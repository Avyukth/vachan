"""Disposition and evidence-contract tests."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import (
    APPEND_ONLY_TABLES,
    BUSINESS_DISPOSITIONS,
    EVIDENCE_INVARIANTS,
    NON_BUSINESS_DISPOSITIONS,
    Disposition,
    EvidenceContractViolation,
    EvidenceEvent,
    EvidenceInvariant,
    LedgerEventType,
    OperatorNote,
    StateSnapshot,
    validate_completed_evidence,
)
from app.states import CallState, IdentityState, PromiseState

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def snapshot(
    *,
    call: CallState = CallState.ACTIVE,
    identity: IdentityState = IdentityState.CONFIRMED,
    promise: PromiseState = PromiseState.NONE,
) -> StateSnapshot:
    return StateSnapshot(call=call, identity=identity, promise=promise)


def event(
    seq: int,
    event_type: LedgerEventType,
    *,
    before: StateSnapshot | None = None,
    after: StateSnapshot | None = None,
    private: bool = False,
    disposition: Disposition | None = None,
) -> EvidenceEvent:
    return EvidenceEvent(
        call_id="call-001",
        seq=seq,
        ts=NOW + timedelta(seconds=seq),
        event_type=event_type,
        state_before=before or snapshot(),
        state_after=after or snapshot(),
        redacted_reason="contract_test",
        contains_private_data=private,
        disposition=disposition,
    )


def valid_promise_stream() -> tuple[EvidenceEvent, ...]:
    return (
        event(
            1,
            LedgerEventType.PROMISE_CANDIDATE_CREATED,
            after=snapshot(promise=PromiseState.CANDIDATE),
            private=True,
        ),
        event(
            2,
            LedgerEventType.PROMISE_READ_BACK,
            before=snapshot(promise=PromiseState.CANDIDATE),
            after=snapshot(promise=PromiseState.READ_BACK),
            private=True,
        ),
        event(
            3,
            LedgerEventType.PROMISE_EXPLICITLY_CONFIRMED,
            before=snapshot(promise=PromiseState.READ_BACK),
            after=snapshot(promise=PromiseState.CONFIRMED),
            private=True,
        ),
        event(
            4,
            LedgerEventType.PROMISE_COMMITTED,
            before=snapshot(promise=PromiseState.CONFIRMED),
            after=snapshot(promise=PromiseState.COMMITTED),
            private=True,
        ),
        event(
            5,
            LedgerEventType.DISPOSITION_SET,
            before=snapshot(promise=PromiseState.COMMITTED),
            after=snapshot(call=CallState.COMPLETED, promise=PromiseState.COMMITTED),
            disposition=Disposition.PROMISE_CONFIRMED,
        ),
    )


def test_contract_exports_exactly_five_exclusive_dispositions() -> None:
    assert {item.value for item in Disposition} == {
        "PROMISE_CONFIRMED",
        "CALLBACK_THIRD_PARTY",
        "VERIFICATION_FAILED",
        "ENDED_TECHNICAL",
        "ENDED_OPERATOR",
    }
    assert BUSINESS_DISPOSITIONS.isdisjoint(NON_BUSINESS_DISPOSITIONS)
    assert frozenset(Disposition) == BUSINESS_DISPOSITIONS | NON_BUSINESS_DISPOSITIONS


def test_invariant_list_is_importable_and_append_only_tables_are_explicit() -> None:
    assert set(EVIDENCE_INVARIANTS) == set(EvidenceInvariant)
    assert {"events", "safe_utterances", "promises", "operator_notes"} == APPEND_ONLY_TABLES


def test_valid_echo_confirmed_promise_proves_one_terminal_outcome() -> None:
    assert validate_completed_evidence(valid_promise_stream()) is Disposition.PROMISE_CONFIRMED


@pytest.mark.parametrize("count", [0, 2])
def test_completed_call_must_have_exactly_one_disposition(count: int) -> None:
    stream = list(valid_promise_stream())
    if count == 0:
        stream.pop()
    else:
        stream.append(
            event(
                6,
                LedgerEventType.DISPOSITION_SET,
                disposition=Disposition.PROMISE_CONFIRMED,
            )
        )

    with pytest.raises(EvidenceContractViolation) as captured:
        validate_completed_evidence(stream)

    assert captured.value.code is EvidenceInvariant.EXACTLY_ONE_DISPOSITION.value


@pytest.mark.parametrize(
    "missing_type",
    [
        LedgerEventType.PROMISE_READ_BACK,
        LedgerEventType.PROMISE_EXPLICITLY_CONFIRMED,
    ],
)
def test_promise_commit_requires_prior_read_back_and_explicit_confirm(
    missing_type: LedgerEventType,
) -> None:
    stream = tuple(
        replace(item, seq=index, ts=NOW + timedelta(seconds=index))
        for index, item in enumerate(
            (item for item in valid_promise_stream() if item.event_type is not missing_type),
            start=1,
        )
    )

    with pytest.raises(EvidenceContractViolation) as captured:
        validate_completed_evidence(stream)

    assert captured.value.code == EvidenceInvariant.COMMIT_REQUIRES_READ_BACK_AND_CONFIRM.value


def test_private_data_event_is_rejected_outside_confirmed_identity() -> None:
    unverified = snapshot(identity=IdentityState.UNVERIFIED)
    stream = (
        event(
            1,
            LedgerEventType.TOOL_DECISION,
            before=unverified,
            after=unverified,
            private=True,
        ),
        event(
            2,
            LedgerEventType.DISPOSITION_SET,
            before=unverified,
            after=replace(unverified, call=CallState.ENDED),
            disposition=Disposition.VERIFICATION_FAILED,
        ),
    )

    with pytest.raises(EvidenceContractViolation) as captured:
        validate_completed_evidence(stream)

    assert captured.value.code is EvidenceInvariant.NO_DISCLOSURE_BEFORE_CONFIRMATION.value


def test_technical_failure_cannot_become_a_business_outcome() -> None:
    stream = list(valid_promise_stream())
    stream.insert(0, event(1, LedgerEventType.TECHNICAL_FAILURE))
    stream = [
        replace(item, seq=index, ts=NOW + timedelta(seconds=index))
        for index, item in enumerate(stream, start=1)
    ]

    with pytest.raises(EvidenceContractViolation) as captured:
        validate_completed_evidence(stream)

    assert captured.value.code == "technical_failure_became_business_outcome"


def test_sequence_and_timestamp_are_monotonic_within_one_call() -> None:
    stream = (
        event(2, LedgerEventType.TOOL_DECISION),
        event(
            1,
            LedgerEventType.DISPOSITION_SET,
            disposition=Disposition.ENDED_OPERATOR,
        ),
    )

    with pytest.raises(EvidenceContractViolation) as captured:
        validate_completed_evidence(stream)

    assert captured.value.code == "non_monotonic_sequence"


def test_operator_notes_are_immutable_attributed_append_values() -> None:
    note = OperatorNote(
        call_id="call-001",
        ts=NOW,
        author="Priya",
        note="Operator ended the mock call after takeover.",
    )
    assert note.author == "Priya"

    with pytest.raises(FrozenInstanceError):
        note.note = "edited"  # type: ignore[misc]
