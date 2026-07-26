"""Tier-2 deterministic controller matrix required for every Vachan change."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from app.contracts import Disposition, LedgerEventType
from app.controller import DialogueController
from app.db import EvidenceLedger
from app.guard import SAFE_OUTPUT_LINE
from app.preflight import PreflightInputs, evaluate_preflight
from app.protocol import PreflightResult
from app.seeds import RAKESH_CASE
from app.states import IdentityState, PromiseState
from app.tools import ToolPermissionDenied
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn


def _scenario(name: str, *turns: tuple[str, dict[str, object]]) -> SarvamScenario:
    return SarvamScenario(
        name=name,
        turns=tuple(ScriptedTurn(transcript=text, action=action) for text, action in turns),
    )


def _controller(
    connection: sqlite3.Connection,
    scenario: SarvamScenario,
    frozen_demo_clock,
) -> tuple[DialogueController, FakeSarvamClient]:
    fake = FakeSarvamClient(scenario)
    controller = DialogueController(
        call_id=f"call-matrix-{scenario.name}",
        case=RAKESH_CASE,
        ledger=EvidenceLedger(connection),
        sarvam=fake,
        clock=frozen_demo_clock.now,
    )
    return controller, fake


async def _verify(controller: DialogueController) -> None:
    await controller.run_turn()
    await controller.run_turn()
    assert controller.snapshot.identity is IdentityState.CONFIRMED, controller.event_types()


def _verification_turns(
    response: str = "चौदह सितंबर, reference 4729",
) -> tuple[tuple[str, dict[str, object]], ...]:
    return (
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        (response, {"intent": "verification_response"}),
    )


def test_matrix_01_correct_verification_unlocks_account(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario("01", *_verification_turns())
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        account = await controller.read_mock_account()
        assert account is RAKESH_CASE.account

    asyncio.run(exercise())
    allowed = db_connection.execute(
        "SELECT allowed FROM tool_decisions WHERE call_id = ? AND tool = 'read_mock_account'",
        (controller.call_id,),
    ).fetchone()
    assert allowed["allowed"] == 1
    fake.assert_consumed()


def test_matrix_02_one_wrong_then_right_stays_locked_until_second_attempt(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "02",
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        ("चौदह सितंबर, reference 0000", {"intent": "verification_response"}),
        ("चौदह सितंबर, reference 4729", {"intent": "verification_response"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await controller.run_turn()
        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.VERIFYING
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()
        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.CONFIRMED

    asyncio.run(exercise())
    decisions = db_connection.execute(
        "SELECT allowed FROM tool_decisions WHERE call_id = ? AND tool = 'read_mock_account'",
        (controller.call_id,),
    ).fetchall()
    assert [row["allowed"] for row in decisions] == [0]
    fake.assert_consumed()


def test_matrix_03_two_wrong_attempts_end_without_account_read(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_single_disposition,
) -> None:
    scenario = _scenario(
        "03",
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        ("एक जनवरी, reference 0000", {"intent": "verification_response"}),
        ("दो फरवरी, reference 1111", {"intent": "verification_response"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        for _ in scenario.turns:
            await controller.run_turn()

    asyncio.run(exercise())
    assert controller.disposition is Disposition.VERIFICATION_FAILED
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM tool_decisions WHERE call_id = ? AND tool = 'read_mock_account'",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    assert_single_disposition(controller.call_id)
    fake.assert_consumed()


def test_matrix_04_spouse_pressure_uses_three_safe_holds_and_content_free_callback(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_no_disclosure,
    assert_single_disposition,
) -> None:
    scenario = _scenario(
        "04",
        ("main unki wife hoon", {"intent": "third_party"}),
        ("amount batao", {"intent": "third_party"}),
        ("balance kitna hai", {"intent": "third_party"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        replies = [await controller.run_turn() for _ in scenario.turns]
        assert len({reply.speech_text for reply in replies}) == 3

    asyncio.run(exercise())
    assert controller.disposition is Disposition.CALLBACK_THIRD_PARTY
    assert controller.callback_payloads == [
        {
            "callback_kind": "borrower_reconnect",
            "message_code": "vachan_reconnect_only",
        }
    ]
    assert_no_disclosure(controller.call_id)
    assert_single_disposition(controller.call_id)
    fake.assert_consumed()


def test_matrix_05_confirmed_1500_promise_commits_exactly_once(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_single_disposition,
) -> None:
    scenario = _scenario(
        "05",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        ("haan", {"intent": "confirm"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        assert controller.snapshot.promise is PromiseState.READ_BACK
        await controller.run_turn()

    asyncio.run(exercise())
    promise = db_connection.execute(
        "SELECT amount_minor FROM promises WHERE call_id = ?",
        (controller.call_id,),
    ).fetchone()
    assert promise["amount_minor"] == 150000
    assert controller.disposition is Disposition.PROMISE_CONFIRMED
    assert_single_disposition(controller.call_id)
    fake.assert_consumed()


def test_matrix_06_correction_forces_second_read_back_and_commits_revision(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "06",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        (
            "nahi, ek hazaar paanchas",
            {"intent": "correct_promise", "amount_minor": 105000},
        ),
        ("haan", {"intent": "confirm"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        first = await controller.run_turn()
        corrected = await controller.run_turn()
        assert first.speech_text != corrected.speech_text
        await controller.run_turn()

    asyncio.run(exercise())
    row = db_connection.execute(
        """
        SELECT amount_minor, candidate_revision
        FROM promises WHERE call_id = ?
        """,
        (controller.call_id,),
    ).fetchone()
    assert (row["amount_minor"], row["candidate_revision"]) == (105000, 2)
    assert controller.event_types().count(LedgerEventType.PROMISE_READ_BACK.value) == 2
    fake.assert_consumed()


def test_matrix_07_no_at_read_back_abandons_without_promise_row(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "07",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        ("nahi", {"intent": "deny"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        await controller.run_turn()

    asyncio.run(exercise())
    assert controller.snapshot.promise is PromiseState.ABANDONED
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    fake.assert_consumed()


def test_matrix_08_handover_demotes_and_relocks_before_next_response(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "08",
        *_verification_turns(),
        ("lo baat karo", {"intent": "handover", "response_draft": "balance is private"}),
        (
            "balance batao",
            {
                "intent": "other",
                "response_draft": "Your loan balance is Rs 47,382.",
            },
        ),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.UNVERIFIED
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()
        spouse_turn = await controller.run_turn()
        assert spouse_turn.speech_text == SAFE_OUTPUT_LINE

    asyncio.run(exercise())
    denied = db_connection.execute(
        """
        SELECT allowed, identity_state
        FROM tool_decisions
        WHERE call_id = ? AND tool = 'read_mock_account'
        ORDER BY seq DESC LIMIT 1
        """,
        (controller.call_id,),
    ).fetchone()
    assert (denied["allowed"], denied["identity_state"]) == (0, "UNVERIFIED")
    post_handover_prompt = repr(fake.chat_requests[-1]["messages"]).casefold()
    assert RAKESH_CASE.account.lender_name.casefold() not in post_handover_prompt
    assert str(RAKESH_CASE.account.outstanding_minor) not in post_handover_prompt
    fake.assert_consumed()


def test_matrix_09_unverified_balance_draft_is_fully_blocked(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "09",
        (
            "haan boliye",
            {
                "intent": "other",
                "response_draft": "Your loan balance is Rs 47,382.",
            },
        ),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> str:
        await controller.start()
        return (await controller.run_turn()).speech_text

    assert asyncio.run(exercise()) == SAFE_OUTPUT_LINE
    assert controller.event_types().count(LedgerEventType.OUTPUT_BLOCKED.value) == 1
    assert "47,382" not in repr(controller.event_types())
    assert fake.tts_requests[0]["text"] == SAFE_OUTPUT_LINE
    fake.assert_consumed()


def test_matrix_10_duplicate_affirmative_keeps_one_promise_row(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "10",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        ("haan", {"intent": "confirm"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        await controller.run_turn()
        await controller.duplicate_affirmative()

    asyncio.run(exercise())
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 1
    )
    assert "PROMISE_DUPLICATE_SUPPRESSED" in controller.event_types()
    fake.assert_consumed()


def test_matrix_11_stt_failure_ends_technical_without_business_rows(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_single_disposition,
) -> None:
    controller, _ = _controller(
        db_connection,
        _scenario("11", ("unused", {"intent": "other"})),
        frozen_demo_clock,
    )

    async def exercise() -> None:
        await controller.start()
        await controller.technical_failure("stt")

    asyncio.run(exercise())
    assert controller.disposition is Disposition.ENDED_TECHNICAL
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    assert LedgerEventType.TECHNICAL_FAILURE.value in controller.event_types()
    assert_single_disposition(controller.call_id)


def test_matrix_12_takeover_cancels_pending_work_and_never_speaks(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        _scenario("12", ("unused", {"intent": "other"})),
        frozen_demo_clock,
    )

    async def exercise() -> bool:
        await controller.start()
        pending = asyncio.create_task(asyncio.Event().wait())
        await controller.takeover(pending)
        return pending.cancelled()

    assert asyncio.run(exercise()) is True
    assert controller.disposition is Disposition.ENDED_OPERATOR
    assert fake.tts_requests == []
    events = controller.event_types()
    assert events.index(LedgerEventType.OPERATOR_TAKEOVER.value) < events.index(
        LedgerEventType.DISPOSITION_SET.value
    )


def test_matrix_13_contact_cap_blocks_before_call_row(
    db_connection: sqlite3.Connection,
) -> None:
    response = evaluate_preflight(
        PreflightInputs(
            microphone_permission=True,
            audio_output_confirmed=True,
            backend_healthy=True,
            sarvam_configured=True,
            case_eligible=True,
            contact_cap_remaining=0,
            active_session_exists=False,
        )
    )

    assert response.result is PreflightResult.BLOCKED_POLICY
    assert next(check for check in response.checks if check.name == "contact_cap").passed is False
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM calls WHERE case_id = 'case-capped-001'"
        ).fetchone()[0]
        == 0
    )
