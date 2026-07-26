"""Explicitly labeled, development-only replay transport for the operator UI."""

from __future__ import annotations

import asyncio
import json
import os
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.protocol import ProtocolModel, ServerEvent

DEV_REPLAY_ENV = "DEV_REPLAY"
REPLAY_LABEL = "REPLAY — recorded sequence"
REPLAY_SOURCE = "recorded_replay"
MAX_PENDING_REPLAYS = 20
FIXTURE_DIRECTORY = Path(__file__).parents[1] / "tests" / "fixtures"

router = APIRouter()


class ReplayFixture(StrEnum):
    """The reviewed canned operator stories."""

    HAPPY = "happy"
    THIRD_PARTY = "third_party"
    TAKEOVER = "takeover"


FIXTURE_FILES = {
    ReplayFixture.HAPPY: "replay_happy.json",
    ReplayFixture.THIRD_PARTY: "replay_third_party.json",
    ReplayFixture.TAKEOVER: "replay_takeover.json",
}


class ReplayRequest(ProtocolModel):
    """Request body for ``POST /api/dev/replay``."""

    fixture: ReplayFixture


class ReplayStartResponse(ProtocolModel):
    """One-time replay session returned to the development UI."""

    replay: Literal[True] = True
    replay_label: Literal["REPLAY — recorded sequence"] = REPLAY_LABEL
    call_id: str
    websocket_path: str


class ReplayFrame(BaseModel):
    """One validated fixture event and its intentionally visible pacing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    delay_ms: int = Field(ge=300, le=800)
    event: ServerEvent


@dataclass(frozen=True, slots=True)
class ReplaySession:
    """A pending one-shot replay stream."""

    call_id: str
    frames: tuple[ReplayFrame, ...]


class ReplayStore:
    """Small bounded in-memory registry for one-shot development sessions."""

    def __init__(self) -> None:
        self._sessions: OrderedDict[str, ReplaySession] = OrderedDict()
        self._lock = asyncio.Lock()

    async def create(self, fixture: ReplayFixture) -> ReplaySession:
        """Create a uniquely scoped replay and evict abandoned oldest entries."""
        call_id = f"replay-{uuid4()}"
        session = ReplaySession(
            call_id=call_id,
            frames=load_replay_fixture(fixture, call_id=call_id),
        )
        async with self._lock:
            self._sessions[call_id] = session
            while len(self._sessions) > MAX_PENDING_REPLAYS:
                self._sessions.popitem(last=False)
        return session

    async def pop(self, call_id: str) -> ReplaySession | None:
        """Consume a session so a fixture cannot masquerade as a live shared call."""
        async with self._lock:
            return self._sessions.pop(call_id, None)


Sleep = Callable[[float], Awaitable[None]]
_sleep: Sleep = asyncio.sleep


def replay_enabled() -> bool:
    """Return true only for an explicit development opt-in."""
    return os.getenv(DEV_REPLAY_ENV) == "1"


def _store(application: FastAPI) -> ReplayStore:
    existing = getattr(application.state, "replay_store", None)
    if isinstance(existing, ReplayStore):
        return existing
    created = ReplayStore()
    application.state.replay_store = created
    return created


def load_replay_fixture(
    fixture: ReplayFixture,
    *,
    call_id: str,
) -> tuple[ReplayFrame, ...]:
    """Load and validate a reviewed JSON fixture through the real v0 event model."""
    path = FIXTURE_DIRECTORY / FIXTURE_FILES[fixture]
    try:
        raw_frames = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        message = f"Replay fixture {fixture.value!r} is unavailable or invalid."
        raise RuntimeError(message) from error

    if not isinstance(raw_frames, list) or not raw_frames:
        raise RuntimeError(f"Replay fixture {fixture.value!r} must contain at least one frame.")

    frames: list[ReplayFrame] = []
    try:
        for raw_frame in raw_frames:
            frame = ReplayFrame.model_validate(raw_frame)
            event = frame.event.model_copy(update={"call_id": call_id})
            if event.payload.get("source") != REPLAY_SOURCE:
                raise ValueError("every replay event must carry the recorded-replay source marker")
            if event.payload.get("replay_label") != REPLAY_LABEL:
                raise ValueError("every replay event must carry the visible replay label")
            frames.append(frame.model_copy(update={"event": event}))
    except (TypeError, ValueError, ValidationError) as error:
        raise RuntimeError(f"Replay fixture {fixture.value!r} violates the v0 contract.") from error

    sequences = [frame.event.seq for frame in frames]
    if sequences != list(range(1, len(frames) + 1)):
        raise RuntimeError(
            f"Replay fixture {fixture.value!r} sequence must be contiguous and start at one."
        )
    return tuple(frames)


@router.post("/api/dev/replay", response_model=ReplayStartResponse, tags=["development"])
async def start_replay(body: ReplayRequest, request: Request) -> ReplayStartResponse:
    """Create a replay session only when the backend explicitly opts in."""
    if not replay_enabled():
        raise HTTPException(status_code=404, detail="Development replay is disabled.")

    session = await _store(request.app).create(body.fixture)
    return ReplayStartResponse(
        call_id=session.call_id,
        websocket_path=f"/ws/dev/replay/{session.call_id}",
    )


@router.websocket("/ws/dev/replay/{call_id}")
async def replay_websocket(websocket: WebSocket, call_id: str) -> None:
    """Stream one reviewed sequence, then permanently consume the replay."""
    if not replay_enabled():
        await websocket.close(code=1008, reason="Development replay is disabled.")
        return

    session = await _store(websocket.app).pop(call_id)
    if session is None:
        await websocket.close(code=1008, reason="Unknown or already consumed replay.")
        return

    await websocket.accept()
    try:
        for frame in session.frames:
            await _sleep(frame.delay_ms / 1_000)
            await websocket.send_json(frame.event.model_dump(mode="json", by_alias=True))
    except WebSocketDisconnect:
        return
