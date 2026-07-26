"""Integration tests for the persisted live-evidence transport."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import EvidenceLedger, migrate_schema
from app.evidence import PERSISTED_LEDGER_SOURCE, read_evidence_events, router
from app.seeds import RAKESH_CASE, reset_and_reseed_demo_cases
from app.states import CallState, IdentityState, PromiseState
from app.tools import ToolDecision, ToolName

CALL_ID = "call-live-evidence"


def _ledger() -> EvidenceLedger:
    connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (CALL_ID, RAKESH_CASE.case_id, datetime.now(UTC).isoformat(), "streaming_pcm16_ws"),
    )
    return ledger


def _state(
    *,
    call: CallState = CallState.ACTIVE,
    identity: IdentityState = IdentityState.UNVERIFIED,
    promise: PromiseState = PromiseState.NONE,
) -> StateSnapshot:
    return StateSnapshot(call=call, identity=identity, promise=promise)


def _append_proof(ledger: EvidenceLedger) -> None:
    unverified = _state()
    verifying = _state(identity=IdentityState.VERIFYING)
    confirmed = _state(identity=IdentityState.CONFIRMED)
    asyncio.run(
        ledger.append_event(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            event_type=LedgerEventType.STATE_TRANSITION,
            state_before=unverified,
            state_after=verifying,
            redacted_reason="verification_started",
        )
    )
    asyncio.run(
        ledger.append_tool_decision(
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
    )
    asyncio.run(
        ledger.append_event(
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
    )
    asyncio.run(
        ledger.append_event(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            event_type=LedgerEventType.STATE_TRANSITION,
            state_before=verifying,
            state_after=confirmed,
            redacted_reason="verification_confirmed",
        )
    )
    asyncio.run(
        ledger.set_ended_operator(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            reason="integration_test",
            state=_state(call=CallState.ENDED, identity=IdentityState.CONFIRMED),
        )
    )


def _application(ledger: EvidenceLedger) -> FastAPI:
    application = FastAPI()
    application.state.evidence_ledger = ledger
    application.include_router(router)
    return application


def test_get_and_websocket_return_the_identical_ordered_persisted_projection() -> None:
    ledger = _ledger()
    _append_proof(ledger)

    with TestClient(_application(ledger)) as client:
        response = client.get(f"/api/evidence/{CALL_ID}")
        assert response.status_code == 200
        rest_events = response.json()["events"]

        streamed: list[dict[str, object]] = []
        with client.websocket_connect(f"/ws/evidence/{CALL_ID}?after_seq=0") as websocket:
            for _ in rest_events:
                streamed.append(websocket.receive_json())

    diagnostics = [
        (event["seq"], event["type"], event["payload"]["source"]) for event in rest_events
    ]
    assert streamed == rest_events, diagnostics
    assert [event["seq"] for event in rest_events] == list(range(1, 6)), diagnostics
    assert all(event["payload"]["source"] == PERSISTED_LEDGER_SOURCE for event in rest_events), (
        diagnostics
    )
    assert sum(event["type"] == "disposition" for event in rest_events) == 1
    assert rest_events[-1]["payload"]["disposition"] == Disposition.ENDED_OPERATOR.value
    ledger.close()


def test_reconnect_replays_only_rows_after_the_acknowledged_sequence() -> None:
    ledger = _ledger()
    _append_proof(ledger)

    with TestClient(_application(ledger)) as client:
        recovered = client.get(f"/api/evidence/{CALL_ID}").json()["events"]
        with client.websocket_connect(f"/ws/evidence/{CALL_ID}?after_seq=3") as websocket:
            replayed = [websocket.receive_json(), websocket.receive_json()]

    assert [event["seq"] for event in recovered] == [1, 2, 3, 4, 5]
    assert [event["seq"] for event in replayed] == [4, 5]
    ledger.close()


def test_backend_boundary_exposes_only_redacted_verification_and_guard_metadata() -> None:
    ledger = _ledger()
    verifying = _state(identity=IdentityState.VERIFYING)
    asyncio.run(
        ledger.append_event(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            event_type="VERIFICATION_ATTEMPT",
            state_before=verifying,
            state_after=verifying,
            redacted_reason=(
                "verification_attempt:"
                '{"attempt_number":1,"fields":[{"field_name":"birth_day","passed":false},'
                '{"field_name":"reference_last4","passed":false}],"passed":false}'
            ),
        )
    )
    asyncio.run(
        ledger.append_event(
            call_id=CALL_ID,
            ts=datetime.now(UTC),
            event_type=LedgerEventType.OUTPUT_BLOCKED,
            state_before=verifying,
            state_after=verifying,
            redacted_reason="output_guard:account_disclosure",
        )
    )

    serialized = json.dumps(
        [event.payload for event in read_evidence_events(ledger, CALL_ID)],
        sort_keys=True,
    )
    assert "birth_day" in serialized
    assert "reference_last4" in serialized
    assert "account_disclosure" in serialized
    assert "blocked draft" not in serialized.casefold()
    for forbidden in ("14", "4729", "four seven two nine"):
        assert forbidden not in serialized
    ledger.close()


def test_unknown_call_fails_without_cross_call_evidence() -> None:
    ledger = _ledger()
    with TestClient(_application(ledger)) as client:
        response = client.get("/api/evidence/call-missing")
    assert response.status_code == 404
    assert CALL_ID not in response.text
    ledger.close()
