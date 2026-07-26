"""API tests for the sanctioned demo-only reset."""

import asyncio
import sqlite3
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import Disposition
from app.db import EvidenceLedger, migrate_schema
from app.preflight import router as preflight_router
from app.protocol import PROTOCOL_VERSION
from app.reset import RESET_CONFIRMATION
from app.reset import router as reset_router
from app.seeds import DEMO_CASES, DEMO_TIME_ANCHOR, reset_and_reseed_demo_cases
from app.state_machine import fresh_call_snapshot


def reset_app() -> tuple[FastAPI, EvidenceLedger]:
    connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    application = FastAPI()
    application.state.evidence_ledger = ledger
    application.state.sarvam_api_key = "configured-in-test"
    application.state.call_session_registrar = lambda call_id: None
    application.state.call_session_discard = lambda call_id: None
    application.include_router(preflight_router)
    application.include_router(reset_router)
    return application, ledger


def confirmation_body() -> dict[str, str]:
    return {
        "api_version": PROTOCOL_VERSION,
        "confirmation": RESET_CONFIRMATION,
    }


def test_reset_router_is_mounted_on_the_production_application() -> None:
    from app.main import app as production_app

    mounted_paths: set[str] = set()
    for route in production_app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            mounted_paths.add(path)
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            mounted_paths.update(
                child.path
                for child in included_router.routes
                if isinstance(getattr(child, "path", None), str)
            )

    assert "/api/reset" in mounted_paths


def preflight_and_start(client: TestClient, case_id: str = "case-rakesh-001") -> str:
    preflight = client.post(
        "/api/preflight",
        json={"api_version": PROTOCOL_VERSION, "case_id": case_id},
        headers={
            "X-Vachan-Microphone": "granted",
            "X-Vachan-Audio-Output": "confirmed",
        },
    )
    assert preflight.status_code == 200
    assert preflight.json()["result"] == "READY"
    start = client.post(
        "/api/call/start",
        json={"api_version": PROTOCOL_VERSION, "case_id": case_id},
    )
    assert start.status_code == 200
    return str(start.json()["call_id"])


def safely_end_call(connection: sqlite3.Connection, call_id: str) -> None:
    connection.execute(
        """
        UPDATE calls
        SET ended = ?, disposition = ?
        WHERE id = ?
        """,
        (
            datetime.now(UTC).isoformat(),
            Disposition.ENDED_OPERATOR.value,
            call_id,
        ),
    )


def test_reset_requires_the_exact_visible_confirmation_phrase() -> None:
    application, _ = reset_app()
    client = TestClient(application)

    missing = client.post("/api/reset", json={"api_version": PROTOCOL_VERSION})
    vague = client.post(
        "/api/reset",
        json={"api_version": PROTOCOL_VERSION, "confirmation": "yes"},
    )
    expanded_scope = client.post(
        "/api/reset",
        json={
            "api_version": PROTOCOL_VERSION,
            "confirmation": RESET_CONFIRMATION,
            "scope": "all data",
        },
    )

    assert missing.status_code == 422
    assert vague.status_code == 422
    assert expanded_scope.status_code == 422


def test_reset_is_refused_during_active_call_without_mutation() -> None:
    application, ledger = reset_app()
    client = TestClient(application)
    active_call_id = preflight_and_start(client)
    before = {
        "cases": ledger.connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
        "calls": ledger.connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0],
    }

    response = client.post("/api/reset", json=confirmation_body())

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Demo reset is unavailable during an active call. End the call safely first."
    }
    assert ledger.connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == before["cases"]
    assert ledger.connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == before["calls"]
    assert ledger.connection.execute("SELECT id FROM calls").fetchone()["id"] == active_call_id


def test_reset_reseeds_only_governed_rows_and_invalidates_ready_state() -> None:
    application, ledger = reset_app()
    client = TestClient(application)
    ledger.connection.execute(
        """
        INSERT INTO cases (
            id, name, eligibility, contact_cap_remaining, mock_label,
            verification_birth_day, verification_birth_month,
            verification_reference_last4, lender_name, outstanding_minor,
            emi_schedule_json, demo_time_anchor
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "non-demo-case",
            "Control",
            True,
            1,
            "NOT DEMO",
            1,
            1,
            "0000",
            "Control",
            0,
            "[]",
            DEMO_TIME_ANCHOR.isoformat(),
        ),
    )
    ready = client.post(
        "/api/preflight",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-rakesh-001"},
        headers={
            "X-Vachan-Microphone": "granted",
            "X-Vachan-Audio-Output": "confirmed",
        },
    )
    assert ready.json()["result"] == "READY"

    response = client.post("/api/reset", json=confirmation_body())
    stale_start = client.post(
        "/api/call/start",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-rakesh-001"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "api_version": PROTOCOL_VERSION,
        "reset": True,
        "seeded_case_count": len(DEMO_CASES),
    }
    assert stale_start.status_code == 409
    rows = ledger.connection.execute(
        "SELECT id, demo_time_anchor FROM cases ORDER BY id"
    ).fetchall()
    assert {row["id"] for row in rows} == {
        "case-rakesh-001",
        "case-capped-001",
        "non-demo-case",
    }
    demo_rows = [row for row in rows if row["id"] != "non-demo-case"]
    assert {row["demo_time_anchor"] for row in demo_rows} == {DEMO_TIME_ANCHOR.isoformat()}


def test_two_reset_rehearsals_get_distinct_call_ids_and_same_ready_behavior() -> None:
    application, ledger = reset_app()
    client = TestClient(application)

    first_call_id = preflight_and_start(client)
    snapshot = fresh_call_snapshot()
    asyncio.run(
        ledger.append_event(
            call_id=first_call_id,
            ts=datetime.now(UTC),
            event_type="STATE_TRANSITION",
            state_before=snapshot,
            state_after=snapshot,
            redacted_reason="reset_rehearsal_event",
        )
    )
    assert ledger.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    safely_end_call(ledger.connection, first_call_id)
    first_reset = client.post("/api/reset", json=confirmation_body())
    assert ledger.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    second_call_id = preflight_and_start(client)
    safely_end_call(ledger.connection, second_call_id)
    second_reset = client.post("/api/reset", json=confirmation_body())

    assert first_reset.status_code == second_reset.status_code == 200
    assert first_reset.json() == second_reset.json()
    assert first_call_id != second_call_id
    assert ledger.connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
