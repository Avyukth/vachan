"""Technical failures fail closed and never become business outcomes."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contracts import Disposition, StateSnapshot
from app.db import EvidenceLedger, migrate_schema
from app.preflight import PreflightInputs, evaluate_preflight
from app.promise import PromiseEngine, SQLitePromiseRepository
from app.seeds import DEMO_TIME_ANCHOR, reset_and_reseed_demo_cases
from app.states import CallState, IdentityState, PromiseState
from app.technical_failure import (
    FailureComponent,
    FreshPreflightReceipt,
    RetryPreflightRequired,
    TechnicalEndingRequired,
    TechnicalFailureCoordinator,
    TechnicalFailureError,
    TechnicalSafetyActionError,
)
from app.tools import PermissionContext, ToolName, evaluate_tool_permission

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


@dataclass
class FakeCallState:
    snapshot: StateSnapshot = field(
        default_factory=lambda: StateSnapshot(
            call=CallState.ACTIVE,
            identity=IdentityState.CONFIRMED,
            promise=PromiseState.NONE,
        )
    )
    timeline: list[str] = field(default_factory=list)

    async def transition(
        self,
        target: CallState | PromiseState,
        *,
        reason_code: str,
    ) -> object:
        self.timeline.append(f"transition:{target.value}:{reason_code}")
        if isinstance(target, CallState):
            self.snapshot = replace(self.snapshot, call=target)
        else:
            self.snapshot = replace(self.snapshot, promise=target)
        return object()


@dataclass
class FakePromise:
    state: PromiseState = PromiseState.CANDIDATE
    timeline: list[str] = field(default_factory=list)

    async def abandon(self) -> None:
        self.timeline.append("promise_abandoned")
        self.state = PromiseState.ABANDONED


def ready_preflight():
    return evaluate_preflight(
        PreflightInputs(
            microphone_permission=True,
            audio_output_confirmed=True,
            backend_healthy=True,
            sarvam_configured=True,
            case_eligible=True,
            contact_cap_remaining=1,
            active_session_exists=False,
        )
    )


def blocked_preflight():
    return evaluate_preflight(
        PreflightInputs(
            microphone_permission=False,
            audio_output_confirmed=True,
            backend_healthy=True,
            sarvam_configured=True,
            case_eligible=True,
            contact_cap_remaining=1,
            active_session_exists=False,
        )
    )


def make_coordinator(
    *,
    call_state: FakeCallState | None = None,
    promise: FakePromise | PromiseEngine | None = None,
) -> tuple[TechnicalFailureCoordinator, FakeCallState, list[str], list[Any]]:
    call_state = call_state or FakeCallState()
    timeline: list[str] = []
    events: list[Any] = []
    coordinator = TechnicalFailureCoordinator(
        call_state=call_state,
        promise=promise,
        lock_tools=lambda: timeline.append("tools_locked"),
        cancel_pending_work=lambda: timeline.append("pending_cancelled"),
        stop_generated_speech=lambda: timeline.append("speech_stopped"),
        record_event=lambda event: events.append(event),
        clock=lambda: NOW,
    )
    return coordinator, call_state, timeline, events


def test_failure_orders_safety_actions_before_promise_and_state_awaits() -> None:
    call_state = FakeCallState(
        snapshot=StateSnapshot(
            call=CallState.ACTIVE,
            identity=IdentityState.CONFIRMED,
            promise=PromiseState.CANDIDATE,
        )
    )
    promise = FakePromise()
    coordinator, _, safety_timeline, events = make_coordinator(
        call_state=call_state,
        promise=promise,
    )

    result = asyncio.run(
        coordinator.handle_failure(
            FailureComponent.STT,
            retryable=True,
            reason_code="stt_network_failure",
        )
    )

    assert safety_timeline == ["tools_locked", "pending_cancelled", "speech_stopped"]
    assert promise.timeline == ["promise_abandoned"]
    assert call_state.timeline == [
        "transition:ABANDONED:technical_failure_abandoned_candidate",
        "transition:DEGRADED:stt_technical_failure",
    ]
    assert result.promise_abandoned is True
    assert result.accepts_async_results is False
    assert events == [result.event]
    assert result.event.as_log_record() == {
        "event_type": "TECHNICAL_FAILURE",
        "component": "stt",
        "reason_code": "stt_network_failure",
        "retryable": True,
    }


@pytest.mark.parametrize("component", list(FailureComponent))
def test_every_dependency_failure_names_component_and_locks_private_tools(
    component: FailureComponent,
) -> None:
    coordinator, call_state, _, _ = make_coordinator()
    result = asyncio.run(
        coordinator.handle_failure(
            component,
            retryable=component is not FailureComponent.BACKEND,
            reason_code=f"{component.value}_unavailable",
        )
    )

    assert result.call_state is CallState.DEGRADED
    assert result.event.component is component
    for tool in (
        ToolName.READ_MOCK_ACCOUNT,
        ToolName.CREATE_PROMISE_CANDIDATE,
        ToolName.CORRECT_PROMISE_CANDIDATE,
        ToolName.COMMIT_PROMISE,
    ):
        decision = evaluate_tool_permission(
            tool,
            PermissionContext(
                call_state=call_state.snapshot.call,
                identity_state=call_state.snapshot.identity,
                promise_state=call_state.snapshot.promise,
                amount_minor=100,
                date_is_allowed=True,
                candidate_exists=True,
                candidate_read_back=True,
                explicit_affirmative=True,
            ),
        )
        assert decision.allowed is False


def test_stale_results_are_dropped_after_failure_and_cannot_restart_work() -> None:
    coordinator, _, _, _ = make_coordinator()
    generation = coordinator.capture_async_generation()
    assert coordinator.accepts_async_result(generation)

    asyncio.run(
        coordinator.handle_failure(
            FailureComponent.LLM,
            retryable=True,
            reason_code="llm_timeout",
        )
    )

    assert coordinator.accepts_async_result(generation) is False
    assert coordinator.accepts_async_result(coordinator.generation) is False
    with pytest.raises(TechnicalFailureError):
        coordinator.capture_async_generation()


def test_safety_callback_failure_still_degrades_and_runs_remaining_actions() -> None:
    call_state = FakeCallState()
    timeline: list[str] = []
    events: list[Any] = []

    def failed_tool_lock() -> None:
        timeline.append("tools_lock_attempted")
        raise RuntimeError("simulated callback failure")

    coordinator = TechnicalFailureCoordinator(
        call_state=call_state,
        lock_tools=failed_tool_lock,
        cancel_pending_work=lambda: timeline.append("pending_cancelled"),
        stop_generated_speech=lambda: timeline.append("speech_stopped"),
        record_event=lambda event: events.append(event),
        clock=lambda: NOW,
    )

    with pytest.raises(TechnicalSafetyActionError) as captured:
        asyncio.run(
            coordinator.handle_failure(
                FailureComponent.LLM,
                retryable=True,
                reason_code="llm_timeout",
            )
        )

    assert captured.value.failed_actions == ("lock_tools",)
    assert timeline == ["tools_lock_attempted", "pending_cancelled", "speech_stopped"]
    assert call_state.snapshot.call is CallState.DEGRADED
    assert coordinator.failure is not None
    assert events == [coordinator.failure.event]


def test_safe_end_is_exactly_ended_technical_and_idempotent() -> None:
    coordinator, call_state, _, events = make_coordinator()
    asyncio.run(
        coordinator.handle_failure(
            FailureComponent.TTS,
            retryable=True,
            reason_code="tts_network_failure",
        )
    )

    first = asyncio.run(coordinator.end_safely())
    second = asyncio.run(coordinator.end_safely())

    assert first is second
    assert first.call_state is CallState.ENDED
    assert first.disposition is Disposition.ENDED_TECHNICAL
    assert first.business_outcome is False
    assert call_state.snapshot.call is CallState.ENDED
    assert first.event.as_log_record() == {
        "event_type": "DISPOSITION_SET",
        "component": "tts",
        "reason_code": "ended_technical",
        "retryable": True,
        "disposition": "ENDED_TECHNICAL",
    }
    assert len(events) == 2


def test_retry_requires_ended_call_and_fresh_ready_preflight() -> None:
    coordinator, _, _, _ = make_coordinator()
    asyncio.run(
        coordinator.handle_failure(
            FailureComponent.BACKEND,
            retryable=True,
            reason_code="backend_unavailable",
        )
    )

    with pytest.raises(TechnicalEndingRequired):
        coordinator.observe_fresh_preflight(
            case_id="case-rakesh-001",
            response=ready_preflight(),
        )

    asyncio.run(coordinator.end_safely())
    with pytest.raises(RetryPreflightRequired):
        coordinator.observe_fresh_preflight(
            case_id="case-rakesh-001",
            response=blocked_preflight(),
        )

    receipt = coordinator.observe_fresh_preflight(
        case_id="case-rakesh-001",
        response=ready_preflight(),
    )
    authorization = coordinator.authorize_new_call(receipt)
    assert authorization.case_id == "case-rakesh-001"
    assert authorization.failure_generation == coordinator.generation

    with pytest.raises(RetryPreflightRequired):
        coordinator.authorize_new_call(receipt)
    with pytest.raises(RetryPreflightRequired):
        coordinator.authorize_new_call(
            FreshPreflightReceipt(
                case_id="case-rakesh-001",
                failure_generation=coordinator.generation + 1,
            )
        )


def test_nonretryable_failure_cannot_issue_retry_receipt() -> None:
    coordinator, _, _, _ = make_coordinator()
    asyncio.run(
        coordinator.handle_failure(
            FailureComponent.BACKEND,
            retryable=False,
            reason_code="backend_configuration_failure",
        )
    )
    asyncio.run(coordinator.end_safely())

    with pytest.raises(RetryPreflightRequired, match="not retryable"):
        coordinator.observe_fresh_preflight(
            case_id="case-rakesh-001",
            response=ready_preflight(),
        )


def test_inflight_real_candidate_is_abandoned_and_never_committed() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES ('call-technical-001', 'case-rakesh-001', ?, 'streaming_pcm16_ws')
        """,
        (NOW.isoformat(),),
    )
    promise_events: list[Any] = []
    promise = PromiseEngine(
        call_id="call-technical-001",
        repository=SQLitePromiseRepository(ledger),
        demo_time_anchor=DEMO_TIME_ANCHOR,
        clock=lambda: NOW,
        record_event=lambda event: promise_events.append(event),
    )
    asyncio.run(
        promise.create_candidate(
            caller_phrase="pandrah sau Friday",
            amount="1500",
            date_phrase="Friday",
        )
    )
    asyncio.run(promise.read_back())
    call_state = FakeCallState(
        snapshot=StateSnapshot(
            call=CallState.ACTIVE,
            identity=IdentityState.CONFIRMED,
            promise=PromiseState.READ_BACK,
        )
    )
    coordinator, _, _, _ = make_coordinator(call_state=call_state, promise=promise)

    result = asyncio.run(
        coordinator.handle_failure(
            FailureComponent.STT,
            retryable=True,
            reason_code="stt_disconnected",
        )
    )
    ending = asyncio.run(coordinator.end_safely())

    assert result.promise_abandoned is True
    assert promise.state is PromiseState.ABANDONED
    assert call_state.snapshot.promise is PromiseState.ABANDONED
    assert ending.disposition is Disposition.ENDED_TECHNICAL
    assert connection.execute("SELECT COUNT(*) FROM promise_candidates").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 0
    connection.close()
