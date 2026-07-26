"""Pure transitions plus serialized, evidence-backed state-machine execution."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from app.contracts import LedgerEventType, StateSnapshot
from app.states import (
    CallState,
    IdentityState,
    InvalidStateTransition,
    PromiseState,
    State,
    StateMachine,
    TransitionEvent,
    machine_for_state,
    validate_transition,
)

_REDACTED_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_:-]{0,99}$")


class EventWriter(Protocol):
    """Narrow persistence contract implemented by ``EvidenceLedger``."""

    async def append_event(
        self,
        *,
        call_id: str,
        ts: datetime,
        event_type: LedgerEventType | str,
        state_before: StateSnapshot,
        state_after: StateSnapshot,
        redacted_reason: str,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class TransitionPlan:
    """Pure result of applying one legal table edge to a full snapshot."""

    state_before: StateSnapshot
    state_after: StateSnapshot
    event: TransitionEvent


@dataclass(frozen=True, slots=True)
class AppliedTransition:
    """Persisted transition delivered synchronously to runtime observers."""

    call_id: str
    seq: int
    ts: datetime
    plan: TransitionPlan


TransitionObserver = Callable[[AppliedTransition], None]
AuthorizationRevoked = Callable[[StateSnapshot], None]
Clock = Callable[[], datetime]


class AuthorizationRelockError(RuntimeError):
    """A relock observer failed after the authoritative state was demoted."""


class TransitionObserverError(RuntimeError):
    """A UI/guard observer failed after the transition was safely persisted."""


def utc_now() -> datetime:
    """Return an aware UTC timestamp for evidence rows."""
    return datetime.now(UTC)


def fresh_call_snapshot() -> StateSnapshot:
    """Return unconditional per-call state; identity is never restored across calls."""
    return StateSnapshot(
        call=CallState.IDLE,
        identity=IdentityState.UNVERIFIED,
        promise=PromiseState.NONE,
    )


def _state_for_machine(snapshot: StateSnapshot, machine: StateMachine) -> State:
    if machine is StateMachine.CALL:
        return snapshot.call
    if machine is StateMachine.IDENTITY:
        return snapshot.identity
    return snapshot.promise


def _replace_machine_state(
    snapshot: StateSnapshot,
    machine: StateMachine,
    target: State,
) -> StateSnapshot:
    if machine is StateMachine.CALL:
        assert isinstance(target, CallState)
        return replace(snapshot, call=target)
    if machine is StateMachine.IDENTITY:
        assert isinstance(target, IdentityState)
        return replace(snapshot, identity=target)
    assert isinstance(target, PromiseState)
    return replace(snapshot, promise=target)


def plan_transition(snapshot: StateSnapshot, target: State) -> TransitionPlan:
    """Purely apply a target state through its machine's frozen transition table."""
    machine = machine_for_state(target)
    current = _state_for_machine(snapshot, machine)
    event = validate_transition(current, target)
    return TransitionPlan(
        state_before=snapshot,
        state_after=_replace_machine_state(snapshot, machine, target),
        event=event,
    )


def _validate_reason_code(reason_code: str) -> str:
    """Accept stable redacted codes, never raw utterances or exception text."""
    if not _REDACTED_REASON_PATTERN.fullmatch(reason_code):
        raise ValueError("reason_code must be a lowercase redacted token of at most 100 characters")
    return reason_code


def _is_authorization_demotion(plan: TransitionPlan) -> bool:
    return (
        plan.state_before.identity is IdentityState.CONFIRMED
        and plan.state_after.identity is not IdentityState.CONFIRMED
    )


class StateMachineCoordinator:
    """Serialize state changes, evidence writes, and authorization notifications.

    Identity demotion is deliberately special: the in-memory authorization fact
    changes and the relock callback runs before the first await. Even if evidence
    persistence then fails, tools stay fail-closed. Authorization-increasing
    transitions take the opposite order and persist before opening the state.
    """

    def __init__(
        self,
        *,
        call_id: str,
        event_writer: EventWriter,
        clock: Clock = utc_now,
        on_transition: TransitionObserver | None = None,
        on_authorization_revoked: AuthorizationRevoked | None = None,
    ) -> None:
        if not call_id.strip():
            raise ValueError("call_id must not be empty")
        self.call_id = call_id
        self._event_writer = event_writer
        self._clock = clock
        self._on_transition = on_transition
        self._on_authorization_revoked = on_authorization_revoked
        self._snapshot = fresh_call_snapshot()
        self._lock = asyncio.Lock()

    @property
    def snapshot(self) -> StateSnapshot:
        """Return the current immutable authorization-relevant state."""
        return self._snapshot

    def adopt_persisted_snapshot(self, target: StateSnapshot) -> None:
        """Adopt state whose complete transition evidence is already atomic.

        This synchronous hook is intentionally narrow: the promise outcome
        boundary persists both legal state edges and the terminal disposition
        in one SQLite transaction before publishing the resulting runtime
        snapshot.
        """

        before = self._snapshot
        if target.identity is not before.identity:
            raise ValueError("atomic promise outcome cannot change identity")
        validate_transition(before.promise, target.promise)
        validate_transition(before.call, target.call)
        self._snapshot = target

    async def transition(
        self,
        target: State,
        *,
        reason_code: str = "application_transition",
    ) -> AppliedTransition:
        """Apply one state edge and append exactly one accepted/rejected event."""
        reason = _validate_reason_code(reason_code)
        async with self._lock:
            before = self._snapshot
            try:
                plan = plan_transition(before, target)
            except InvalidStateTransition as error:
                rejected_reason = (
                    f"transition_not_allowed:{error.event.machine.value}:"
                    f"{error.event.state_before.value.lower()}:"
                    f"{error.event.state_after.value.lower()}"
                )
                await self._event_writer.append_event(
                    call_id=self.call_id,
                    ts=self._clock(),
                    event_type=LedgerEventType.STATE_TRANSITION_REJECTED,
                    state_before=before,
                    state_after=before,
                    redacted_reason=rejected_reason,
                )
                raise

            timestamp = self._clock()
            demoting = _is_authorization_demotion(plan)
            relock_error: Exception | None = None

            if demoting:
                # This assignment is the structural tool relock: every tool gate
                # reads the coordinator snapshot. No await may precede it.
                self._snapshot = plan.state_after
                if self._on_authorization_revoked is not None:
                    try:
                        self._on_authorization_revoked(self._snapshot)
                    except Exception as error:  # trusted callback failure becomes technical ending
                        relock_error = error

            seq = await self._event_writer.append_event(
                call_id=self.call_id,
                ts=timestamp,
                event_type=LedgerEventType.STATE_TRANSITION,
                state_before=plan.state_before,
                state_after=plan.state_after,
                redacted_reason="authorization_relock_failed" if relock_error else reason,
            )

            if not demoting:
                # Authorization can increase only after the evidence row exists.
                self._snapshot = plan.state_after

            applied = AppliedTransition(
                call_id=self.call_id,
                seq=seq,
                ts=timestamp,
                plan=plan,
            )
            if self._on_transition is not None:
                try:
                    self._on_transition(applied)
                except Exception as error:
                    raise TransitionObserverError(
                        "transition observer failed after persistence"
                    ) from error

            if relock_error is not None:
                raise AuthorizationRelockError(
                    "authorization relock callback failed; state remains demoted"
                ) from relock_error
            return applied
