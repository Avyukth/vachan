"""Persist-before-mutate execution boundary for state-gated controller tools."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from app.contracts import StateSnapshot
from app.tools import (
    PermissionContext,
    ToolDecision,
    ToolName,
    ToolPermissionDenied,
    evaluate_tool_permission,
)

T = TypeVar("T")


class AuthorizationState(Protocol):
    """Authoritative state source implemented by StateMachineCoordinator."""

    call_id: str

    @property
    def snapshot(self) -> StateSnapshot: ...


class ToolDecisionWriter(Protocol):
    """Atomic decision/event persistence implemented by EvidenceLedger."""

    async def append_tool_decision(
        self,
        *,
        call_id: str,
        ts: datetime,
        decision: ToolDecision,
        state: StateSnapshot,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class ToolFacts:
    """Redacted non-state facts used by declarative permission conditions."""

    verification_attempts: int = 0
    max_verification_attempts: int = 2
    amount_minor: int | None = None
    date_is_allowed: bool = False
    candidate_exists: bool = False
    candidate_committed: bool = False
    candidate_read_back: bool = False
    explicit_affirmative: bool = False
    callback_payload_is_content_free: bool = False
    end_reason_is_valid: bool = False


EMPTY_TOOL_FACTS = ToolFacts()


class AsyncToolMutationRejected(TypeError):
    """Tool effects must not outlive the authorization snapshot in this boundary."""


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def _permission_context(snapshot: StateSnapshot, facts: ToolFacts) -> PermissionContext:
    return PermissionContext(
        call_state=snapshot.call,
        identity_state=snapshot.identity,
        promise_state=snapshot.promise,
        verification_attempts=facts.verification_attempts,
        max_verification_attempts=facts.max_verification_attempts,
        amount_minor=facts.amount_minor,
        date_is_allowed=facts.date_is_allowed,
        candidate_exists=facts.candidate_exists,
        candidate_committed=facts.candidate_committed,
        candidate_read_back=facts.candidate_read_back,
        explicit_affirmative=facts.explicit_affirmative,
        callback_payload_is_content_free=facts.callback_payload_is_content_free,
        end_reason_is_valid=facts.end_reason_is_valid,
    )


class GatedToolExecutor:
    """Authorize from code-owned state, persist, recheck, then mutate synchronously."""

    def __init__(
        self,
        *,
        call_id: str,
        authorization_state: AuthorizationState,
        decision_writer: ToolDecisionWriter,
        clock: Clock = utc_now,
    ) -> None:
        if not call_id.strip():
            raise ValueError("call_id must not be empty")
        if authorization_state.call_id != call_id:
            raise ValueError("authorization state must belong to the same call")
        self.call_id = call_id
        self._authorization_state = authorization_state
        self._decision_writer = decision_writer
        self._clock = clock

    async def execute(
        self,
        tool: ToolName,
        *,
        facts: ToolFacts = EMPTY_TOOL_FACTS,
        operation: Callable[[], T],
    ) -> T:
        """Execute one synchronous effect only after an auditable allowed decision.

        State is re-read after the persistence await. If handover demoted identity
        during that await, a second denied decision is recorded and the operation
        is never invoked. Restricting effects to synchronous functions prevents a
        permitted coroutine from mutating later under a stale authorization fact.
        """
        if inspect.iscoroutinefunction(operation):
            raise AsyncToolMutationRejected(
                "gated tool operation must be synchronous; split async preparation from mutation"
            )

        authorized_snapshot = self._authorization_state.snapshot
        decision = evaluate_tool_permission(
            tool,
            _permission_context(authorized_snapshot, facts),
        )
        await self._decision_writer.append_tool_decision(
            call_id=self.call_id,
            ts=self._clock(),
            decision=decision,
            state=authorized_snapshot,
        )
        if not decision.allowed:
            raise ToolPermissionDenied(decision)

        current_snapshot = self._authorization_state.snapshot
        if current_snapshot != authorized_snapshot:
            decision = evaluate_tool_permission(
                tool,
                _permission_context(current_snapshot, facts),
            )
            await self._decision_writer.append_tool_decision(
                call_id=self.call_id,
                ts=self._clock(),
                decision=decision,
                state=current_snapshot,
            )
            if not decision.allowed:
                raise ToolPermissionDenied(decision)

        result = operation()
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise AsyncToolMutationRejected("gated tool operation returned an awaitable")
        return result


def facts_with(facts: ToolFacts = EMPTY_TOOL_FACTS, **changes: object) -> ToolFacts:
    """Build condition facts without exposing any state-spoofing fields."""
    return replace(facts, **changes)
