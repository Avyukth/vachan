"""State contracts for Vachan's three orthogonal state machines.

The language model may propose an action, but only these code-owned transition
tables determine whether the resulting state change is legal.
"""

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class StateMachine(StrEnum):
    """Names of the independently evolving state machines."""

    CALL = "call"
    IDENTITY = "identity"
    PROMISE = "promise"


class CallState(StrEnum):
    """Lifecycle of one operator-supervised call."""

    IDLE = "IDLE"
    PREFLIGHT = "PREFLIGHT"
    READY = "READY"
    CONNECTING = "CONNECTING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"
    OPERATOR_TAKEOVER = "OPERATOR_TAKEOVER"
    ENDED = "ENDED"


class IdentityState(StrEnum):
    """Authorization fact for the person currently speaking."""

    UNVERIFIED = "UNVERIFIED"
    VERIFYING = "VERIFYING"
    CONFIRMED = "CONFIRMED"
    THIRD_PARTY = "THIRD_PARTY"


class PromiseState(StrEnum):
    """Progress of an echo-confirmed promise-to-pay."""

    NONE = "NONE"
    CANDIDATE = "CANDIDATE"
    READ_BACK = "READ_BACK"
    CONFIRMED = "CONFIRMED"
    COMMITTED = "COMMITTED"
    CORRECTED = "CORRECTED"
    ABANDONED = "ABANDONED"


State = CallState | IdentityState | PromiseState
Transition = tuple[State, State]

CALL_TRANSITIONS: frozenset[Transition] = frozenset(
    {
        (CallState.IDLE, CallState.PREFLIGHT),
        (CallState.PREFLIGHT, CallState.READY),
        (CallState.PREFLIGHT, CallState.BLOCKED),
        (CallState.READY, CallState.CONNECTING),
        (CallState.CONNECTING, CallState.ACTIVE),
        (CallState.CONNECTING, CallState.DEGRADED),
        (CallState.ACTIVE, CallState.COMPLETED),
        (CallState.ACTIVE, CallState.DEGRADED),
        (CallState.ACTIVE, CallState.OPERATOR_TAKEOVER),
        (CallState.DEGRADED, CallState.OPERATOR_TAKEOVER),
        (CallState.ACTIVE, CallState.ENDED),
        (CallState.DEGRADED, CallState.ENDED),
        (CallState.OPERATOR_TAKEOVER, CallState.ENDED),
    }
)

IDENTITY_TRANSITIONS: frozenset[Transition] = frozenset(
    {
        (IdentityState.UNVERIFIED, IdentityState.VERIFYING),
        (IdentityState.VERIFYING, IdentityState.CONFIRMED),
        (IdentityState.UNVERIFIED, IdentityState.THIRD_PARTY),
        (IdentityState.VERIFYING, IdentityState.THIRD_PARTY),
        (IdentityState.CONFIRMED, IdentityState.UNVERIFIED),
        (IdentityState.CONFIRMED, IdentityState.THIRD_PARTY),
        # A borrower reclaiming a phone from a third party must verify afresh.
        (IdentityState.THIRD_PARTY, IdentityState.VERIFYING),
    }
)

PROMISE_TRANSITIONS: frozenset[Transition] = frozenset(
    {
        (PromiseState.NONE, PromiseState.CANDIDATE),
        (PromiseState.CANDIDATE, PromiseState.READ_BACK),
        (PromiseState.READ_BACK, PromiseState.CONFIRMED),
        (PromiseState.CONFIRMED, PromiseState.COMMITTED),
        (PromiseState.CONFIRMED, PromiseState.ABANDONED),
        (PromiseState.CANDIDATE, PromiseState.CORRECTED),
        (PromiseState.READ_BACK, PromiseState.CORRECTED),
        (PromiseState.CORRECTED, PromiseState.READ_BACK),
        (PromiseState.CANDIDATE, PromiseState.ABANDONED),
        (PromiseState.READ_BACK, PromiseState.ABANDONED),
        (PromiseState.CORRECTED, PromiseState.ABANDONED),
    }
)

TRANSITION_TABLES = MappingProxyType(
    {
        StateMachine.CALL: CALL_TRANSITIONS,
        StateMachine.IDENTITY: IDENTITY_TRANSITIONS,
        StateMachine.PROMISE: PROMISE_TRANSITIONS,
    }
)

INITIAL_STATES = MappingProxyType(
    {
        StateMachine.CALL: CallState.IDLE,
        StateMachine.IDENTITY: IdentityState.UNVERIFIED,
        StateMachine.PROMISE: PromiseState.NONE,
    }
)

_STATE_MACHINE_BY_TYPE = MappingProxyType(
    {
        CallState: StateMachine.CALL,
        IdentityState: StateMachine.IDENTITY,
        PromiseState: StateMachine.PROMISE,
    }
)


@dataclass(frozen=True, slots=True)
class TransitionEvent:
    """Append-ready evidence describing one transition decision."""

    event_type: str
    machine: StateMachine
    state_before: State
    state_after: State
    accepted: bool
    reason: str

    def as_ledger_payload(self) -> dict[str, str | bool]:
        """Return a serialization-safe payload without timestamps or sequence IDs."""
        return {
            "event_type": self.event_type,
            "machine": self.machine.value,
            "state_before": self.state_before.value,
            "state_after": self.state_after.value,
            "accepted": self.accepted,
            "reason": self.reason,
        }


class InvalidStateTransition(ValueError):
    """Typed failure carrying the evidence that callers must persist."""

    def __init__(self, event: TransitionEvent) -> None:
        self.event = event
        super().__init__(
            f"Illegal {event.machine.value} transition: "
            f"{event.state_before.value} -> {event.state_after.value}"
        )


def machine_for_state(state: State) -> StateMachine:
    """Return the machine that owns a state enum member."""
    try:
        return _STATE_MACHINE_BY_TYPE[type(state)]
    except KeyError as error:
        raise TypeError(f"Unsupported state type: {type(state).__name__}") from error


def is_valid_transition(state_before: State, state_after: State) -> bool:
    """Return whether an edge is legal without performing any side effect."""
    if type(state_before) is not type(state_after):
        return False
    machine = machine_for_state(state_before)
    return (state_before, state_after) in TRANSITION_TABLES[machine]


def validate_transition(state_before: State, state_after: State) -> TransitionEvent:
    """Validate an edge and produce evidence, or raise evidence-bearing failure."""
    machine = machine_for_state(state_before)
    accepted = is_valid_transition(state_before, state_after)
    event = TransitionEvent(
        event_type="STATE_TRANSITION" if accepted else "STATE_TRANSITION_REJECTED",
        machine=machine,
        state_before=state_before,
        state_after=state_after,
        accepted=accepted,
        reason="allowed_by_transition_table" if accepted else "transition_not_allowed",
    )
    if not accepted:
        raise InvalidStateTransition(event)
    return event


def initial_state(machine: StateMachine) -> State:
    """Return the unconditional initial state for a fresh call context."""
    return INITIAL_STATES[machine]


def transition_tables_for_json() -> dict[str, list[dict[str, str]]]:
    """Render immutable tables for protocol/docs consumers without exposing mutable state."""
    return {
        machine.value: [
            {"from": state_before.value, "to": state_after.value}
            for state_before, state_after in sorted(
                transitions,
                key=lambda edge: (edge[0].value, edge[1].value),
            )
        ]
        for machine, transitions in TRANSITION_TABLES.items()
    }
