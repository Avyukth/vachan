"""Strict break-glass takeover ordering and permanent agent silencing."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from fastapi import APIRouter, HTTPException, Request, status

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.protocol import EndCallRequest, EventType, ServerEvent, TakeoverRequest
from app.state_machine import StateMachineCoordinator, utc_now
from app.states import CallState

TAKEOVER_BANNER = "OPERATOR TAKEOVER — AGENT SILENCED"
MAX_OPERATOR_REASON_LENGTH = 500

router = APIRouter(tags=["operator"])


class TakeoverError(RuntimeError):
    """Base class for typed break-glass failures."""


class TakeoverPersistenceError(TakeoverError):
    """Evidence failed after the agent had already been silenced."""


class TakeoverNotActive(TakeoverError):
    """Operator ending was attempted before a completed takeover."""


class TakeoverEventWriter(Protocol):
    """Narrow append-only evidence contract used after synchronous silencing."""

    async def append_event(
        self,
        *,
        call_id: str,
        ts: datetime,
        event_type: LedgerEventType | str,
        state_before: StateSnapshot,
        state_after: StateSnapshot,
        redacted_reason: str,
    ) -> int:
        """Append one monotonic evidence row."""


class OperatorEndWriter(Protocol):
    """Atomic terminal-disposition boundary implemented by call persistence."""

    async def set_ended_operator(
        self,
        *,
        call_id: str,
        ts: datetime,
        reason: str,
        state: StateSnapshot,
    ) -> int:
        """Persist ENDED_OPERATOR and its required attributed reason."""


CancelPendingWork = Callable[[], Sequence[str]]
SynchronousEffect = Callable[[], None]


@dataclass(frozen=True, slots=True)
class TakeoverResult:
    """Persisted break-glass result exposed to the operator surface."""

    call_id: str
    event_seq: int
    ts: datetime
    call_state_before: CallState
    cancelled_work: tuple[str, ...]
    safety_failures: tuple[str, ...] = ()
    banner: str = TAKEOVER_BANNER


@dataclass(frozen=True, slots=True)
class OperatorEndResult:
    """The only terminal outcome available after break-glass takeover."""

    call_id: str
    disposition_seq: int
    ts: datetime
    disposition: Disposition = Disposition.ENDED_OPERATOR


class TaskCancellationGroup:
    """Synchronous cancellation registry for call-owned LLM/TTS work."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def register(self, name: str, task: asyncio.Task[Any]) -> None:
        """Register one uniquely named call-owned task."""
        normalized = name.strip()
        if not normalized:
            raise ValueError("task name must not be empty")
        prior = self._tasks.get(normalized)
        if prior is not None and not prior.done():
            raise ValueError(f"task {normalized!r} is already pending")
        self._tasks[normalized] = task

    def cancel_all(self) -> tuple[str, ...]:
        """Cancel every pending task without awaiting a stale callback."""
        cancelled: list[str] = []
        for name, task in tuple(self._tasks.items()):
            if not task.done():
                task.cancel()
                cancelled.append(name)
        self._tasks.clear()
        return tuple(cancelled)


class BreakGlassTakeover:
    """Own the permanent authority boundary for one active call.

    The first three operations in :meth:`takeover` contain no await:
    revoke authority, cancel pending work, stop generated speech. Persistence
    happens only after those safety effects have completed.
    """

    def __init__(
        self,
        *,
        state: StateMachineCoordinator,
        event_writer: TakeoverEventWriter,
        end_writer: OperatorEndWriter,
        revoke_tools: SynchronousEffect,
        cancel_pending_work: CancelPendingWork,
        stop_generated_speech: SynchronousEffect,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._state = state
        self._event_writer = event_writer
        self._end_writer = end_writer
        self._revoke_tools = revoke_tools
        self._cancel_pending_work = cancel_pending_work
        self._stop_generated_speech = stop_generated_speech
        self._clock = clock
        self._agent_enabled = True
        self._generation = 0
        self._started = False
        self._result: TakeoverResult | None = None
        self._failure: BaseException | None = None
        self._completed = asyncio.Event()
        self._end_lock = asyncio.Lock()
        self._ended = False

    @property
    def agent_enabled(self) -> bool:
        """Whether any model/tool/TTS callback may still act."""
        return self._agent_enabled

    @property
    def call_id(self) -> str:
        """Stable call identity used by the process-local registry."""
        return self._state.call_id

    @property
    def snapshot(self) -> StateSnapshot:
        """Current immutable domain state."""
        return self._state.snapshot

    @property
    def banner(self) -> str | None:
        """Persistent operator banner after takeover begins."""
        return TAKEOVER_BANNER if self._started else None

    def capture_agent_generation(self) -> int:
        """Return the token every outbound async operation must retain."""
        return self._generation

    def allows_agent_callback(self, generation: int) -> bool:
        """Drop callbacks from before takeover or outside an agent-owned state."""
        return (
            self._agent_enabled
            and generation == self._generation
            and self._state.snapshot.call in {CallState.ACTIVE, CallState.DEGRADED}
        )

    async def takeover(self) -> TakeoverResult:
        """Silence first, then persist OPERATOR_TAKEOVER exactly once."""
        if self._started:
            await self._completed.wait()
            if self._result is not None:
                return self._result
            assert self._failure is not None
            raise TakeoverPersistenceError(
                "takeover evidence failed after permanent agent revocation"
            ) from self._failure

        self._started = True

        # Strict synchronous safety order. No await may move above these lines.
        self._agent_enabled = False
        self._generation += 1
        safety_failures: list[str] = []
        try:
            self._revoke_tools()
        except Exception:
            safety_failures.append("revoke_tools")
        try:
            cancelled_work = tuple(self._cancel_pending_work())
        except Exception:
            cancelled_work = ()
            safety_failures.append("cancel_pending_work")
        try:
            self._stop_generated_speech()
        except Exception:
            safety_failures.append("stop_generated_speech")

        try:
            transition = await self._state.transition(
                CallState.OPERATOR_TAKEOVER,
                reason_code="operator_takeover",
            )
            timestamp = self._clock()
            seq = await self._event_writer.append_event(
                call_id=self._state.call_id,
                ts=timestamp,
                event_type=LedgerEventType.OPERATOR_TAKEOVER,
                state_before=transition.plan.state_after,
                state_after=transition.plan.state_after,
                redacted_reason=(
                    f"operator_break_glass:safety_failures_{len(safety_failures)}:"
                    f"cancelled_{len(cancelled_work)}"
                ),
            )
            self._result = TakeoverResult(
                call_id=self._state.call_id,
                event_seq=seq,
                ts=timestamp,
                call_state_before=transition.plan.state_before.call,
                cancelled_work=cancelled_work,
                safety_failures=tuple(safety_failures),
            )
            return self._result
        except BaseException as error:
            self._failure = error
            raise TakeoverPersistenceError(
                "takeover evidence failed after permanent agent revocation"
            ) from error
        finally:
            self._completed.set()

    async def end_with_reason(self, reason: str) -> OperatorEndResult:
        """End a taken-over call with the required ENDED_OPERATOR disposition."""
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("operator end reason must not be empty")
        if len(normalized_reason) > MAX_OPERATOR_REASON_LENGTH:
            raise ValueError("operator end reason exceeds 500 characters")

        async with self._end_lock:
            if self._result is None or self._state.snapshot.call is not CallState.OPERATOR_TAKEOVER:
                raise TakeoverNotActive("call is not in OPERATOR_TAKEOVER")
            if self._ended:
                raise TakeoverNotActive("operator-taken call has already ended")

            await self._state.transition(
                CallState.ENDED,
                reason_code="operator_ended_call",
            )
            timestamp = self._clock()
            seq = await self._end_writer.set_ended_operator(
                call_id=self._state.call_id,
                ts=timestamp,
                reason=normalized_reason,
                state=self._state.snapshot,
            )
            self._ended = True
            return OperatorEndResult(
                call_id=self._state.call_id,
                disposition_seq=seq,
                ts=timestamp,
            )


class TakeoverRegistry:
    """Process-local index populated by the deterministic call controller."""

    def __init__(self) -> None:
        self._calls: dict[str, BreakGlassTakeover] = {}

    def register(self, takeover: BreakGlassTakeover) -> None:
        """Register one active call's break-glass boundary."""
        self._calls[takeover.call_id] = takeover

    def get(self, call_id: str) -> BreakGlassTakeover | None:
        """Return the exact registered call, if active."""
        return self._calls.get(call_id)

    def discard(self, call_id: str) -> None:
        """Remove a terminal call from the operator index."""
        self._calls.pop(call_id, None)


def _registry(request: Request) -> TakeoverRegistry:
    registry = getattr(request.app.state, "takeover_sessions", None)
    if not isinstance(registry, TakeoverRegistry):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator takeover is unavailable.",
        )
    return registry


@router.post("/api/takeover", response_model=ServerEvent)
async def request_takeover(payload: TakeoverRequest, request: Request) -> ServerEvent:
    """Execute break-glass ordering and return its persisted state event."""
    takeover = _registry(request).get(payload.call_id)
    if takeover is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active call was not found.",
        )
    try:
        result = await takeover.takeover()
    except TakeoverPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent was silenced, but takeover evidence could not be persisted.",
        ) from error
    return ServerEvent(
        type=EventType.STATE_CHANGE,
        call_id=result.call_id,
        seq=result.event_seq,
        ts=result.ts,
        payload={
            "machine": "call",
            "before": result.call_state_before.value,
            "after": CallState.OPERATOR_TAKEOVER.value,
            "banner": result.banner,
            "cancelled_work": list(result.cancelled_work),
            "safety_failures": list(result.safety_failures),
        },
    )


@router.post("/api/call/end", response_model=ServerEvent)
async def end_operator_call(payload: EndCallRequest, request: Request) -> ServerEvent:
    """Allow only a required-reason ENDED_OPERATOR close after takeover."""
    registry = _registry(request)
    takeover = registry.get(payload.call_id)
    if takeover is None or takeover.snapshot.call is not CallState.OPERATOR_TAKEOVER:
        normal_ender = getattr(request.app.state, "normal_call_ender", None)
        if not callable(normal_ender):
            if takeover is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Call is not awaiting an operator ending.",
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active call was not found.",
            )
        try:
            result = await normal_ender(payload.call_id, payload.reason)
        except LookupError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active call was not found.",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A non-empty operator reason is required.",
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Call is not active.",
            ) from error
        return ServerEvent(
            type=EventType.DISPOSITION,
            call_id=result.call_id,
            seq=result.disposition_seq,
            ts=result.ts,
            payload={
                "call_state": CallState.ENDED.value,
                "disposition": Disposition.ENDED_OPERATOR.value,
                "reason": payload.reason,
            },
        )
    try:
        result = await takeover.end_with_reason(payload.reason)
    except TakeoverNotActive as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Call is not awaiting an operator ending.",
        ) from error
    registry.discard(payload.call_id)
    return ServerEvent(
        type=EventType.DISPOSITION,
        call_id=result.call_id,
        seq=result.disposition_seq,
        ts=result.ts,
        payload={
            "call_state": CallState.ENDED.value,
            "disposition": result.disposition.value,
            "reason": payload.reason,
        },
    )
