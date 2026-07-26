"""Scaffold-level smoke tests."""

import asyncio
import sqlite3
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import EvidenceLedger, migrate_schema
from app.main import (
    _discard_call_session,
    _end_normal_call,
    _production_voice_binding,
    app,
)
from app.preflight import AUDIO_OUTPUT_HEADER, MICROPHONE_HEADER
from app.preflight import router as preflight_router
from app.reset import RESET_CONFIRMATION
from app.reset import router as reset_router
from app.seeds import RAKESH_CASE, reset_and_reseed_demo_cases
from app.states import CallState
from app.stt import SttSessionRegistry
from app.takeover import TakeoverRegistry
from app.takeover import router as takeover_router


def test_application_metadata_and_health_route() -> None:
    """The backend exposes a named FastAPI app and its liveness route."""
    assert app.title == "Vachan API"
    assert any(getattr(route, "path", None) == "/healthz" for route in app.routes)


def test_live_binding_is_created_lazily_for_a_preflight_call() -> None:
    application = FastAPI()
    ledger = EvidenceLedger.open(":memory:")
    reset_and_reseed_demo_cases(ledger)
    ledger.connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (
            "call-live-main",
            RAKESH_CASE.case_id,
            datetime.now(UTC).isoformat(),
            "streaming_pcm16_ws",
        ),
    )
    application.state.evidence_ledger = ledger
    application.state.sarvam_api_key = "backend-only-test-key"
    application.state.voice_calls = None
    application.state.stt_sessions = SttSessionRegistry()
    application.state.takeover_sessions = TakeoverRegistry()

    first = _production_voice_binding(application, "call-live-main")
    second = _production_voice_binding(application, "call-live-main")

    assert first is second
    assert first.is_call_active()
    _discard_call_session(application, "call-live-main")
    assert _production_voice_binding(application, "call-live-main") is not first
    ledger.close()


def test_real_start_registers_takeover_and_reasoned_end_unlocks_reset() -> None:
    application = FastAPI()
    connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    application.state.evidence_ledger = ledger
    application.state.sarvam_api_key = "backend-only-test-key"
    application.state.voice_calls = None
    application.state.stt_sessions = SttSessionRegistry()
    application.state.takeover_sessions = TakeoverRegistry()
    application.state.call_session_registrar = lambda call_id: _production_voice_binding(
        application,
        call_id,
    )
    application.state.call_session_discard = lambda call_id: _discard_call_session(
        application,
        call_id,
    )
    application.include_router(preflight_router)
    application.include_router(takeover_router)
    application.include_router(reset_router)

    with TestClient(application) as client:
        preflight = client.post(
            "/api/preflight",
            json={"api_version": "v0", "case_id": RAKESH_CASE.case_id},
            headers={
                MICROPHONE_HEADER: "granted",
                AUDIO_OUTPUT_HEADER: "confirmed",
            },
        )
        started = client.post(
            "/api/call/start",
            json={"api_version": "v0", "case_id": RAKESH_CASE.case_id},
        )
        assert preflight.json()["result"] == "READY"
        assert started.status_code == 200
        call_id = started.json()["call_id"]
        assert application.state.takeover_sessions.get(call_id) is not None

        takeover = client.post(
            "/api/takeover",
            json={"api_version": "v0", "call_id": call_id},
        )
        ended = client.post(
            "/api/call/end",
            json={
                "api_version": "v0",
                "call_id": call_id,
                "reason": "Operator completed the conversation",
            },
        )
        disposition_count = ledger.connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = ? AND type = 'DISPOSITION_SET'",
            (call_id,),
        ).fetchone()[0]
        reset = client.post(
            "/api/reset",
            json={
                "api_version": "v0",
                "confirmation": RESET_CONFIRMATION,
            },
        )

    assert takeover.status_code == 200
    assert takeover.json()["payload"]["after"] == "OPERATOR_TAKEOVER"
    assert ended.status_code == 200
    assert ended.json()["payload"]["disposition"] == "ENDED_OPERATOR"
    assert disposition_count == 1
    assert reset.status_code == 200
    assert ledger.connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
    ledger.close()


def test_normal_end_allows_fresh_preflight_and_distinct_second_start() -> None:
    application = FastAPI()
    connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    application.state.evidence_ledger = ledger
    application.state.sarvam_api_key = "backend-only-test-key"
    application.state.voice_calls = None
    application.state.stt_sessions = SttSessionRegistry()
    application.state.takeover_sessions = TakeoverRegistry()
    application.state.call_session_registrar = lambda call_id: _production_voice_binding(
        application,
        call_id,
    )
    application.state.call_session_discard = lambda call_id: _discard_call_session(
        application,
        call_id,
    )
    application.state.normal_call_ender = lambda call_id, reason: _end_normal_call(
        application,
        call_id,
        reason,
    )
    application.include_router(preflight_router)
    application.include_router(takeover_router)

    with TestClient(application) as client:
        first_preflight = client.post(
            "/api/preflight",
            json={"api_version": "v0", "case_id": RAKESH_CASE.case_id},
            headers={
                MICROPHONE_HEADER: "granted",
                AUDIO_OUTPUT_HEADER: "confirmed",
            },
        )
        first_start = client.post(
            "/api/call/start",
            json={"api_version": "v0", "case_id": RAKESH_CASE.case_id},
        )
        first_call_id = first_start.json()["call_id"]
        first_binding = _production_voice_binding(application, first_call_id)
        asyncio.run(first_binding.controller.activate_existing_call())

        assert first_preflight.json()["result"] == "READY"
        assert first_start.status_code == 200
        assert first_binding.controller.snapshot.call is CallState.ACTIVE

        first_end = client.post(
            "/api/call/end",
            json={
                "api_version": "v0",
                "call_id": first_call_id,
                "reason": "Normal operator close after read-back",
            },
        )
        first_terminal_events = ledger.connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = ? AND type = 'DISPOSITION_SET'",
            (first_call_id,),
        ).fetchone()[0]

        second_preflight = client.post(
            "/api/preflight",
            json={"api_version": "v0", "case_id": RAKESH_CASE.case_id},
            headers={
                MICROPHONE_HEADER: "granted",
                AUDIO_OUTPUT_HEADER: "confirmed",
            },
        )
        second_start = client.post(
            "/api/call/start",
            json={"api_version": "v0", "case_id": RAKESH_CASE.case_id},
        )
        second_call_id = second_start.json()["call_id"]
        second_binding = _production_voice_binding(application, second_call_id)
        asyncio.run(second_binding.controller.activate_existing_call())

        assert first_end.status_code == 200
        assert first_end.json()["payload"]["disposition"] == "ENDED_OPERATOR"
        assert first_terminal_events == 1
        assert second_preflight.json()["result"] == "READY"
        assert second_start.status_code == 200
        assert second_call_id != first_call_id
        assert second_binding.controller.snapshot.call is CallState.ACTIVE

        second_end = client.post(
            "/api/call/end",
            json={
                "api_version": "v0",
                "call_id": second_call_id,
                "reason": "Test cleanup",
            },
        )
        assert second_end.status_code == 200

    ledger.close()
