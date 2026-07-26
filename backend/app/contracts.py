"""Importable contracts for Vachan dispositions and append-only evidence.

This module performs no I/O. Persistence and controller code import these
values and validators so the product's evidence claims are executable rules,
not prose duplicated across layers.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from app.states import CallState, IdentityState, PromiseState


class Disposition(StrEnum):
    """The only terminal outcomes for a Vachan call."""

    PROMISE_CONFIRMED = "PROMISE_CONFIRMED"
    CALLBACK_THIRD_PARTY = "CALLBACK_THIRD_PARTY"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ENDED_TECHNICAL = "ENDED_TECHNICAL"
    ENDED_OPERATOR = "ENDED_OPERATOR"


BUSINESS_DISPOSITIONS = frozenset(
    {
        Disposition.PROMISE_CONFIRMED,
        Disposition.CALLBACK_THIRD_PARTY,
    }
)
NON_BUSINESS_DISPOSITIONS = frozenset(Disposition) - BUSINESS_DISPOSITIONS


class LedgerEventType(StrEnum):
    """Append-only event categories needed to prove authorization decisions."""

    STATE_TRANSITION = "STATE_TRANSITION"
    STATE_TRANSITION_REJECTED = "STATE_TRANSITION_REJECTED"
    TOOL_DECISION = "TOOL_DECISION"
    OUTPUT_BLOCKED = "OUTPUT_BLOCKED"
    SAFE_UTTERANCE = "SAFE_UTTERANCE"
    PROMISE_CANDIDATE_CREATED = "PROMISE_CANDIDATE_CREATED"
    PROMISE_CANDIDATE_CORRECTED = "PROMISE_CANDIDATE_CORRECTED"
    PROMISE_READ_BACK = "PROMISE_READ_BACK"
    PROMISE_EXPLICITLY_CONFIRMED = "PROMISE_EXPLICITLY_CONFIRMED"
    PROMISE_COMMITTED = "PROMISE_COMMITTED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    OPERATOR_TAKEOVER = "OPERATOR_TAKEOVER"
    DISPOSITION_SET = "DISPOSITION_SET"
    TURN_TIMING = "TURN_TIMING"


class EvidenceInvariant(StrEnum):
    """Stable identifiers imported by schema, controller, and runner tests."""

    EXACTLY_ONE_DISPOSITION = "exactly_one_disposition_per_call"
    COMMIT_REQUIRES_READ_BACK_AND_CONFIRM = "promise_commit_requires_prior_read_back_and_confirm"
    NO_DISCLOSURE_BEFORE_CONFIRMATION = "no_disclosure_while_identity_is_not_confirmed"


EVIDENCE_INVARIANTS = MappingProxyType(
    {
        EvidenceInvariant.EXACTLY_ONE_DISPOSITION: (
            "A completed call has exactly one terminal disposition event."
        ),
        EvidenceInvariant.COMMIT_REQUIRES_READ_BACK_AND_CONFIRM: (
            "A promise commit is preceded by read-back and explicit-confirmation events."
        ),
        EvidenceInvariant.NO_DISCLOSURE_BEFORE_CONFIRMATION: (
            "Evidence marked as containing private account data is recorded only while identity "
            "is CONFIRMED."
        ),
    }
)

APPEND_ONLY_TABLES = frozenset({"events", "safe_utterances", "promises", "operator_notes"})


class EvidenceContractViolation(ValueError):
    """Typed failure identifying which evidence invariant was violated."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """All authorization-relevant state at one side of an evidence event."""

    call: CallState
    identity: IdentityState
    promise: PromiseState


@dataclass(frozen=True, slots=True)
class EvidenceEvent:
    """One immutable, append-ready ledger event.

    Sequence allocation and insertion are owned by the database layer. The
    constructor rejects values that could never form a valid ledger row.
    """

    call_id: str
    seq: int
    ts: datetime
    event_type: LedgerEventType
    state_before: StateSnapshot
    state_after: StateSnapshot
    redacted_reason: str
    contains_private_data: bool = False
    disposition: Disposition | None = None

    def __post_init__(self) -> None:
        if not self.call_id.strip():
            raise EvidenceContractViolation("invalid_call_id", "call_id must not be empty")
        if self.seq < 1:
            raise EvidenceContractViolation("invalid_sequence", "seq must be positive")
        if self.ts.tzinfo is None or self.ts.utcoffset() is None:
            raise EvidenceContractViolation("invalid_timestamp", "ts must be timezone-aware")
        if not self.redacted_reason.strip():
            raise EvidenceContractViolation(
                "invalid_redacted_reason",
                "redacted_reason must not be empty",
            )

        is_disposition_event = self.event_type is LedgerEventType.DISPOSITION_SET
        if is_disposition_event != (self.disposition is not None):
            raise EvidenceContractViolation(
                "invalid_disposition_event",
                "only DISPOSITION_SET carries a disposition, and it must carry one",
            )


@dataclass(frozen=True, slots=True)
class OperatorNote:
    """An attributed note value that may only be appended by persistence code."""

    call_id: str
    ts: datetime
    author: str
    note: str

    def __post_init__(self) -> None:
        empty_fields = [
            name
            for name, value in (
                ("call_id", self.call_id),
                ("author", self.author),
                ("note", self.note),
            )
            if not value.strip()
        ]
        if empty_fields:
            raise EvidenceContractViolation(
                "invalid_operator_note",
                f"empty fields: {', '.join(empty_fields)}",
            )
        if self.ts.tzinfo is None or self.ts.utcoffset() is None:
            raise EvidenceContractViolation(
                "invalid_operator_note_timestamp",
                "operator note timestamp must be timezone-aware",
            )


def _raise_invariant(invariant: EvidenceInvariant, detail: str) -> None:
    raise EvidenceContractViolation(invariant.value, detail)


def validate_completed_evidence(events: Sequence[EvidenceEvent]) -> Disposition:
    """Validate a completed call's ordered evidence and return its disposition.

    This is deliberately a final-stream validator. Active calls may have no
    disposition yet; completed calls passed here must prove exactly one.
    """

    if not events:
        _raise_invariant(
            EvidenceInvariant.EXACTLY_ONE_DISPOSITION,
            "completed evidence stream is empty",
        )

    call_id = events[0].call_id
    if any(event.call_id != call_id for event in events):
        raise EvidenceContractViolation(
            "mixed_call_stream",
            "all evidence events must belong to one call",
        )

    sequences = [event.seq for event in events]
    if any(
        current >= following for current, following in zip(sequences, sequences[1:], strict=False)
    ):
        raise EvidenceContractViolation(
            "non_monotonic_sequence",
            "event sequence numbers must be strictly increasing",
        )

    timestamps = [event.ts for event in events]
    if any(
        current > following for current, following in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise EvidenceContractViolation(
            "non_monotonic_timestamp",
            "event timestamps must not move backwards",
        )

    disposition_events = [
        event for event in events if event.event_type is LedgerEventType.DISPOSITION_SET
    ]
    if len(disposition_events) != 1:
        _raise_invariant(
            EvidenceInvariant.EXACTLY_ONE_DISPOSITION,
            f"found {len(disposition_events)} disposition events",
        )
    if disposition_events[0] is not events[-1]:
        _raise_invariant(
            EvidenceInvariant.EXACTLY_ONE_DISPOSITION,
            "the terminal disposition must be the final system event",
        )

    private_events = [event for event in events if event.contains_private_data]
    for event in private_events:
        if (
            event.state_before.identity is not IdentityState.CONFIRMED
            or event.state_after.identity is not IdentityState.CONFIRMED
        ):
            _raise_invariant(
                EvidenceInvariant.NO_DISCLOSURE_BEFORE_CONFIRMATION,
                f"private event at seq {event.seq} was outside CONFIRMED identity",
            )

    commit_events = [
        event for event in events if event.event_type is LedgerEventType.PROMISE_COMMITTED
    ]
    for commit in commit_events:
        prior_types = {event.event_type for event in events if event.seq < commit.seq}
        required = {
            LedgerEventType.PROMISE_READ_BACK,
            LedgerEventType.PROMISE_EXPLICITLY_CONFIRMED,
        }
        if not required.issubset(prior_types):
            _raise_invariant(
                EvidenceInvariant.COMMIT_REQUIRES_READ_BACK_AND_CONFIRM,
                f"promise commit at seq {commit.seq} lacks prerequisite events",
            )

    disposition = disposition_events[0].disposition
    assert disposition is not None

    if disposition is Disposition.PROMISE_CONFIRMED and len(commit_events) != 1:
        _raise_invariant(
            EvidenceInvariant.COMMIT_REQUIRES_READ_BACK_AND_CONFIRM,
            "PROMISE_CONFIRMED requires exactly one promise commit event",
        )
    if disposition is not Disposition.PROMISE_CONFIRMED and commit_events:
        raise EvidenceContractViolation(
            "commit_disposition_mismatch",
            "a committed promise must end as PROMISE_CONFIRMED",
        )

    if (
        any(event.event_type is LedgerEventType.TECHNICAL_FAILURE for event in events)
        and disposition in BUSINESS_DISPOSITIONS
    ):
        raise EvidenceContractViolation(
            "technical_failure_became_business_outcome",
            "technical failure may end only in a non-business disposition",
        )

    return disposition
