"""Fail-closed orchestration for broken runtime dependencies.

This module owns ordering and outcome facts, while persistence, state
transitions, promise abandonment, and device cancellation remain behind narrow
interfaces. Raw exception text is intentionally absent from every public type.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from app.contracts import BUSINESS_DISPOSITIONS, Disposition, LedgerEventType, StateSnapshot
from app.protocol import PreflightResponse, PreflightResult
from app.states import CallState, PromiseState

_REASON_CODE = re.compile(r"^[a-z][a-z0-9_:-]{0,99}$")
_ABANDONABLE_PROMISE_STATES = frozenset(
    {
        PromiseState.CANDIDATE,
        PromiseState.READ_BACK,
        PromiseState.CORRECTED,
    }
)


class FailureComponent(StrEnum):
    """Dependencies whose failure must terminate model-driven work."""

    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    BACKEND = "backend"


class TechnicalFailureError(RuntimeError):
    """Base failure-path contract error."""


class RetryPreflightRequired(TechnicalFailureError):
    """A retry was requested without a fresh successful preflight."""


class TechnicalEndingRequired(TechnicalFailureError):
    """Retry observation occurred before the failed call ended safely."""


class TechnicalSafetyActionError(TechnicalFailureError):
    """One or more synchronous safety callbacks failed."""

    def __init__(self, failed_actions: tuple[str, ...]) -> None:
        self.failed_actions = failed_actions
        super().__init__("technical safety callbacks failed: " + ",".join(failed_actions))


@dataclass(frozen=True, slots=True)
class TechnicalEvent:
    """Redacted evidence for a failure or terminal disposition."""

    event_type: LedgerEventType
    ts: datetime
    component: FailureComponent
    reason_code: str
    retryable: bool
    disposition: Disposition | None = None

    def __post_init__(self) -> None:
        if self.ts.tzinfo is None or self.ts.utcoffset() is None:
            raise ValueError("technical event timestamp must be timezone-aware")
        if not _REASON_CODE.fullmatch(self.reason_code):
            raise ValueError("reason_code must be a redacted lowercase token")
        is_disposition = self.event_type is LedgerEventType.DISPOSITION_SET
        if is_disposition != (self.disposition is not None):
            raise ValueError("only a disposition event may carry a disposition")
        if self.disposition in BUSINESS_DISPOSITIONS:
            raise ValueError("technical failure cannot produce a business disposition")

    def as_log_record(self) -> dict[str, str | bool]:
        record: dict[str, str | bool] = {
            "event_type": self.event_type.value,
            "component": self.component.value,
            "reason_code": self.reason_code,
            "retryable": self.retryable,
        }
        if self.disposition is not None:
            record["disposition"] = self.disposition.value
        return record


@dataclass(frozen=True, slots=True)
class TechnicalFailureResult:
    """Fail-closed state after all immediate safety actions."""

    generation: int
    event: TechnicalEvent
    call_state: CallState
    promise_abandoned: bool
    can_end_safely: bool = True
    can_takeover: bool = True
    accepts_async_results: bool = False


@dataclass(frozen=True, slots=True)
class TechnicalEnding:
    """The only direct terminal outcome owned by this coordinator."""

    event: TechnicalEvent
    call_state: CallState
    disposition: Disposition
    business_outcome: bool = False

    def __post_init__(self) -> None:
        if self.disposition is not Disposition.ENDED_TECHNICAL:
            raise ValueError("technical ending must use ENDED_TECHNICAL")
        if self.business_outcome:
            raise ValueError("technical ending can never be a business outcome")


@dataclass(frozen=True, slots=True)
class FreshPreflightReceipt:
    """One READY preflight observed after a technical ending."""

    case_id: str
    failure_generation: int

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        if self.failure_generation < 1:
            raise ValueError("failure_generation must be positive")


@dataclass(frozen=True, slots=True)
class RetryAuthorization:
    """Single-use authorization to start a new call, never resume the old one."""

    case_id: str
    failure_generation: int


class CallStateCoordinator(Protocol):
    """State-machine surface required by the failure path."""

    @property
    def snapshot(self) -> StateSnapshot: ...

    async def transition(
        self,
        target: CallState | PromiseState,
        *,
        reason_code: str,
    ) -> object: ...


class PromiseAbandoner(Protocol):
    """Promise surface needed to prevent partial candidates becoming outcomes."""

    @property
    def state(self) -> PromiseState: ...

    async def abandon(self) -> None: ...


EventRecorder = Callable[[TechnicalEvent], Awaitable[None] | None]
SafetyCallback = Callable[[], None]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


async def _record(recorder: EventRecorder, event: TechnicalEvent) -> None:
    result = recorder(event)
    if inspect.isawaitable(result):
        await result


class TechnicalFailureCoordinator:
    """Order fail-closed actions and prevent accidental business outcomes."""

    def __init__(
        self,
        *,
        call_state: CallStateCoordinator,
        lock_tools: SafetyCallback,
        cancel_pending_work: SafetyCallback,
        stop_generated_speech: SafetyCallback,
        record_event: EventRecorder,
        promise: PromiseAbandoner | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._call_state = call_state
        self._promise = promise
        self._lock_tools = lock_tools
        self._cancel_pending_work = cancel_pending_work
        self._stop_generated_speech = stop_generated_speech
        self._record_event = record_event
        self._clock = clock
        self._generation = 0
        self._accepting_results = True
        self._failure: TechnicalFailureResult | None = None
        self._ending: TechnicalEnding | None = None
        self._consumed_receipts: set[FreshPreflightReceipt] = set()

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def failure(self) -> TechnicalFailureResult | None:
        return self._failure

    def capture_async_generation(self) -> int:
        """Tag new work so callbacks can prove they belong to the live call."""

        if not self._accepting_results:
            raise TechnicalFailureError("failed call no longer accepts asynchronous work")
        return self._generation

    def accepts_async_result(self, generation: int) -> bool:
        """Drop stale callbacks after failure, end, or generation change."""

        return (
            self._accepting_results
            and self._failure is None
            and self._call_state.snapshot.call is CallState.ACTIVE
            and generation == self._generation
        )

    def _run_safety_callbacks(self) -> tuple[str, ...]:
        failed: list[str] = []
        for name, callback in (
            ("lock_tools", self._lock_tools),
            ("cancel_pending_work", self._cancel_pending_work),
            ("stop_generated_speech", self._stop_generated_speech),
        ):
            try:
                callback()
            except Exception:
                failed.append(name)
        return tuple(failed)

    async def handle_failure(
        self,
        component: FailureComponent,
        *,
        retryable: bool,
        reason_code: str,
    ) -> TechnicalFailureResult:
        """Lock, cancel, silence, abandon, and enter DEGRADED in that order."""

        if self._failure is not None:
            return self._failure
        if not _REASON_CODE.fullmatch(reason_code):
            raise ValueError("reason_code must be a redacted lowercase token")

        self._generation += 1
        self._accepting_results = False
        callback_failures = self._run_safety_callbacks()

        promise_abandoned = False
        snapshot_promise = self._call_state.snapshot.promise
        if snapshot_promise in _ABANDONABLE_PROMISE_STATES:
            if self._promise is None or self._promise.state is not snapshot_promise:
                raise TechnicalFailureError(
                    "active promise state requires its authoritative abandonment boundary"
                )
            await self._promise.abandon()
            await self._call_state.transition(
                PromiseState.ABANDONED,
                reason_code="technical_failure_abandoned_candidate",
            )
            promise_abandoned = True

        if self._call_state.snapshot.call is not CallState.DEGRADED:
            await self._call_state.transition(
                CallState.DEGRADED,
                reason_code=f"{component.value}_technical_failure",
            )

        event = TechnicalEvent(
            event_type=LedgerEventType.TECHNICAL_FAILURE,
            ts=self._clock(),
            component=component,
            reason_code=reason_code,
            retryable=retryable,
        )
        await _record(self._record_event, event)
        self._failure = TechnicalFailureResult(
            generation=self._generation,
            event=event,
            call_state=CallState.DEGRADED,
            promise_abandoned=promise_abandoned,
        )
        if callback_failures:
            raise TechnicalSafetyActionError(callback_failures)
        return self._failure

    async def end_safely(self) -> TechnicalEnding:
        """End the failed call with the sole non-business technical outcome."""

        if self._ending is not None:
            return self._ending
        failure = self._failure
        if failure is None or self._call_state.snapshot.call is not CallState.DEGRADED:
            raise TechnicalFailureError("safe technical ending requires a DEGRADED failure")

        await self._call_state.transition(
            CallState.ENDED,
            reason_code="operator_ended_technical",
        )
        event = TechnicalEvent(
            event_type=LedgerEventType.DISPOSITION_SET,
            ts=self._clock(),
            component=failure.event.component,
            reason_code="ended_technical",
            retryable=failure.event.retryable,
            disposition=Disposition.ENDED_TECHNICAL,
        )
        await _record(self._record_event, event)
        self._ending = TechnicalEnding(
            event=event,
            call_state=CallState.ENDED,
            disposition=Disposition.ENDED_TECHNICAL,
        )
        return self._ending

    def observe_fresh_preflight(
        self,
        *,
        case_id: str,
        response: PreflightResponse,
    ) -> FreshPreflightReceipt:
        """Issue a receipt only for READY observed after the failed call ended."""

        if self._ending is None:
            raise TechnicalEndingRequired("end the failed call before rerunning preflight")
        if not self._ending.event.retryable:
            raise RetryPreflightRequired("failed component is not retryable")
        if response.result is not PreflightResult.READY:
            raise RetryPreflightRequired("retry requires a fresh READY preflight")
        return FreshPreflightReceipt(
            case_id=case_id,
            failure_generation=self._generation,
        )

    def authorize_new_call(self, receipt: FreshPreflightReceipt) -> RetryAuthorization:
        """Consume one current receipt; this never resumes the ended coordinator."""

        if self._ending is None:
            raise TechnicalEndingRequired("failed call has not ended")
        if receipt.failure_generation != self._generation or receipt in self._consumed_receipts:
            raise RetryPreflightRequired("fresh preflight receipt is missing, stale, or consumed")
        self._consumed_receipts.add(receipt)
        return RetryAuthorization(
            case_id=receipt.case_id,
            failure_generation=receipt.failure_generation,
        )
