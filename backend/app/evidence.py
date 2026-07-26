"""Read-only REST and WebSocket views over persisted evidence-ledger rows."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from app.contracts import LedgerEventType
from app.db import EvidenceLedger
from app.protocol import EventType, EvidenceResponse, ServerEvent

PERSISTED_LEDGER_SOURCE = "persisted_ledger"
EVIDENCE_WEBSOCKET_PATH = "/ws/evidence/{call_id}"
EVIDENCE_POLL_SECONDS = 0.05

router = APIRouter()


def _ledger_for(application: Any) -> EvidenceLedger:
    ledger = getattr(application.state, "evidence_ledger", None)
    if not isinstance(ledger, EvidenceLedger):
        raise RuntimeError("evidence ledger is unavailable")
    return ledger


def _snapshot(raw: str) -> dict[str, str]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("evidence snapshot must be an object")
    allowed = {"call", "identity", "promise"}
    if set(value) != allowed or not all(isinstance(item, str) for item in value.values()):
        raise ValueError("evidence snapshot violates the state contract")
    return {key: str(value[key]) for key in sorted(allowed)}


def _transition_machine(
    before: dict[str, str],
    after: dict[str, str],
    *,
    ledger_type: str,
) -> str:
    changed = [
        machine for machine in ("call", "identity", "promise") if before[machine] != after[machine]
    ]
    if len(changed) == 1:
        return changed[0]
    if ledger_type == "VERIFICATION_ATTEMPT":
        return "identity"
    if ledger_type.startswith("PROMISE_"):
        return "promise"
    return "call"


def _base_payload(ledger_type: str, redacted_reason: str) -> dict[str, object]:
    return {
        "source": PERSISTED_LEDGER_SOURCE,
        "ledger_type": ledger_type,
        "reason": redacted_reason,
    }


def _event_category(ledger_type: str) -> EventType:
    if ledger_type == LedgerEventType.TOOL_DECISION.value:
        return EventType.TOOL_DECISION
    if ledger_type == LedgerEventType.OUTPUT_BLOCKED.value:
        return EventType.GUARD_BLOCK
    if ledger_type == LedgerEventType.DISPOSITION_SET.value:
        return EventType.DISPOSITION
    if ledger_type == LedgerEventType.TECHNICAL_FAILURE.value:
        return EventType.ERROR
    if ledger_type == LedgerEventType.SAFE_UTTERANCE.value:
        return EventType.UTTERANCE
    if ledger_type in {
        LedgerEventType.TURN_TIMING.value,
        LedgerEventType.AUDIO_SUPPRESSED.value,
    }:
        return EventType.DIAGNOSTIC
    return EventType.STATE_CHANGE


def _row_to_event(row: sqlite3.Row) -> ServerEvent:
    ledger_type = str(row["type"])
    before = _snapshot(str(row["state_before"]))
    after = _snapshot(str(row["state_after"]))
    reason = str(row["redacted_reason"])
    event_type = _event_category(ledger_type)
    payload = _base_payload(ledger_type, reason)

    if event_type is EventType.TOOL_DECISION:
        if row["tool"] is None:
            raise ValueError("tool-decision evidence is missing its typed detail row")
        payload.update(
            {
                "tool": str(row["tool"]),
                "allowed": bool(row["allowed"]),
                "reason": str(row["tool_reason"]),
                "identity_state": str(row["identity_state"]),
                "promise_state": str(row["promise_state"]),
            }
        )
    elif event_type is EventType.GUARD_BLOCK:
        payload["category"] = reason.removeprefix("output_guard:")
    elif event_type is EventType.DISPOSITION:
        if row["disposition"] is None:
            raise ValueError("disposition evidence is missing its terminal call outcome")
        payload["disposition"] = str(row["disposition"])
    elif event_type is EventType.UTTERANCE:
        if row["speaker"] is None or row["guard_result"] is None or row["speech_text"] is None:
            raise ValueError("safe-utterance evidence is missing its typed detail row")
        payload.update(
            {
                "speaker": str(row["speaker"]),
                "guard_result": str(row["guard_result"]),
                "text": str(row["speech_text"]),
            }
        )
    elif event_type is EventType.DIAGNOSTIC:
        payload["component"] = (
            "audio_suppression"
            if ledger_type == LedgerEventType.AUDIO_SUPPRESSED.value
            else "turn_timing"
        )
    elif event_type is EventType.ERROR:
        payload["component"] = reason.removeprefix("technical_failure:")
    else:
        machine = _transition_machine(before, after, ledger_type=ledger_type)
        payload.update(
            {
                "machine": machine,
                "before": before[machine],
                "after": after[machine],
            }
        )

    return ServerEvent(
        type=event_type,
        call_id=str(row["call_id"]),
        seq=int(row["seq"]),
        ts=datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")),
        payload=payload,
    )


def read_evidence_events(
    ledger: EvidenceLedger,
    call_id: str,
    *,
    after_seq: int = 0,
) -> tuple[ServerEvent, ...]:
    """Return the ordered, redacted wire projection of durable rows."""

    call = ledger.connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (call_id,),
    ).fetchone()
    if call is None:
        raise LookupError("call evidence was not found")

    rows = ledger.connection.execute(
        """
        SELECT
            events.call_id,
            events.seq,
            events.ts,
            events.type,
            events.state_before,
            events.state_after,
            events.redacted_reason,
            tool_decisions.tool,
            tool_decisions.allowed,
            tool_decisions.identity_state,
            tool_decisions.promise_state,
            tool_decisions.reason AS tool_reason,
            safe_utterances.speaker,
            safe_utterances.guard_result,
            safe_utterances.speech_text,
            calls.disposition
        FROM events
        JOIN calls ON calls.id = events.call_id
        LEFT JOIN tool_decisions
          ON tool_decisions.call_id = events.call_id
         AND tool_decisions.seq = events.seq
        LEFT JOIN safe_utterances
          ON safe_utterances.call_id = events.call_id
         AND safe_utterances.seq = events.seq
        WHERE events.call_id = ? AND events.seq > ?
        ORDER BY events.seq
        """,
        (call_id, after_seq),
    ).fetchall()
    return tuple(_row_to_event(row) for row in rows)


@router.get(
    "/api/evidence/{call_id}",
    response_model=EvidenceResponse,
    tags=["evidence"],
)
async def get_evidence(call_id: str, request: Request) -> EvidenceResponse:
    """Recover the complete ordered event projection for one persisted call."""

    try:
        events = read_evidence_events(_ledger_for(request.app), call_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        raise HTTPException(
            status_code=503,
            detail="Evidence is temporarily unavailable.",
        ) from error
    return EvidenceResponse(call_id=call_id, events=events)


@router.websocket(EVIDENCE_WEBSOCKET_PATH)
async def evidence_websocket(
    websocket: WebSocket,
    call_id: str,
    after_seq: int = Query(default=0, ge=0),
) -> None:
    """Replay missed rows, then tail SQLite until the call reaches a disposition."""

    try:
        ledger = _ledger_for(websocket.app)
        read_evidence_events(ledger, call_id, after_seq=after_seq)
    except (LookupError, RuntimeError, ValueError, json.JSONDecodeError):
        await websocket.close(code=1008, reason="Call evidence is unavailable.")
        return

    await websocket.accept()
    cursor = after_seq
    try:
        while True:
            events = read_evidence_events(ledger, call_id, after_seq=cursor)
            for event in events:
                await websocket.send_json(event.model_dump(mode="json", by_alias=True))
                cursor = event.seq
                if event.type is EventType.DISPOSITION:
                    await websocket.close(code=1000, reason="Evidence stream complete.")
                    return
            await asyncio.sleep(EVIDENCE_POLL_SECONDS)
    except WebSocketDisconnect:
        return
