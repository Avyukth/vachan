"""Local deterministic backend used only by the browser evidence E2E suite."""

from __future__ import annotations

import asyncio
import sqlite3
import struct
from datetime import UTC, datetime

from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect

from app.contracts import LedgerEventType, StateSnapshot
from app.db import EvidenceLedger, migrate_schema
from app.evidence import router as evidence_router
from app.protocol import (
    CasesResponse,
    CaseSummary,
    PreflightCheck,
    PreflightResponse,
    PreflightResult,
    StartCallRequest,
    StartCallResponse,
)
from app.seeds import RAKESH_CASE, reset_and_reseed_demo_cases
from app.states import CallState, IdentityState, PromiseState
from app.tools import ToolDecision, ToolName

CALL_ID = "call-browser-e2e"


def _ledger() -> EvidenceLedger:
    connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    return ledger


def _snapshot(identity: IdentityState) -> StateSnapshot:
    return StateSnapshot(
        call=CallState.ACTIVE,
        identity=identity,
        promise=PromiseState.NONE,
    )


def _silent_wav() -> bytes:
    samples = 1_600
    pcm = bytes(samples * 2)
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


ledger = _ledger()
app = FastAPI(title="Vachan evidence browser E2E")
app.state.evidence_ledger = ledger
app.include_router(evidence_router)


@app.get("/api/cases", response_model=CasesResponse)
async def cases() -> CasesResponse:
    return CasesResponse(
        cases=(
            CaseSummary(
                case_id=RAKESH_CASE.case_id,
                borrower_display_name=RAKESH_CASE.borrower_display_name,
                eligible=True,
                contact_cap_remaining=1,
            ),
        )
    )


@app.post("/api/audio/check")
async def audio_check() -> Response:
    return Response(content=_silent_wav(), media_type="audio/wav")


@app.post("/api/preflight", response_model=PreflightResponse)
async def preflight() -> PreflightResponse:
    return PreflightResponse(
        result=PreflightResult.READY,
        checks=(PreflightCheck(name="backend", **{"pass": True}, detail="Backend is reachable."),),
    )


@app.post("/api/call/start", response_model=StartCallResponse)
async def start_call(payload: StartCallRequest) -> StartCallResponse:
    assert payload.case_id == RAKESH_CASE.case_id
    existing = ledger.connection.execute(
        "SELECT 1 FROM calls WHERE id = ?",
        (CALL_ID,),
    ).fetchone()
    if existing is None:
        ledger.connection.execute(
            """
            INSERT INTO calls (id, case_id, started, transport)
            VALUES (?, ?, ?, ?)
            """,
            (CALL_ID, RAKESH_CASE.case_id, datetime.now(UTC).isoformat(), "streaming_pcm16_ws"),
        )
        unverified = _snapshot(IdentityState.UNVERIFIED)
        verifying = _snapshot(IdentityState.VERIFYING)
        confirmed = _snapshot(IdentityState.CONFIRMED)
        await ledger.append_event(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            event_type=LedgerEventType.STATE_TRANSITION,
            state_before=unverified,
            state_after=verifying,
            redacted_reason="verification_started",
        )
        await ledger.append_tool_decision(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            decision=ToolDecision(
                tool=ToolName.READ_MOCK_ACCOUNT,
                allowed=False,
                call_state=CallState.ACTIVE.value,
                identity_state=IdentityState.VERIFYING.value,
                promise_state=PromiseState.NONE.value,
                reason="identity_state=VERIFYING",
            ),
            state=verifying,
        )
        await ledger.append_event(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            event_type="VERIFICATION_ATTEMPT",
            state_before=verifying,
            state_after=verifying,
            redacted_reason=(
                "verification_attempt:"
                '{"attempt_number":1,"fields":[{"field_name":"birth_day","passed":true},'
                '{"field_name":"reference_last4","passed":true}],"passed":true}'
            ),
        )
        await ledger.append_event(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            event_type=LedgerEventType.STATE_TRANSITION,
            state_before=verifying,
            state_after=confirmed,
            redacted_reason="verification_confirmed",
        )
    return StartCallResponse(call_id=CALL_ID)


@app.websocket("/ws/call/{call_id}")
async def voice_socket(websocket: WebSocket, call_id: str) -> None:
    if call_id != CALL_ID:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await websocket.send_json({"type": "ready", "sample_rate": 16_000, "encoding": "pcm_s16le"})
    try:
        while True:
            await websocket.receive_bytes()
            await asyncio.sleep(0)
    except WebSocketDisconnect:
        return
