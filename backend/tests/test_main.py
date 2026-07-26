"""Scaffold-level smoke tests."""

import sqlite3
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import EvidenceLedger, migrate_schema
from app.main import _discard_call_session, _production_voice_binding, app
from app.preflight import AUDIO_OUTPUT_HEADER, MICROPHONE_HEADER
from app.preflight import router as preflight_router
from app.reset import RESET_CONFIRMATION
from app.reset import router as reset_router
from app.seeds import RAKESH_CASE, reset_and_reseed_demo_cases
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
