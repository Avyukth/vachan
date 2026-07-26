"""Integration tests for persisted tool decisions and zero-mutation denials."""

import asyncio
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.contracts import LedgerEventType, StateSnapshot
from app.db import EvidenceLedger, migrate_schema
from app.gated_tools import (
    AsyncToolMutationRejected,
    GatedToolExecutor,
    ToolFacts,
)
from app.seeds import RAKESH_CASE, reset_and_reseed_demo_cases
from app.state_machine import StateMachineCoordinator
from app.states import CallState, IdentityState, PromiseState
from app.tools import ToolDecision, ToolName, ToolPermissionDenied

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def database() -> tuple[sqlite3.Connection, EvidenceLedger]:
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
        ("call-001", RAKESH_CASE.case_id, NOW.isoformat(), "streaming_pcm16_ws"),
    )
    return connection, ledger


async def advance_call_to_active(engine: StateMachineCoordinator) -> None:
    await engine.transition(CallState.PREFLIGHT, reason_code="preflight_started")
    await engine.transition(CallState.READY, reason_code="preflight_passed")
    await engine.transition(CallState.CONNECTING, reason_code="connection_started")
    await engine.transition(CallState.ACTIVE, reason_code="connection_ready")


async def confirm_identity(engine: StateMachineCoordinator) -> None:
    await engine.transition(IdentityState.VERIFYING, reason_code="verification_started")
    await engine.transition(IdentityState.CONFIRMED, reason_code="verification_passed")


def test_denied_tool_persists_decision_and_performs_zero_mutation() -> None:
    connection, ledger = database()
    engine = StateMachineCoordinator(
        call_id="call-001",
        event_writer=ledger,
        clock=lambda: NOW,
    )
    asyncio.run(advance_call_to_active(engine))
    executor = GatedToolExecutor(
        call_id="call-001",
        authorization_state=engine,
        decision_writer=ledger,
        clock=lambda: NOW,
    )
    mutations: list[str] = []

    try:
        with pytest.raises(ToolPermissionDenied):
            asyncio.run(
                executor.execute(
                    ToolName.READ_MOCK_ACCOUNT,
                    operation=lambda: mutations.append("private account read"),
                )
            )
        row = connection.execute(
            """
            SELECT event.type, event.redacted_reason, decision.allowed,
                   decision.identity_state, decision.reason
            FROM events AS event
            JOIN tool_decisions AS decision
              ON decision.call_id = event.call_id AND decision.seq = event.seq
            ORDER BY event.seq DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()

    assert mutations == []
    assert dict(row) == {
        "type": LedgerEventType.TOOL_DECISION.value,
        "redacted_reason": "tool_denied:read_mock_account",
        "allowed": 0,
        "identity_state": "UNVERIFIED",
        "reason": "identity_state=UNVERIFIED requires one of ['CONFIRMED']",
    }


def test_confirmed_unlock_is_evidenced_before_allowed_side_effect() -> None:
    connection, ledger = database()
    engine = StateMachineCoordinator(
        call_id="call-001",
        event_writer=ledger,
        clock=lambda: NOW,
    )
    asyncio.run(advance_call_to_active(engine))
    asyncio.run(confirm_identity(engine))
    executor = GatedToolExecutor(
        call_id="call-001",
        authorization_state=engine,
        decision_writer=ledger,
        clock=lambda: NOW,
    )

    try:
        result = asyncio.run(
            executor.execute(
                ToolName.READ_MOCK_ACCOUNT,
                operation=lambda: RAKESH_CASE.account,
            )
        )
        rows = connection.execute(
            "SELECT seq, type, state_after FROM events ORDER BY seq"
        ).fetchall()
        decision = connection.execute(
            "SELECT allowed, identity_state FROM tool_decisions ORDER BY seq DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()

    assert result is RAKESH_CASE.account
    confirmed_seq = next(
        row["seq"]
        for row in rows
        if row["type"] == LedgerEventType.STATE_TRANSITION.value
        and '"identity":"CONFIRMED"' in row["state_after"]
    )
    tool_seq = next(
        row["seq"] for row in rows if row["type"] == LedgerEventType.TOOL_DECISION.value
    )
    assert confirmed_seq < tool_seq
    assert dict(decision) == {"allowed": 1, "identity_state": "CONFIRMED"}


@dataclass
class MutableAuthorizationState:
    call_id: str
    snapshot: StateSnapshot


class DemotingDecisionWriter:
    def __init__(self, state: MutableAuthorizationState) -> None:
        self.state = state
        self.rows: list[tuple[ToolDecision, StateSnapshot]] = []

    async def append_tool_decision(self, **values: Any) -> int:
        decision = values["decision"]
        snapshot = values["state"]
        self.rows.append((decision, snapshot))
        if len(self.rows) == 1:
            self.state.snapshot = replace(
                self.state.snapshot,
                identity=IdentityState.UNVERIFIED,
            )
        return len(self.rows)


def test_handover_during_decision_persistence_rechecks_and_blocks_mutation() -> None:
    state = MutableAuthorizationState(
        call_id="call-001",
        snapshot=StateSnapshot(
            call=CallState.ACTIVE,
            identity=IdentityState.CONFIRMED,
            promise=PromiseState.NONE,
        ),
    )
    writer = DemotingDecisionWriter(state)
    executor = GatedToolExecutor(
        call_id="call-001",
        authorization_state=state,
        decision_writer=writer,
        clock=lambda: NOW,
    )
    mutations: list[str] = []

    with pytest.raises(ToolPermissionDenied):
        asyncio.run(
            executor.execute(
                ToolName.READ_MOCK_ACCOUNT,
                operation=lambda: mutations.append("stale mutation"),
            )
        )

    assert mutations == []
    assert [decision.allowed for decision, _snapshot in writer.rows] == [True, False]
    assert [snapshot.identity for _decision, snapshot in writer.rows] == [
        IdentityState.CONFIRMED,
        IdentityState.UNVERIFIED,
    ]


def test_executor_has_no_state_override_and_rejects_async_mutations() -> None:
    state = MutableAuthorizationState(
        call_id="call-001",
        snapshot=StateSnapshot(
            call=CallState.ACTIVE,
            identity=IdentityState.UNVERIFIED,
            promise=PromiseState.NONE,
        ),
    )
    writer = DemotingDecisionWriter(state)
    executor = GatedToolExecutor(
        call_id="call-001",
        authorization_state=state,
        decision_writer=writer,
        clock=lambda: NOW,
    )

    assert "identity_state" not in ToolFacts.__dataclass_fields__

    async def mutation() -> None:
        return None

    with pytest.raises(AsyncToolMutationRejected):
        asyncio.run(
            executor.execute(
                ToolName.READ_MOCK_ACCOUNT,
                operation=mutation,
            )
        )
