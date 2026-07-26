"""Canonical demo arc: handover precedes the sole terminal promise outcome."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from app.contracts import Disposition, LedgerEventType
from app.controller import ControllerClosedError, DialogueController
from app.db import EvidenceLedger
from app.seeds import RAKESH_CASE
from app.states import IdentityState, PromiseState
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn


def test_demo_handover_reverifies_then_ends_on_one_terminal_promise(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    """Prove the live script never asks a terminal call to process another turn."""

    scenario = SarvamScenario(
        name="safe-terminal-demo-arc",
        turns=(
            ScriptedTurn("Rakesh bol raha hoon", {"intent": "borrower_present"}),
            ScriptedTurn(
                "चौदह सितंबर, reference 4729",
                {"intent": "verification_response"},
            ),
            ScriptedTurn(
                "pandrah sau Friday",
                {
                    "intent": "offer_promise",
                    "amount_minor": 150_000,
                    "date_phrase": "Friday",
                },
            ),
            ScriptedTurn("lo baat karo", {"intent": "handover"}),
            ScriptedTurn("main unki wife hoon", {"intent": "third_party"}),
            ScriptedTurn("Rakesh bol raha hoon", {"intent": "other"}),
            ScriptedTurn(
                "चौदह सितंबर, reference 4729",
                {"intent": "verification_response"},
            ),
            ScriptedTurn(
                "Saturday kar dijiye",
                {"intent": "correct_promise", "date_phrase": "Saturday"},
            ),
            ScriptedTurn("haan", {"intent": "confirm"}),
        ),
    )
    fake = FakeSarvamClient(scenario)
    controller = DialogueController(
        call_id="call-safe-terminal-demo-arc",
        case=RAKESH_CASE,
        ledger=EvidenceLedger(db_connection),
        sarvam=fake,
        clock=frozen_demo_clock.now,
    )
    turn_log: list[tuple[IdentityState, PromiseState, Disposition | None, int]] = []

    def record(turn_disposition: Disposition | None) -> None:
        event_count = db_connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        turn_log.append(
            (
                controller.snapshot.identity,
                controller.snapshot.promise,
                turn_disposition,
                event_count,
            )
        )

    async def exercise() -> None:
        await controller.start()
        for _ in range(len(scenario.turns)):
            turn = await controller.run_turn()
            record(turn.disposition)

        with pytest.raises(ControllerClosedError):
            await controller.run_turn()

    asyncio.run(exercise())

    assert [(identity, promise, disposition) for identity, promise, disposition, _ in turn_log] == [
        (IdentityState.VERIFYING, PromiseState.NONE, None),
        (IdentityState.CONFIRMED, PromiseState.NONE, None),
        (IdentityState.CONFIRMED, PromiseState.READ_BACK, None),
        (IdentityState.UNVERIFIED, PromiseState.READ_BACK, None),
        (IdentityState.THIRD_PARTY, PromiseState.READ_BACK, None),
        (IdentityState.VERIFYING, PromiseState.READ_BACK, None),
        (IdentityState.CONFIRMED, PromiseState.READ_BACK, None),
        (IdentityState.CONFIRMED, PromiseState.READ_BACK, None),
        (
            IdentityState.CONFIRMED,
            PromiseState.COMMITTED,
            Disposition.PROMISE_CONFIRMED,
        ),
    ]
    assert [count for *_, count in turn_log] == sorted(count for *_, count in turn_log)
    assert controller.verification.attempts == 1

    private_values = (
        RAKESH_CASE.account.lender_name,
        str(RAKESH_CASE.account.outstanding_minor),
        "pandrah sau Friday",
    )
    for request_index in (4, 5, 6):
        prompt = json.dumps(
            fake.chat_requests[request_index]["messages"],
            ensure_ascii=False,
        )
        assert all(value not in prompt for value in private_values)

    events = db_connection.execute(
        """
        SELECT seq, type, redacted_reason
        FROM events
        WHERE call_id = ?
        ORDER BY seq
        """,
        (controller.call_id,),
    ).fetchall()
    disposition_events = [
        event for event in events if event["type"] == LedgerEventType.DISPOSITION_SET.value
    ]
    assert len(disposition_events) == 1
    assert disposition_events[0] == events[-1]
    persisted_disposition = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (controller.call_id,),
    ).fetchone()["disposition"]
    assert persisted_disposition == Disposition.PROMISE_CONFIRMED.value
    assert any(
        event["redacted_reason"] == "borrower_returned_fresh_verification" for event in events
    )

    promise = db_connection.execute(
        """
        SELECT amount_minor, date_iso, candidate_revision
        FROM promises
        WHERE call_id = ?
        """,
        (controller.call_id,),
    ).fetchone()
    assert dict(promise) == {
        "amount_minor": 150_000,
        "date_iso": "2026-08-01",
        "candidate_revision": 2,
    }
    fake.assert_consumed()
