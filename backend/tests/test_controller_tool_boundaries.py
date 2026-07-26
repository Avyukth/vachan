"""Controller regressions for promise authorization and mutation ordering."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.controller import ControllerToolEffectError, DialogueController
from app.db import EvidenceLedger
from app.gated_tools import GatedToolExecutor, ToolFacts
from app.seeds import RAKESH_CASE
from app.states import IdentityState, PromiseState
from app.tools import ToolDecision, ToolName, ToolPermissionDenied
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn


def _controller(
    connection: sqlite3.Connection,
    frozen_demo_clock,
    *,
    name: str,
) -> DialogueController:
    return DialogueController(
        call_id=f"call-controller-tool-boundary-{name}",
        case=RAKESH_CASE,
        ledger=EvidenceLedger(connection),
        sarvam=FakeSarvamClient(
            SarvamScenario(
                name=name,
                turns=(
                    ScriptedTurn("Rakesh bol raha hoon", {"intent": "borrower_present"}),
                    ScriptedTurn(
                        "चौदह सितंबर, reference 4729",
                        {"intent": "verification_response"},
                    ),
                ),
            )
        ),
        clock=frozen_demo_clock.now,
    )


async def _confirm_identity(controller: DialogueController) -> None:
    await controller.start()
    await controller.run_turn()
    await controller.run_turn()
    assert controller.snapshot.identity is IdentityState.CONFIRMED


class _SkippingExecutor:
    """Return success-shaped control without invoking the supplied effect."""

    def __init__(self) -> None:
        self.calls: list[ToolName] = []

    async def execute(
        self,
        tool: ToolName,
        *,
        facts: ToolFacts,
        operation: Callable[[], Any],
    ) -> None:
        del facts, operation
        self.calls.append(tool)


@pytest.mark.parametrize(
    ("boundary", "expected_tool", "candidate_count", "expected_state"),
    [
        ("create", ToolName.CREATE_PROMISE_CANDIDATE, 0, PromiseState.NONE),
        ("correct", ToolName.CORRECT_PROMISE_CANDIDATE, 1, PromiseState.READ_BACK),
        ("commit", ToolName.COMMIT_PROMISE, 1, PromiseState.CONFIRMED),
    ],
)
def test_executor_that_skips_effect_cannot_mutate_promise_boundary(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    boundary: str,
    expected_tool: ToolName,
    candidate_count: int,
    expected_state: PromiseState,
) -> None:
    controller = _controller(
        db_connection,
        frozen_demo_clock,
        name=f"skip-{boundary}",
    )
    skipping = _SkippingExecutor()

    async def exercise() -> None:
        await _confirm_identity(controller)
        if boundary in {"correct", "commit"}:
            await controller._prepare_promise(  # noqa: SLF001
                "pandrah sau Friday",
                150_000,
                "Friday",
            )
        controller._tools = skipping  # type: ignore[assignment]  # noqa: SLF001
        with pytest.raises(ControllerToolEffectError, match=f"{boundary} promise effect"):
            if boundary == "create":
                await controller._prepare_promise(  # noqa: SLF001
                    "pandrah sau Friday",
                    150_000,
                    "Friday",
                )
            elif boundary == "correct":
                await controller._correct_promise(  # noqa: SLF001
                    "nahi, ek hazaar Friday",
                    100_000,
                    "Friday",
                )
            else:
                await controller._confirm_promise()  # noqa: SLF001
                await controller._commit_confirmed_promise()  # noqa: SLF001

    asyncio.run(exercise())

    assert skipping.calls == [expected_tool]
    assert controller.snapshot.promise is expected_state
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == candidate_count
    )
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM tool_decisions WHERE call_id = ? AND tool = ?",
            (controller.call_id, expected_tool.value),
        ).fetchone()[0]
        == 0
    )


def test_candidate_persistence_failure_rolls_back_controller_state_and_evidence(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller = _controller(
        db_connection,
        frozen_demo_clock,
        name="candidate-persistence-failure",
    )

    async def exercise() -> None:
        await _confirm_identity(controller)
        db_connection.execute(
            """
            CREATE TRIGGER reject_controller_candidate_write
            BEFORE INSERT ON promise_candidates
            BEGIN
                SELECT RAISE(ABORT, 'injected controller persistence failure');
            END
            """
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="injected controller persistence failure",
        ):
            await controller._prepare_promise(  # noqa: SLF001
                "pandrah sau Friday",
                150_000,
                "Friday",
            )

    asyncio.run(exercise())

    assert controller.snapshot.promise is PromiseState.NONE
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = ? AND type = ?",
            (controller.call_id, LedgerEventType.PROMISE_CANDIDATE_CREATED.value),
        ).fetchone()[0]
        == 0
    )
    decisions = db_connection.execute(
        """
        SELECT allowed
        FROM tool_decisions
        WHERE call_id = ? AND tool = ?
        ORDER BY seq
        """,
        (controller.call_id, ToolName.CREATE_PROMISE_CANDIDATE.value),
    ).fetchall()
    assert [row["allowed"] for row in decisions] == [1]


class _DemotingDecisionWriter:
    """Demote identity after the first allowed decision is durable."""

    def __init__(
        self,
        *,
        ledger: EvidenceLedger,
        controller: DialogueController,
    ) -> None:
        self._ledger = ledger
        self._controller = controller
        self._demoted = False

    async def append_tool_decision(
        self,
        *,
        call_id: str,
        ts: datetime,
        decision: ToolDecision,
        state: StateSnapshot,
    ) -> int:
        seq = await self._ledger.append_tool_decision(
            call_id=call_id,
            ts=ts,
            decision=decision,
            state=state,
        )
        if decision.allowed and not self._demoted:
            self._demoted = True
            await self._controller.coordinator.transition(
                IdentityState.UNVERIFIED,
                reason_code="test_handover_during_tool_decision",
            )
        return seq


def test_identity_demotion_during_decision_denies_and_leaves_zero_candidate(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller = _controller(
        db_connection,
        frozen_demo_clock,
        name="demotion-race",
    )

    async def exercise() -> None:
        await _confirm_identity(controller)
        ledger = controller.ledger
        controller._tools = GatedToolExecutor(  # noqa: SLF001
            call_id=controller.call_id,
            authorization_state=controller.coordinator,
            decision_writer=_DemotingDecisionWriter(
                ledger=ledger,
                controller=controller,
            ),
            clock=frozen_demo_clock.now,
        )
        with pytest.raises(ToolPermissionDenied) as denied:
            await controller._prepare_promise(  # noqa: SLF001
                "pandrah sau Friday",
                150_000,
                "Friday",
            )
        assert denied.value.decision.tool is ToolName.CREATE_PROMISE_CANDIDATE

    asyncio.run(exercise())

    decisions = db_connection.execute(
        """
        SELECT allowed, identity_state
        FROM tool_decisions
        WHERE call_id = ? AND tool = ?
        ORDER BY seq
        """,
        (controller.call_id, ToolName.CREATE_PROMISE_CANDIDATE.value),
    ).fetchall()
    assert [(row["allowed"], row["identity_state"]) for row in decisions] == [
        (1, IdentityState.CONFIRMED.value),
        (0, IdentityState.UNVERIFIED.value),
    ]
    assert controller.snapshot.identity is IdentityState.UNVERIFIED
    assert controller.snapshot.promise is PromiseState.NONE
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )


def test_affirmative_precedes_commit_decision_and_atomic_terminal_evidence(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller = _controller(
        db_connection,
        frozen_demo_clock,
        name="ordered-commit",
    )

    async def exercise() -> None:
        await _confirm_identity(controller)
        await controller._prepare_promise(  # noqa: SLF001
            "pandrah sau Friday",
            150_000,
            "Friday",
        )
        _speech, _disposition = await controller._confirm_promise()  # noqa: SLF001
        await controller._commit_confirmed_promise()  # noqa: SLF001

    asyncio.run(exercise())

    events = db_connection.execute(
        """
        SELECT seq, type, redacted_reason
        FROM events
        WHERE call_id = ?
        ORDER BY seq
        """,
        (controller.call_id,),
    ).fetchall()

    def sequence(*, event_type: LedgerEventType, reason: str | None = None) -> int:
        matches = [
            row["seq"]
            for row in events
            if row["type"] == event_type.value
            and (reason is None or row["redacted_reason"] == reason)
        ]
        assert len(matches) == 1, [
            (row["seq"], row["type"], row["redacted_reason"]) for row in events
        ]
        return int(matches[0])

    affirmative_seq = sequence(event_type=LedgerEventType.PROMISE_EXPLICITLY_CONFIRMED)
    decision_seq = sequence(
        event_type=LedgerEventType.TOOL_DECISION,
        reason=f"tool_allowed:{ToolName.COMMIT_PROMISE.value}",
    )
    commit_seq = sequence(event_type=LedgerEventType.PROMISE_COMMITTED)
    disposition_seq = sequence(event_type=LedgerEventType.DISPOSITION_SET)
    assert affirmative_seq < decision_seq < commit_seq < disposition_seq

    call = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (controller.call_id,),
    ).fetchone()
    assert call["disposition"] == Disposition.PROMISE_CONFIRMED.value
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM tool_decisions WHERE call_id = ? AND tool = ?",
            (controller.call_id, ToolName.END_CALL.value),
        ).fetchone()[0]
        == 0
    )
