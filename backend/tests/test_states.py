"""Contract tests for Vachan's orthogonal state machines."""

import pytest

from app.states import (
    CALL_TRANSITIONS,
    IDENTITY_TRANSITIONS,
    PROMISE_TRANSITIONS,
    CallState,
    IdentityState,
    InvalidStateTransition,
    PromiseState,
    StateMachine,
    initial_state,
    is_valid_transition,
    transition_tables_for_json,
    validate_transition,
)


@pytest.mark.parametrize(
    ("transitions", "expected_count"),
    [
        (CALL_TRANSITIONS, 13),
        (IDENTITY_TRANSITIONS, 7),
        (PROMISE_TRANSITIONS, 10),
    ],
)
def test_every_declared_edge_is_accepted(
    transitions: frozenset[tuple[object, object]],
    expected_count: int,
) -> None:
    """Every contract edge validates and creates exactly one accepted event."""
    assert len(transitions) == expected_count
    for state_before, state_after in transitions:
        assert is_valid_transition(state_before, state_after)
        event = validate_transition(state_before, state_after)
        assert event.accepted is True
        assert event.event_type == "STATE_TRANSITION"
        assert event.state_before is state_before
        assert event.state_after is state_after


@pytest.mark.parametrize(
    ("state_before", "state_after"),
    [
        (CallState.IDLE, CallState.ACTIVE),
        (CallState.READY, CallState.COMPLETED),
        (IdentityState.UNVERIFIED, IdentityState.CONFIRMED),
        (PromiseState.NONE, PromiseState.COMMITTED),
        (PromiseState.COMMITTED, PromiseState.CANDIDATE),
    ],
)
def test_illegal_edges_raise_typed_errors_with_append_ready_evidence(
    state_before: CallState | IdentityState | PromiseState,
    state_after: CallState | IdentityState | PromiseState,
) -> None:
    """Rejected edges carry redacted evidence for the append-only ledger."""
    with pytest.raises(InvalidStateTransition) as captured:
        validate_transition(state_before, state_after)

    event = captured.value.event
    assert event.accepted is False
    assert event.event_type == "STATE_TRANSITION_REJECTED"
    assert event.as_ledger_payload() == {
        "event_type": "STATE_TRANSITION_REJECTED",
        "machine": {
            CallState: "call",
            IdentityState: "identity",
            PromiseState: "promise",
        }[type(state_before)],
        "state_before": state_before.value,
        "state_after": state_after.value,
        "accepted": False,
        "reason": "transition_not_allowed",
    }


def test_states_from_different_machines_never_form_a_valid_edge() -> None:
    """Same-named states in separate machines cannot authorize each other."""
    assert not is_valid_transition(IdentityState.CONFIRMED, PromiseState.CONFIRMED)
    with pytest.raises(InvalidStateTransition):
        validate_transition(IdentityState.CONFIRMED, PromiseState.CONFIRMED)


def test_identity_always_starts_unverified_for_a_fresh_call() -> None:
    """No previous call can restore identity authorization."""
    assert initial_state(StateMachine.CALL) is CallState.IDLE
    assert initial_state(StateMachine.IDENTITY) is IdentityState.UNVERIFIED
    assert initial_state(StateMachine.PROMISE) is PromiseState.NONE


def test_borrower_can_reclaim_phone_only_via_fresh_verification() -> None:
    """The amended third-party path has no direct authorization shortcut."""
    assert is_valid_transition(IdentityState.THIRD_PARTY, IdentityState.VERIFYING)
    assert not is_valid_transition(IdentityState.THIRD_PARTY, IdentityState.CONFIRMED)


def test_transition_tables_have_stable_json_shape() -> None:
    """Frontend and evidence consumers receive values, never enum internals."""
    rendered = transition_tables_for_json()
    assert set(rendered) == {"call", "identity", "promise"}
    assert {"from": "CONFIRMED", "to": "UNVERIFIED"} in rendered["identity"]
