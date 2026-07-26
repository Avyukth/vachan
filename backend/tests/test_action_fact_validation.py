"""Fail-closed controller regressions for untrusted promise action facts."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping

import pytest

from app.controller import ControllerClosedError, DialogueController
from app.db import EvidenceLedger
from app.seeds import RAKESH_CASE
from app.states import PromiseState
from app.templates import TemplateId, render_template
from app.tools import ToolName
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn


def _controller(
    connection: sqlite3.Connection,
    frozen_demo_clock,
    *,
    name: str,
    actions: tuple[tuple[str, Mapping[str, object]], ...],
) -> tuple[DialogueController, FakeSarvamClient]:
    turns = (
        ScriptedTurn("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        ScriptedTurn(
            "चौदह सितंबर, reference 4729",
            {"intent": "verification_response"},
        ),
        *(ScriptedTurn(transcript=transcript, action=action) for transcript, action in actions),
    )
    fake = FakeSarvamClient(SarvamScenario(name=name, turns=turns))
    return (
        DialogueController(
            call_id=f"call-action-facts-{name}",
            case=RAKESH_CASE,
            ledger=EvidenceLedger(connection),
            sarvam=fake,
            clock=frozen_demo_clock.now,
        ),
        fake,
    )


async def _run_all(controller: DialogueController, count: int) -> list[str]:
    await controller.start()
    return [(await controller.run_turn()).speech_text for _ in range(count)]


def _tool_decisions(
    connection: sqlite3.Connection,
    *,
    call_id: str,
    tool: ToolName,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT allowed, reason, identity_state, promise_state
        FROM tool_decisions
        WHERE call_id = ? AND tool = ?
        ORDER BY seq
        """,
        (call_id, tool.value),
    ).fetchall()


@pytest.mark.parametrize(
    ("amount_minor", "date_phrase", "reason_code"),
    [
        (0, "Friday", "invalid_amount"),
        (-100, "Friday", "invalid_amount"),
        (150_099, "Friday", "invalid_amount"),
        (1_000_000_000, "Friday", "invalid_amount"),
        (150_000, "next week", "ambiguous_date"),
        (150_000, "2026-07-01", "invalid_date"),
        (150_000, "31/02/2026", "invalid_date"),
        (150_000, "someday", "invalid_date"),
    ],
)
def test_invalid_offer_facts_record_one_redacted_denial_before_clarifying(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    amount_minor: int,
    date_phrase: str,
    reason_code: str,
) -> None:
    transcript = f"hostile offer vector {reason_code}"
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        name=f"offer-{reason_code}-{abs(amount_minor)}-{len(date_phrase)}",
        actions=(
            (
                transcript,
                {
                    "intent": "offer_promise",
                    "amount_minor": amount_minor,
                    "date_phrase": date_phrase,
                },
            ),
        ),
    )

    speech = asyncio.run(_run_all(controller, 3))[-1]

    assert speech == render_template(TemplateId.CLARIFY)
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
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    decisions = _tool_decisions(
        db_connection,
        call_id=controller.call_id,
        tool=ToolName.CREATE_PROMISE_CANDIDATE,
    )
    assert [(row["allowed"], row["reason"]) for row in decisions] == [
        (0, f"invalid_action_facts={reason_code}")
    ]
    fake.assert_consumed()


def test_correction_without_authoritative_candidate_is_denied(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        name="correction-without-candidate",
        actions=(
            (
                "nahi, ek hazaar pachaas",
                {"intent": "correct_promise", "amount_minor": 105_000},
            ),
        ),
    )

    speech = asyncio.run(_run_all(controller, 3))[-1]

    assert speech == render_template(TemplateId.CLARIFY)
    assert controller.snapshot.promise is PromiseState.NONE
    decisions = _tool_decisions(
        db_connection,
        call_id=controller.call_id,
        tool=ToolName.CORRECT_PROMISE_CANDIDATE,
    )
    assert len(decisions) == 1
    assert decisions[0]["allowed"] == 0
    assert "condition_failed=uncommitted_candidate_exists" in decisions[0]["reason"]
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    fake.assert_consumed()


def test_correction_after_abandonment_uses_authoritative_state(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        name="correction-after-abandonment",
        actions=(
            (
                "pandrah sau Friday",
                {
                    "intent": "offer_promise",
                    "amount_minor": 150_000,
                    "date_phrase": "Friday",
                },
            ),
            ("nahi", {"intent": "deny"}),
            (
                "theek hai, ek hazaar pachaas",
                {"intent": "correct_promise", "amount_minor": 105_000},
            ),
        ),
    )

    speech = asyncio.run(_run_all(controller, 5))[-1]

    assert speech == render_template(TemplateId.CLARIFY)
    assert controller.snapshot.promise is PromiseState.ABANDONED
    decisions = _tool_decisions(
        db_connection,
        call_id=controller.call_id,
        tool=ToolName.CORRECT_PROMISE_CANDIDATE,
    )
    assert len(decisions) == 1
    assert decisions[0]["allowed"] == 0
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    fake.assert_consumed()


def test_correction_after_commit_is_rejected_without_post_terminal_evidence(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        name="correction-after-commit",
        actions=(
            (
                "pandrah sau Friday",
                {
                    "intent": "offer_promise",
                    "amount_minor": 150_000,
                    "date_phrase": "Friday",
                },
            ),
            ("haan", {"intent": "confirm"}),
        ),
    )

    asyncio.run(_run_all(controller, 4))

    with pytest.raises(ControllerClosedError):
        asyncio.run(
            controller._correct_promise(  # noqa: SLF001
                "nahi, ek hazaar pachaas",
                105_000,
                None,
            )
        )
    assert controller.snapshot.promise is PromiseState.COMMITTED
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 1
    )
    decisions = _tool_decisions(
        db_connection,
        call_id=controller.call_id,
        tool=ToolName.CORRECT_PROMISE_CANDIDATE,
    )
    assert decisions == []
    fake.assert_consumed()
