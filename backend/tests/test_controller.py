"""Concurrency regressions for the controller's terminal-disposition boundary."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from app.contracts import Disposition, LedgerEventType
from app.controller import ControllerClosedError, DialogueController
from app.db import EvidenceLedger
from app.seeds import RAKESH_CASE
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn


def _controller(
    connection: sqlite3.Connection,
    frozen_demo_clock,
    *,
    call_id: str,
) -> DialogueController:
    return DialogueController(
        call_id=call_id,
        case=RAKESH_CASE,
        ledger=EvidenceLedger(connection),
        sarvam=FakeSarvamClient(
            SarvamScenario(
                name=call_id,
                turns=(ScriptedTurn("unused", {"intent": "other"}),),
            )
        ),
        clock=frozen_demo_clock.now,
    )


def _terminal_evidence(
    connection: sqlite3.Connection,
    call_id: str,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT seq, redacted_reason
        FROM events
        WHERE call_id = ? AND type = ?
        ORDER BY seq
        """,
        (call_id, LedgerEventType.DISPOSITION_SET.value),
    ).fetchall()


def test_concurrent_conflicting_dispositions_persist_one_consistent_winner(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    business_controller = _controller(
        db_connection,
        frozen_demo_clock,
        call_id="call-terminal-conflict",
    )
    technical_controller = _controller(
        db_connection,
        frozen_demo_clock,
        call_id="call-terminal-conflict",
    )

    async def exercise() -> list[None | BaseException]:
        await business_controller.start()
        await technical_controller.activate_existing_call()
        return await asyncio.gather(
            business_controller._set_disposition(  # noqa: SLF001
                Disposition.PROMISE_CONFIRMED,
                reason_code="audit_business",
            ),
            technical_controller._set_disposition(  # noqa: SLF001
                Disposition.ENDED_TECHNICAL,
                reason_code="audit_technical",
            ),
            return_exceptions=True,
        )

    results = asyncio.run(exercise())
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(failures) == 1, results
    assert isinstance(failures[0], ControllerClosedError)

    persisted = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (business_controller.call_id,),
    ).fetchone()
    evidence = _terminal_evidence(db_connection, business_controller.call_id)
    assert len(evidence) == 1, [(row["seq"], row["redacted_reason"]) for row in evidence]
    winner = next(
        controller.disposition
        for controller in (business_controller, technical_controller)
        if controller.disposition is not None
    )
    assert persisted["disposition"] == winner.value


def test_concurrent_duplicate_disposition_is_idempotent(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller = _controller(
        db_connection,
        frozen_demo_clock,
        call_id="call-terminal-duplicate",
    )

    async def exercise() -> None:
        await controller.start()
        await asyncio.gather(
            controller._set_disposition(  # noqa: SLF001 - regression targets this boundary
                Disposition.ENDED_TECHNICAL,
                reason_code="audit_duplicate",
            ),
            controller._set_disposition(  # noqa: SLF001 - regression targets this boundary
                Disposition.ENDED_TECHNICAL,
                reason_code="audit_duplicate",
            ),
        )

    asyncio.run(exercise())

    persisted = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (controller.call_id,),
    ).fetchone()
    assert persisted["disposition"] == Disposition.ENDED_TECHNICAL.value
    assert controller.disposition is Disposition.ENDED_TECHNICAL
    assert len(_terminal_evidence(db_connection, controller.call_id)) == 1


@pytest.mark.parametrize(
    "first, stale",
    [
        (Disposition.ENDED_TECHNICAL, Disposition.PROMISE_CONFIRMED),
        (Disposition.ENDED_TECHNICAL, Disposition.CALLBACK_THIRD_PARTY),
    ],
)
def test_technical_disposition_rejects_stale_business_outcome(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    first: Disposition,
    stale: Disposition,
) -> None:
    controller = _controller(
        db_connection,
        frozen_demo_clock,
        call_id=f"call-terminal-{stale.value.casefold()}",
    )

    async def exercise() -> None:
        await controller.start()
        await controller._set_disposition(  # noqa: SLF001 - regression targets this boundary
            first,
            reason_code="audit_technical_first",
        )
        with pytest.raises(ControllerClosedError):
            await controller._set_disposition(  # noqa: SLF001
                stale,
                reason_code="audit_stale_business",
            )

    asyncio.run(exercise())

    persisted = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (controller.call_id,),
    ).fetchone()
    assert persisted["disposition"] == Disposition.ENDED_TECHNICAL.value
    assert controller.disposition is Disposition.ENDED_TECHNICAL
    assert len(_terminal_evidence(db_connection, controller.call_id)) == 1
