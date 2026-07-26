"""Execution tests for pure and evidence-backed state transitions."""

import asyncio
import json
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contracts import LedgerEventType, StateSnapshot
from app.db import EvidenceLedger, migrate_schema
from app.seeds import reset_and_reseed_demo_cases
from app.state_machine import (
    AppliedTransition,
    AuthorizationRelockError,
    StateMachineCoordinator,
    fresh_call_snapshot,
    plan_transition,
)
from app.states import (
    TRANSITION_TABLES,
    CallState,
    IdentityState,
    InvalidStateTransition,
    PromiseState,
    State,
    StateMachine,
)
from app.tools import PermissionContext, ToolName, evaluate_tool_permission

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


class RecordingWriter:
    """In-memory stand-in exposing the same narrow contract as EvidenceLedger."""

    def __init__(
        self,
        *,
        before_append: Callable[[dict[str, Any]], None] | None = None,
        fail: bool = False,
    ) -> None:
        self.rows: list[dict[str, Any]] = []
        self.before_append = before_append
        self.fail = fail

    async def append_event(self, **row: Any) -> int:
        if self.before_append is not None:
            self.before_append(row)
        if self.fail:
            raise RuntimeError("simulated ledger failure")
        self.rows.append(row)
        return len(self.rows)


def snapshot_with_state(state: State) -> StateSnapshot:
    snapshot = fresh_call_snapshot()
    if isinstance(state, CallState):
        return replace(snapshot, call=state)
    if isinstance(state, IdentityState):
        return replace(snapshot, identity=state)
    return replace(snapshot, promise=state)


def coordinator(
    writer: RecordingWriter,
    **callbacks: Any,
) -> StateMachineCoordinator:
    return StateMachineCoordinator(
        call_id="call-001",
        event_writer=writer,
        clock=lambda: NOW,
        **callbacks,
    )


def advance_identity_to_confirmed(engine: StateMachineCoordinator) -> None:
    async def advance() -> None:
        await engine.transition(IdentityState.VERIFYING, reason_code="verification_started")
        await engine.transition(IdentityState.CONFIRMED, reason_code="verification_passed")

    asyncio.run(advance())


def advance_call_to_active(engine: StateMachineCoordinator) -> None:
    async def advance() -> None:
        await engine.transition(CallState.PREFLIGHT, reason_code="preflight_started")
        await engine.transition(CallState.READY, reason_code="preflight_passed")
        await engine.transition(CallState.CONNECTING, reason_code="connection_started")
        await engine.transition(CallState.ACTIVE, reason_code="connection_ready")

    asyncio.run(advance())


def account_tool_allowed(engine: StateMachineCoordinator) -> bool:
    snapshot = engine.snapshot
    return evaluate_tool_permission(
        ToolName.READ_MOCK_ACCOUNT,
        PermissionContext(
            call_state=snapshot.call,
            identity_state=snapshot.identity,
            promise_state=snapshot.promise,
        ),
    ).allowed


@pytest.mark.parametrize(
    ("machine", "state_before", "state_after"),
    [
        (machine, state_before, state_after)
        for machine, transitions in TRANSITION_TABLES.items()
        for state_before, state_after in transitions
    ],
)
def test_pure_planner_accepts_every_frozen_legal_edge(
    machine: StateMachine,
    state_before: State,
    state_after: State,
) -> None:
    plan = plan_transition(snapshot_with_state(state_before), state_after)

    assert plan.event.machine is machine
    assert plan.event.accepted is True
    assert plan.state_before == snapshot_with_state(state_before)
    assert {
        StateMachine.CALL: plan.state_after.call,
        StateMachine.IDENTITY: plan.state_after.identity,
        StateMachine.PROMISE: plan.state_after.promise,
    }[machine] is state_after


def test_fresh_coordinator_never_restores_identity_from_another_call() -> None:
    first = coordinator(RecordingWriter())
    advance_identity_to_confirmed(first)
    second = coordinator(RecordingWriter())

    assert first.snapshot.identity is IdentityState.CONFIRMED
    assert second.snapshot == fresh_call_snapshot()
    assert second.snapshot.identity is IdentityState.UNVERIFIED


def test_accepted_transitions_append_exactly_one_row_each() -> None:
    writer = RecordingWriter()
    engine = coordinator(writer)

    async def run() -> None:
        await engine.transition(CallState.PREFLIGHT, reason_code="preflight_started")
        await engine.transition(CallState.READY, reason_code="preflight_passed")
        await engine.transition(IdentityState.VERIFYING, reason_code="verification_started")
        await engine.transition(IdentityState.CONFIRMED, reason_code="verification_passed")
        await engine.transition(PromiseState.CANDIDATE, reason_code="candidate_created")
        await engine.transition(PromiseState.READ_BACK, reason_code="read_back_started")

    asyncio.run(run())

    assert len(writer.rows) == 6
    assert all(row["event_type"] is LedgerEventType.STATE_TRANSITION for row in writer.rows)
    assert writer.rows[0]["state_before"].call is CallState.IDLE
    assert writer.rows[0]["state_after"].call is CallState.PREFLIGHT
    assert writer.rows[-1]["state_before"].promise is PromiseState.CANDIDATE
    assert writer.rows[-1]["state_after"].promise is PromiseState.READ_BACK


def test_illegal_transition_is_persisted_and_does_not_change_state() -> None:
    writer = RecordingWriter()
    engine = coordinator(writer)

    with pytest.raises(InvalidStateTransition):
        asyncio.run(engine.transition(CallState.ACTIVE, reason_code="illegal_test"))

    assert engine.snapshot == fresh_call_snapshot()
    assert len(writer.rows) == 1
    assert writer.rows[0]["event_type"] is LedgerEventType.STATE_TRANSITION_REJECTED
    assert writer.rows[0]["state_before"] == writer.rows[0]["state_after"]
    assert writer.rows[0]["redacted_reason"] == "transition_not_allowed:call:idle:active"


def test_confirmation_is_persisted_before_authorization_opens() -> None:
    writer = RecordingWriter()
    engine = coordinator(writer)
    asyncio.run(engine.transition(IdentityState.VERIFYING, reason_code="verification_started"))

    writer.before_append = lambda row: (
        pytest.fail("CONFIRMED opened before evidence persisted")
        if engine.snapshot.identity is IdentityState.CONFIRMED
        else None
    )
    asyncio.run(engine.transition(IdentityState.CONFIRMED, reason_code="verification_passed"))

    assert engine.snapshot.identity is IdentityState.CONFIRMED


def test_handover_relocks_before_ledger_await_and_before_next_utterance() -> None:
    timeline: list[str] = []
    writer = RecordingWriter()
    engine: StateMachineCoordinator

    def on_revoke(snapshot: StateSnapshot) -> None:
        assert snapshot.identity is IdentityState.UNVERIFIED
        timeline.append("tools_relocked")

    def before_append(row: dict[str, Any]) -> None:
        if row["state_before"].identity is IdentityState.CONFIRMED:
            assert engine.snapshot.identity is IdentityState.UNVERIFIED
            assert timeline == ["tools_relocked"]
            timeline.append("ledger_append")

    def on_transition(transition: AppliedTransition) -> None:
        if transition.plan.state_before.identity is not IdentityState.CONFIRMED:
            return
        assert engine.snapshot.identity is IdentityState.UNVERIFIED
        assert account_tool_allowed(engine) is False
        assert timeline == ["tools_relocked", "ledger_append"]
        timeline.append("observer_can_emit_safe_utterance")

    writer.before_append = before_append
    engine = coordinator(
        writer,
        on_authorization_revoked=on_revoke,
        on_transition=on_transition,
    )
    advance_call_to_active(engine)
    advance_identity_to_confirmed(engine)
    assert account_tool_allowed(engine) is True
    timeline.clear()

    asyncio.run(engine.transition(IdentityState.UNVERIFIED, reason_code="explicit_handover"))

    assert timeline == [
        "tools_relocked",
        "ledger_append",
        "observer_can_emit_safe_utterance",
    ]


def test_demotion_stays_fail_closed_when_ledger_write_fails() -> None:
    writer = RecordingWriter()
    engine = coordinator(writer)
    advance_identity_to_confirmed(engine)
    writer.fail = True

    with pytest.raises(RuntimeError, match="simulated ledger failure"):
        asyncio.run(engine.transition(IdentityState.UNVERIFIED, reason_code="explicit_handover"))

    assert engine.snapshot.identity is IdentityState.UNVERIFIED


def test_relock_callback_failure_is_typed_and_state_remains_demoted() -> None:
    writer = RecordingWriter()

    def failed_relock(_snapshot: StateSnapshot) -> None:
        raise RuntimeError("simulated cache failure")

    engine = coordinator(writer, on_authorization_revoked=failed_relock)
    advance_identity_to_confirmed(engine)

    with pytest.raises(AuthorizationRelockError):
        asyncio.run(engine.transition(IdentityState.THIRD_PARTY, reason_code="new_speaker"))

    assert engine.snapshot.identity is IdentityState.THIRD_PARTY
    assert writer.rows[-1]["redacted_reason"] == "authorization_relock_failed"


def test_reason_codes_reject_raw_utterance_text() -> None:
    engine = coordinator(RecordingWriter())

    with pytest.raises(ValueError, match="redacted token"):
        asyncio.run(
            engine.transition(
                CallState.PREFLIGHT,
                reason_code="the caller said my balance is overdue",
            )
        )


def test_real_ledger_records_accepted_and_rejected_snapshot_rows() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        ("call-001", "case-rakesh-001", NOW.isoformat(), "streaming_pcm16_ws"),
    )
    engine = StateMachineCoordinator(
        call_id="call-001",
        event_writer=ledger,
        clock=lambda: NOW,
    )

    async def run() -> None:
        await engine.transition(CallState.PREFLIGHT, reason_code="preflight_started")
        with pytest.raises(InvalidStateTransition):
            await engine.transition(CallState.ACTIVE, reason_code="invalid_direct_start")

    try:
        asyncio.run(run())
        rows = connection.execute(
            """
            SELECT seq, type, state_before, state_after, redacted_reason
            FROM events
            WHERE call_id = ?
            ORDER BY seq
            """,
            ("call-001",),
        ).fetchall()
    finally:
        connection.close()

    assert [row["seq"] for row in rows] == [1, 2]
    assert [row["type"] for row in rows] == [
        LedgerEventType.STATE_TRANSITION.value,
        LedgerEventType.STATE_TRANSITION_REJECTED.value,
    ]
    assert json.loads(rows[0]["state_before"])["call"] == "IDLE"
    assert json.loads(rows[0]["state_after"])["call"] == "PREFLIGHT"
    assert rows[1]["state_before"] == rows[1]["state_after"]
    assert rows[1]["redacted_reason"] == "transition_not_allowed:call:preflight:active"
