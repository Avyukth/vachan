"""Durable verification evidence contracts for controller integration."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from app.contracts import Disposition, StateSnapshot
from app.controller import DialogueController
from app.db import EvidenceLedger
from app.seeds import RAKESH_CASE
from app.states import CallState, IdentityState, PromiseState
from app.tools import ToolPermissionDenied
from app.verification import (
    COMPLETE_VERIFICATION_INPUT_MARKER,
    ExpectedVerification,
    FieldCheck,
    VerificationAttemptEvidence,
    VerificationField,
    VerificationSession,
    VerificationStatus,
    VerificationSubmission,
    reconstruct_verification_session,
    submit_verification,
    verification_input_marker,
)
from app.verification_evidence import (
    VERIFICATION_ATTEMPT_EVENT,
    VerificationEvidenceRepository,
)
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn

EXPECTED = ExpectedVerification(
    birth_day=14,
    birth_month=9,
    reference_last4="4729",
)


def _controller(
    connection: sqlite3.Connection,
    frozen_demo_clock,
    *,
    name: str,
    turns: tuple[tuple[str, dict[str, object]], ...],
) -> tuple[DialogueController, FakeSarvamClient]:
    fake = FakeSarvamClient(
        SarvamScenario(
            name=name,
            turns=tuple(
                ScriptedTurn(transcript=transcript, action=action) for transcript, action in turns
            ),
        )
    )
    return (
        DialogueController(
            call_id=f"call-{name}",
            case=RAKESH_CASE,
            ledger=EvidenceLedger(connection),
            sarvam=fake,
            clock=frozen_demo_clock.now,
        ),
        fake,
    )


def _attempt(
    number: int,
    *,
    birth_passed: bool,
    reference_passed: bool,
) -> VerificationAttemptEvidence:
    return VerificationAttemptEvidence(
        attempt=number,
        checks=(
            FieldCheck(VerificationField.BIRTH_DAY_MONTH, birth_passed),
            FieldCheck(VerificationField.REFERENCE_LAST4, reference_passed),
        ),
        passed=birth_passed and reference_passed,
    )


def test_persistence_shape_contains_only_approved_field_results() -> None:
    result = submit_verification(
        VerificationSession(),
        VerificationSubmission(
            birth_day_month="चौदह सितंबर",
            reference_last4="0000",
        ),
        EXPECTED,
    )

    assert result.evidence.as_log_record() == {
        "event": "VERIFICATION_ATTEMPT",
        "attempt": 1,
        "fields": [
            {"field": "birth_day_month", "passed": True},
            {"field": "reference_last4", "passed": False},
        ],
        "passed": False,
    }
    serialized = json.dumps(result.evidence.as_log_record(), ensure_ascii=False, sort_keys=True)
    for forbidden in ("4729", "0000", "चौदह", "सितंबर", "14", '"9"'):
        assert forbidden not in serialized


def test_redacted_reason_round_trip_is_exact_and_rejects_extra_fields() -> None:
    evidence = _attempt(1, birth_passed=True, reference_passed=False)
    serialized = evidence.as_redacted_reason()

    assert VerificationAttemptEvidence.from_redacted_reason(serialized) == evidence
    record = json.loads(serialized)
    record["submitted_value"] = "must never be accepted"
    with pytest.raises(ValueError, match="unexpected top-level shape"):
        VerificationAttemptEvidence.from_redacted_reason(json.dumps(record))


def test_model_marker_reveals_only_submission_completeness() -> None:
    complete = VerificationSubmission(
        birth_day_month="चौदह सितंबर",
        reference_last4="4729",
    )
    incomplete = VerificationSubmission(
        birth_day_month="चौदह सितंबर",
        reference_last4="not provided",
    )

    assert verification_input_marker(complete) == COMPLETE_VERIFICATION_INPUT_MARKER
    assert verification_input_marker(incomplete) == "[verification input withheld]"
    for forbidden in ("4729", "चौदह", "सितंबर"):
        assert forbidden not in verification_input_marker(complete)


@pytest.mark.parametrize(
    ("attempts", "expected"),
    [
        ((), VerificationSession()),
        (
            (_attempt(1, birth_passed=False, reference_passed=True),),
            VerificationSession(attempts=1, status=VerificationStatus.PENDING),
        ),
        (
            (_attempt(1, birth_passed=True, reference_passed=True),),
            VerificationSession(attempts=1, status=VerificationStatus.CONFIRMED),
        ),
        (
            (
                _attempt(1, birth_passed=False, reference_passed=False),
                _attempt(2, birth_passed=True, reference_passed=True),
            ),
            VerificationSession(attempts=2, status=VerificationStatus.CONFIRMED),
        ),
        (
            (
                _attempt(1, birth_passed=False, reference_passed=True),
                _attempt(2, birth_passed=True, reference_passed=False),
            ),
            VerificationSession(attempts=2, status=VerificationStatus.FAILED),
        ),
    ],
)
def test_session_reconstruction_consumes_only_durable_attempts(
    attempts: tuple[VerificationAttemptEvidence, ...],
    expected: VerificationSession,
) -> None:
    assert reconstruct_verification_session(attempts) == expected


@pytest.mark.parametrize(
    "attempts",
    [
        (_attempt(2, birth_passed=False, reference_passed=False),),
        (
            _attempt(1, birth_passed=True, reference_passed=True),
            _attempt(2, birth_passed=False, reference_passed=False),
        ),
    ],
)
def test_session_reconstruction_rejects_gaps_and_post_success_attempts(
    attempts: tuple[VerificationAttemptEvidence, ...],
) -> None:
    with pytest.raises(ValueError):
        reconstruct_verification_session(attempts)


def test_repository_persists_exact_rows_and_reconstructs_session(
    db_connection: sqlite3.Connection,
    evidence_ledger,
    frozen_demo_clock,
) -> None:
    call_id = "call-verification-evidence"
    db_connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (
            call_id,
            RAKESH_CASE.case_id,
            frozen_demo_clock.now().isoformat(),
            "test",
        ),
    )
    state = StateSnapshot(
        call=CallState.ACTIVE,
        identity=IdentityState.VERIFYING,
        promise=PromiseState.NONE,
    )
    attempts = (
        _attempt(1, birth_passed=False, reference_passed=True),
        _attempt(2, birth_passed=True, reference_passed=True),
    )
    repository = VerificationEvidenceRepository(evidence_ledger)

    async def persist() -> None:
        for evidence in attempts:
            await repository.append_attempt(
                call_id=call_id,
                ts=frozen_demo_clock.now(),
                state=state,
                evidence=evidence,
            )

    asyncio.run(persist())

    rows = db_connection.execute(
        """
        SELECT type, redacted_reason
        FROM events
        WHERE call_id = ?
        ORDER BY seq
        """,
        (call_id,),
    ).fetchall()
    assert [row["type"] for row in rows] == [VERIFICATION_ATTEMPT_EVENT] * 2
    assert [
        VerificationAttemptEvidence.from_redacted_reason(row["redacted_reason"]) for row in rows
    ] == list(attempts)
    assert repository.reconstruct_session(call_id) == VerificationSession(
        attempts=2,
        status=VerificationStatus.CONFIRMED,
    )


def test_failed_event_write_cannot_consume_an_attempt(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    call_id = "call-verification-evidence-failure"
    db_connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (
            call_id,
            RAKESH_CASE.case_id,
            frozen_demo_clock.now().isoformat(),
            "test",
        ),
    )
    state = StateSnapshot(
        call=CallState.ACTIVE,
        identity=IdentityState.VERIFYING,
        promise=PromiseState.NONE,
    )

    class FailingLedger(EvidenceLedger):
        async def append_event(self, **kwargs: object) -> int:
            raise sqlite3.OperationalError("injected verification evidence failure")

    repository = VerificationEvidenceRepository(FailingLedger(db_connection))

    async def persist() -> None:
        await repository.append_attempt(
            call_id=call_id,
            ts=frozen_demo_clock.now(),
            state=state,
            evidence=_attempt(1, birth_passed=False, reference_passed=False),
        )

    with pytest.raises(sqlite3.OperationalError, match="injected verification evidence failure"):
        asyncio.run(persist())
    assert repository.attempts_for_call(call_id) == ()
    assert repository.reconstruct_session(call_id) == VerificationSession()


@pytest.mark.parametrize(
    ("name", "verification_turns", "expected_attempts", "expected_disposition"),
    [
        (
            "verification-correct",
            (("चौदह सितंबर, reference 4729", {"intent": "verification_response"}),),
            (_attempt(1, birth_passed=True, reference_passed=True),),
            None,
        ),
        (
            "verification-wrong-then-right",
            (
                ("चौदह सितंबर, reference 0000", {"intent": "verification_response"}),
                ("चौदह सितंबर, reference 4729", {"intent": "verification_response"}),
            ),
            (
                _attempt(1, birth_passed=True, reference_passed=False),
                _attempt(2, birth_passed=True, reference_passed=True),
            ),
            None,
        ),
        (
            "verification-two-wrong",
            (
                ("एक जनवरी, reference 0000", {"intent": "verification_response"}),
                ("दो फरवरी, reference 1111", {"intent": "verification_response"}),
            ),
            (
                _attempt(1, birth_passed=False, reference_passed=False),
                _attempt(2, birth_passed=False, reference_passed=False),
            ),
            Disposition.VERIFICATION_FAILED,
        ),
    ],
)
def test_controller_persists_exact_attempt_rows_without_values(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    name: str,
    verification_turns: tuple[tuple[str, dict[str, object]], ...],
    expected_attempts: tuple[VerificationAttemptEvidence, ...],
    expected_disposition: Disposition | None,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        name=name,
        turns=(
            ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
            *verification_turns,
        ),
    )

    async def exercise() -> None:
        await controller.start()
        for _ in fake.scenario.turns:
            await controller.run_turn()

    asyncio.run(exercise())

    repository = VerificationEvidenceRepository(controller.ledger)
    assert repository.attempts_for_call(controller.call_id) == expected_attempts
    assert controller.disposition is expected_disposition
    if expected_disposition is None:
        assert controller.snapshot.identity is IdentityState.CONFIRMED

    event_rows = db_connection.execute(
        "SELECT type, redacted_reason FROM events WHERE call_id = ? ORDER BY seq",
        (controller.call_id,),
    ).fetchall()
    decision_rows = db_connection.execute(
        """
        SELECT tool, allowed, identity_state, promise_state, reason
        FROM tool_decisions
        WHERE call_id = ?
        ORDER BY seq
        """,
        (controller.call_id,),
    ).fetchall()
    safe_surfaces = repr(
        {
            "events": [tuple(row) for row in event_rows],
            "tool_decisions": [tuple(row) for row in decision_rows],
            "model_requests": fake.chat_requests,
        }
    )
    for forbidden in ("4729", "0000", "1111", "चौदह", "सितंबर", "एक जनवरी", "दो फरवरी"):
        assert forbidden not in safe_surfaces
    fake.assert_consumed()


def test_controller_evidence_failure_keeps_session_locked_and_retryable(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        name="verification-evidence-retry",
        turns=(
            ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
            ("चौदह सितंबर, reference 0000", {"intent": "verification_response"}),
            ("चौदह सितंबर, reference 0000", {"intent": "verification_response"}),
        ),
    )

    class FailingRepository:
        async def append_attempt(self, **kwargs: object) -> int:
            raise sqlite3.OperationalError("injected verification evidence failure")

    async def exercise() -> None:
        await controller.start()
        await controller.run_turn()
        controller._verification_evidence = FailingRepository()  # type: ignore[assignment]  # noqa: SLF001
        with pytest.raises(
            sqlite3.OperationalError,
            match="injected verification evidence failure",
        ):
            await controller.run_turn()
        assert controller.verification == VerificationSession()
        assert controller.snapshot.identity is IdentityState.VERIFYING
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()

        controller._verification_evidence = VerificationEvidenceRepository(  # noqa: SLF001
            controller.ledger
        )
        await controller.run_turn()

    asyncio.run(exercise())

    repository = VerificationEvidenceRepository(controller.ledger)
    assert repository.attempts_for_call(controller.call_id) == (
        _attempt(1, birth_passed=True, reference_passed=False),
    )
    assert controller.verification == VerificationSession(
        attempts=1,
        status=VerificationStatus.PENDING,
    )
    assert (len(fake.stt_requests), len(fake.chat_requests), len(fake.tts_requests)) == (3, 3, 2)


def test_same_call_restart_reconstructs_only_durable_attempts(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    first, first_fake = _controller(
        db_connection,
        frozen_demo_clock,
        name="verification-restart",
        turns=(
            ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
            ("चौदह सितंबर, reference 0000", {"intent": "verification_response"}),
        ),
    )

    async def first_process() -> None:
        await first.start()
        await first.run_turn()
        await first.run_turn()

    asyncio.run(first_process())
    first_fake.assert_consumed()

    second_fake = FakeSarvamClient(
        SarvamScenario(
            name="verification-restart-second-process",
            turns=(
                ScriptedTurn(
                    transcript="चौदह सितंबर, reference 4729",
                    action={"intent": "verification_response"},
                ),
            ),
        )
    )
    restored = DialogueController(
        call_id=first.call_id,
        case=RAKESH_CASE,
        ledger=EvidenceLedger(db_connection),
        sarvam=second_fake,
        clock=frozen_demo_clock.now,
    )
    assert restored.verification == VerificationSession(
        attempts=1,
        status=VerificationStatus.PENDING,
    )

    async def second_process() -> None:
        await restored.activate_existing_call()
        assert restored.snapshot.identity is IdentityState.VERIFYING
        await restored.run_turn()
        await restored.read_mock_account()

    asyncio.run(second_process())

    assert restored.snapshot.identity is IdentityState.CONFIRMED
    assert VerificationEvidenceRepository(restored.ledger).attempts_for_call(restored.call_id) == (
        _attempt(1, birth_passed=True, reference_passed=False),
        _attempt(2, birth_passed=True, reference_passed=True),
    )
    second_fake.assert_consumed()
