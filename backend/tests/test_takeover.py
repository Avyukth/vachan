"""Break-glass ordering, permanent silence, and terminal outcome tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.state_machine import StateMachineCoordinator
from app.states import CallState
from app.takeover import (
    TAKEOVER_BANNER,
    BreakGlassTakeover,
    OperatorEndResult,
    TakeoverNotActive,
    TakeoverPersistenceError,
    TakeoverRegistry,
    TaskCancellationGroup,
    router,
)

NOW = datetime(2026, 7, 26, 13, 0, tzinfo=UTC)


class RecordingWriter:
    def __init__(self, trace: list[str], *, fail_takeover_event: bool = False) -> None:
        self.trace = trace
        self.rows: list[dict[str, Any]] = []
        self.fail_takeover_event = fail_takeover_event

    async def append_event(self, **row: Any) -> int:
        event_type = row["event_type"]
        name = event_type.value if isinstance(event_type, LedgerEventType) else event_type
        self.trace.append(f"persist:{name}")
        if self.fail_takeover_event and event_type is LedgerEventType.OPERATOR_TAKEOVER:
            raise OSError("simulated evidence outage")
        self.rows.append(row)
        return len(self.rows)


class RecordingEndWriter:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.rows: list[dict[str, Any]] = []

    async def set_ended_operator(
        self,
        *,
        call_id: str,
        ts: datetime,
        reason: str,
        state: StateSnapshot,
    ) -> int:
        self.trace.append("persist:DISPOSITION_SET")
        self.rows.append(
            {
                "call_id": call_id,
                "ts": ts,
                "reason": reason,
                "state": state,
                "disposition": Disposition.ENDED_OPERATOR,
            }
        )
        return 99


async def active_state(writer: RecordingWriter) -> StateMachineCoordinator:
    state = StateMachineCoordinator(
        call_id="call-takeover-001",
        event_writer=writer,
        clock=lambda: NOW,
    )
    await state.transition(CallState.PREFLIGHT, reason_code="preflight_started")
    await state.transition(CallState.READY, reason_code="preflight_passed")
    await state.transition(CallState.CONNECTING, reason_code="connection_started")
    await state.transition(CallState.ACTIVE, reason_code="connection_ready")
    writer.trace.clear()
    writer.rows.clear()
    return state


async def make_takeover(
    *,
    fail_takeover_event: bool = False,
    cancellation: TaskCancellationGroup | None = None,
) -> tuple[BreakGlassTakeover, RecordingWriter, RecordingEndWriter, list[str]]:
    trace: list[str] = []
    writer = RecordingWriter(trace, fail_takeover_event=fail_takeover_event)
    end_writer = RecordingEndWriter(trace)
    state = await active_state(writer)
    cancellation = cancellation or TaskCancellationGroup()

    takeover = BreakGlassTakeover(
        state=state,
        event_writer=writer,
        end_writer=end_writer,
        revoke_tools=lambda: trace.append("revoke_tools"),
        cancel_pending_work=lambda: (
            trace.append("cancel_work"),
            *cancellation.cancel_all(),
        )[1:],
        stop_generated_speech=lambda: trace.append("stop_speech"),
        clock=lambda: NOW,
    )
    return takeover, writer, end_writer, trace


def test_takeover_executes_strict_safety_order_before_persistence() -> None:
    async def exercise() -> None:
        takeover, writer, _, trace = await make_takeover()
        generation = takeover.capture_agent_generation()

        result = await takeover.takeover()

        assert trace == [
            "revoke_tools",
            "cancel_work",
            "stop_speech",
            "persist:STATE_TRANSITION",
            "persist:OPERATOR_TAKEOVER",
        ]
        assert result.banner == TAKEOVER_BANNER
        assert takeover.banner == TAKEOVER_BANNER
        assert not takeover.agent_enabled
        assert not takeover.allows_agent_callback(generation)
        assert writer.rows[-1]["event_type"] is LedgerEventType.OPERATOR_TAKEOVER
        assert (
            writer.rows[-1]["redacted_reason"]
            == "operator_break_glass:safety_failures_0:cancelled_0"
        )

    asyncio.run(exercise())


def test_takeover_mid_llm_cancels_task_and_emits_no_agent_audio() -> None:
    async def exercise() -> None:
        cancellation = TaskCancellationGroup()
        gate = asyncio.Event()
        spoken_audio: list[str] = []

        async def pending_llm_then_tts() -> None:
            await gate.wait()
            spoken_audio.append("must never play")

        llm_task = asyncio.create_task(pending_llm_then_tts())
        cancellation.register("llm", llm_task)
        takeover, writer, _, _ = await make_takeover(cancellation=cancellation)

        result = await takeover.takeover()
        gate.set()
        await asyncio.gather(llm_task, return_exceptions=True)

        assert result.cancelled_work == ("llm",)
        assert spoken_audio == []
        assert (
            writer.rows[-1]["redacted_reason"]
            == "operator_break_glass:safety_failures_0:cancelled_1"
        )

    asyncio.run(exercise())


def test_stubborn_late_callback_is_dropped_even_if_cancellation_is_ignored() -> None:
    async def exercise() -> None:
        takeover, _, _, _ = await make_takeover()
        generation = takeover.capture_agent_generation()
        spoken_audio: list[str] = []

        await takeover.takeover()
        if takeover.allows_agent_callback(generation):
            spoken_audio.append("stale TTS")

        assert spoken_audio == []

    asyncio.run(exercise())


def test_duplicate_takeover_is_idempotent_and_agent_never_resumes() -> None:
    async def exercise() -> None:
        takeover, writer, _, trace = await make_takeover()
        first = await takeover.takeover()
        second = await takeover.takeover()

        assert first == second
        assert not takeover.agent_enabled
        assert [row["event_type"] for row in writer.rows].count(
            LedgerEventType.OPERATOR_TAKEOVER
        ) == 1
        assert trace.count("revoke_tools") == 1

    asyncio.run(exercise())


def test_persistence_failure_still_leaves_agent_revoked_and_speech_stopped() -> None:
    async def exercise() -> None:
        takeover, _, _, trace = await make_takeover(fail_takeover_event=True)
        generation = takeover.capture_agent_generation()

        with pytest.raises(TakeoverPersistenceError):
            await takeover.takeover()

        assert trace[:3] == ["revoke_tools", "cancel_work", "stop_speech"]
        assert not takeover.agent_enabled
        assert not takeover.allows_agent_callback(generation)
        assert takeover.banner == TAKEOVER_BANNER

    asyncio.run(exercise())


def test_one_safety_effect_failure_does_not_skip_later_silencing_or_evidence() -> None:
    async def exercise() -> None:
        trace: list[str] = []
        writer = RecordingWriter(trace)
        end_writer = RecordingEndWriter(trace)
        state = await active_state(writer)

        def fail_cancel() -> tuple[str, ...]:
            trace.append("cancel_work")
            raise RuntimeError("simulated cancellation registry failure")

        takeover = BreakGlassTakeover(
            state=state,
            event_writer=writer,
            end_writer=end_writer,
            revoke_tools=lambda: trace.append("revoke_tools"),
            cancel_pending_work=fail_cancel,
            stop_generated_speech=lambda: trace.append("stop_speech"),
            clock=lambda: NOW,
        )

        result = await takeover.takeover()

        assert trace[:3] == ["revoke_tools", "cancel_work", "stop_speech"]
        assert result.safety_failures == ("cancel_pending_work",)
        assert not takeover.agent_enabled
        assert (
            writer.rows[-1]["redacted_reason"]
            == "operator_break_glass:safety_failures_1:cancelled_0"
        )

    asyncio.run(exercise())


@pytest.mark.parametrize("reason", ["", "   ", "x" * 501])
def test_operator_end_requires_a_bounded_reason(reason: str) -> None:
    async def exercise() -> None:
        takeover, _, _, _ = await make_takeover()
        await takeover.takeover()
        with pytest.raises(ValueError):
            await takeover.end_with_reason(reason)

    asyncio.run(exercise())


def test_only_ended_operator_disposition_is_available_after_takeover() -> None:
    async def exercise() -> None:
        takeover, _, end_writer, trace = await make_takeover()

        await takeover.takeover()
        result = await takeover.end_with_reason("Operator completed the conversation")

        assert result == OperatorEndResult(
            call_id="call-takeover-001",
            disposition_seq=99,
            ts=NOW,
        )
        assert result.disposition is Disposition.ENDED_OPERATOR
        assert end_writer.rows == [
            {
                "call_id": "call-takeover-001",
                "ts": NOW,
                "reason": "Operator completed the conversation",
                "state": takeover.snapshot,
                "disposition": Disposition.ENDED_OPERATOR,
            }
        ]
        assert takeover.snapshot.call is CallState.ENDED
        assert trace[-2:] == ["persist:STATE_TRANSITION", "persist:DISPOSITION_SET"]

    asyncio.run(exercise())


def test_call_cannot_end_as_operator_without_successful_takeover() -> None:
    async def exercise() -> None:
        takeover, _, _, _ = await make_takeover()
        with pytest.raises(TakeoverNotActive):
            await takeover.end_with_reason("Operator chose to end")

    asyncio.run(exercise())


def test_operator_routes_return_persisted_takeover_and_disposition_events() -> None:
    takeover, _, _, _ = asyncio.run(make_takeover())
    registry = TakeoverRegistry()
    registry.register(takeover)
    app = FastAPI()
    app.state.takeover_sessions = registry
    app.include_router(router)

    with TestClient(app) as client:
        takeover_response = client.post(
            "/api/takeover",
            json={"api_version": "v0", "call_id": "call-takeover-001"},
        )
        assert takeover_response.status_code == 200
        assert takeover_response.json() == {
            "api_version": "v0",
            "type": "state_change",
            "call_id": "call-takeover-001",
            "seq": 2,
            "ts": "2026-07-26T13:00:00Z",
            "payload": {
                "machine": "call",
                "before": "ACTIVE",
                "after": "OPERATOR_TAKEOVER",
                "banner": TAKEOVER_BANNER,
                "cancelled_work": [],
                "safety_failures": [],
            },
        }

        end_response = client.post(
            "/api/call/end",
            json={
                "api_version": "v0",
                "call_id": "call-takeover-001",
                "reason": "Operator completed the conversation",
            },
        )
        assert end_response.status_code == 200
        assert end_response.json()["payload"] == {
            "call_state": "ENDED",
            "disposition": "ENDED_OPERATOR",
            "reason": "Operator completed the conversation",
        }
        assert registry.get("call-takeover-001") is None


def test_operator_routes_fail_closed_for_unknown_call() -> None:
    app = FastAPI()
    app.state.takeover_sessions = TakeoverRegistry()
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            "/api/takeover",
            json={"api_version": "v0", "call_id": "missing-call"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Active call was not found."}
