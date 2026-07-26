"""Tests for the mutation-free preflight policy engine."""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import EvidenceLedger, migrate_schema
from app.preflight import (
    AUDIO_OUTPUT_HEADER,
    CONTACT_CAP_POLICY_DETAIL,
    MICROPHONE_HEADER,
    PreflightInputs,
    evaluate_preflight,
    router,
)
from app.protocol import PROTOCOL_VERSION, PreflightResult
from app.seeds import reset_and_reseed_demo_cases


def ready_inputs(**overrides: object) -> PreflightInputs:
    values: dict[str, object] = {
        "microphone_permission": True,
        "audio_output_confirmed": True,
        "backend_healthy": True,
        "sarvam_configured": True,
        "case_eligible": True,
        "contact_cap_remaining": 2,
        "active_session_exists": False,
    }
    values.update(overrides)
    return PreflightInputs(**values)  # type: ignore[arg-type]


def check_map(inputs: PreflightInputs) -> dict[str, bool]:
    return {check.name: check.passed for check in evaluate_preflight(inputs).checks}


def test_all_green_is_ready_with_exact_check_order() -> None:
    response = evaluate_preflight(ready_inputs())

    assert response.result is PreflightResult.READY
    assert [check.name for check in response.checks] == [
        "microphone",
        "audio_output",
        "backend",
        "sarvam_configuration",
        "eligibility",
        "contact_cap",
        "active_session",
    ]
    assert all(check.passed for check in response.checks)


def test_microphone_denial_is_a_named_technical_block() -> None:
    response = evaluate_preflight(ready_inputs(microphone_permission=False))

    assert response.result is PreflightResult.BLOCKED_TECHNICAL
    assert check_map(ready_inputs(microphone_permission=False))["microphone"] is False
    microphone = response.checks[0]
    assert "browser settings" in microphone.detail


def test_backend_failure_is_a_named_technical_block() -> None:
    response = evaluate_preflight(ready_inputs(backend_healthy=False))

    assert response.result is PreflightResult.BLOCKED_TECHNICAL
    assert check_map(ready_inputs(backend_healthy=False))["backend"] is False


def test_contact_cap_is_a_non_overridable_policy_block_without_call_row() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)

    capped = connection.execute(
        """
        SELECT eligibility, contact_cap_remaining
        FROM cases
        WHERE id = ?
        """,
        ("case-capped-001",),
    ).fetchone()
    response = evaluate_preflight(
        ready_inputs(
            case_eligible=bool(capped["eligibility"]),
            contact_cap_remaining=int(capped["contact_cap_remaining"]),
        )
    )

    assert response.result is PreflightResult.BLOCKED_POLICY
    assert (
        check_map(ready_inputs(contact_cap_remaining=int(capped["contact_cap_remaining"])))[
            "contact_cap"
        ]
        is False
    )
    assert "cannot override" in next(
        check.detail for check in response.checks if check.name == "contact_cap"
    )
    assert next(check.detail for check in response.checks if check.name == "contact_cap") == (
        CONTACT_CAP_POLICY_DETAIL
    )
    assert connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
    connection.close()


def test_active_session_blocks_a_second_start_during_preflight() -> None:
    response = evaluate_preflight(ready_inputs(active_session_exists=True))

    assert response.result is PreflightResult.BLOCKED_POLICY
    assert check_map(ready_inputs(active_session_exists=True))["active_session"] is False


def test_technical_failure_takes_precedence_over_policy_failure() -> None:
    response = evaluate_preflight(
        ready_inputs(microphone_permission=False, contact_cap_remaining=0)
    )

    assert response.result is PreflightResult.BLOCKED_TECHNICAL


def test_negative_contact_cap_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        ready_inputs(contact_cap_remaining=-1)


@pytest.fixture
def preflight_client() -> TestClient:
    connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    application = FastAPI()
    application.state.evidence_ledger = ledger
    application.state.sarvam_api_key = "test-only-non-secret"
    application.include_router(router)
    with TestClient(application) as client:
        yield client
    connection.close()


def preflight_headers(*, microphone: str = "granted", audio: str = "confirmed") -> dict[str, str]:
    return {
        MICROPHONE_HEADER: microphone,
        AUDIO_OUTPUT_HEADER: audio,
    }


def test_preflight_endpoint_names_denied_microphone(
    preflight_client: TestClient,
) -> None:
    response = preflight_client.post(
        "/api/preflight",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-rakesh-001"},
        headers=preflight_headers(microphone="denied"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == PreflightResult.BLOCKED_TECHNICAL
    assert next(check for check in body["checks"] if check["name"] == "microphone")["pass"] is False


def test_capped_case_endpoint_blocks_without_creating_a_call(
    preflight_client: TestClient,
) -> None:
    response = preflight_client.post(
        "/api/preflight",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-capped-001"},
        headers=preflight_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == PreflightResult.BLOCKED_POLICY
    contact_cap = next(check for check in body["checks"] if check["name"] == "contact_cap")
    assert contact_cap == {
        "api_version": PROTOCOL_VERSION,
        "name": "contact_cap",
        "pass": False,
        "detail": CONTACT_CAP_POLICY_DETAIL,
    }
    denied_start = preflight_client.post(
        "/api/call/start",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-capped-001"},
    )
    assert denied_start.status_code == 409
    ledger = preflight_client.app.state.evidence_ledger
    assert ledger.connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0


def test_ready_preflight_allows_one_start_and_database_rejects_double_start(
    preflight_client: TestClient,
) -> None:
    first_preflight = preflight_client.post(
        "/api/preflight",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-rakesh-001"},
        headers=preflight_headers(),
    )
    first_start = preflight_client.post(
        "/api/call/start",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-rakesh-001"},
    )

    assert first_preflight.json()["result"] == PreflightResult.READY
    assert first_start.status_code == 200
    assert first_start.json()["call_id"].startswith("call-")

    second_preflight = preflight_client.post(
        "/api/preflight",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-rakesh-001"},
        headers=preflight_headers(),
    )
    second_start = preflight_client.post(
        "/api/call/start",
        json={"api_version": PROTOCOL_VERSION, "case_id": "case-rakesh-001"},
    )

    assert second_preflight.json()["result"] == PreflightResult.BLOCKED_POLICY
    assert second_start.status_code == 409
    ledger = preflight_client.app.state.evidence_ledger
    assert ledger.connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1


def test_cases_endpoint_omits_private_account_and_verification_fields(
    preflight_client: TestClient,
) -> None:
    response = preflight_client.get("/api/cases")

    assert response.status_code == 200
    body = response.json()
    assert len(body["cases"]) == 2
    serialized = response.text.casefold()
    assert "lender" not in serialized
    assert "outstanding" not in serialized
    assert "reference_last4" not in serialized
