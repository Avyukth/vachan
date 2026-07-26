"""Matrix case 8: handover demotes, relocks, and starts a clean context epoch."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime

import pytest

from app.db import EvidenceLedger, migrate_schema
from app.handover import (
    HandoverBoundary,
    HandoverSignal,
    detect_handover,
)
from app.seeds import CONTACT_CAPPED_CASE, RAKESH_CASE, reset_and_reseed_demo_cases
from app.state_machine import StateMachineCoordinator
from app.states import CallState, IdentityState, PromiseState
from app.templates import TemplateId, is_bank_member
from app.tools import PermissionContext, ToolName, evaluate_tool_permission

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def engine_with_ledger() -> tuple[
    sqlite3.Connection,
    StateMachineCoordinator,
    list[str],
]:
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
    relocks: list[str] = []
    engine = StateMachineCoordinator(
        call_id="call-001",
        event_writer=ledger,
        clock=lambda: NOW,
        on_authorization_revoked=lambda snapshot: relocks.append(snapshot.identity.value),
    )
    return connection, engine, relocks


async def advance_to_read_back(engine: StateMachineCoordinator) -> None:
    for target in (
        CallState.PREFLIGHT,
        CallState.READY,
        CallState.CONNECTING,
        CallState.ACTIVE,
        IdentityState.VERIFYING,
        IdentityState.CONFIRMED,
        PromiseState.CANDIDATE,
        PromiseState.READ_BACK,
    ):
        await engine.transition(target, reason_code=f"test_{target.value.lower()}")


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
    ("utterance", "signal", "target"),
    [
        ("main phone de raha hoon", HandoverSignal.EXPLICIT_HANDOVER, IdentityState.UNVERIFIED),
        ("lo baat karo", HandoverSignal.EXPLICIT_HANDOVER, IdentityState.UNVERIFIED),
        ("मैं फोन दे रहा हूँ", HandoverSignal.EXPLICIT_HANDOVER, IdentityState.UNVERIFIED),
        (
            "main unki wife hoon",
            HandoverSignal.NEW_SPEAKER_IDENTIFIED,
            IdentityState.THIRD_PARTY,
        ),
        ("this is Sunita", HandoverSignal.NEW_SPEAKER_IDENTIFIED, IdentityState.THIRD_PARTY),
    ],
)
def test_handover_detection_is_typed_and_redacted(
    utterance: str,
    signal: HandoverSignal,
    target: IdentityState,
) -> None:
    detection = detect_handover(utterance)

    assert detection.signal is signal
    assert detection.identity_target is target
    assert utterance not in repr(detection)


def test_runtime_uncertainty_signals_fail_closed() -> None:
    assert (
        detect_handover("unrecognized phrasing", handover_requested=True).signal
        is HandoverSignal.TYPED_HANDOVER
    )
    assert detect_handover("hello", speaker_changed=True).signal is HandoverSignal.SPEAKER_CHANGE
    assert (
        detect_handover("hello", identity_uncertain=True).signal
        is HandoverSignal.IDENTITY_UNCERTAIN
    )
    assert detect_handover("ordinary continuation").detected is False


def test_case_8_handover_before_affirmation_relocks_and_removes_account_carryover() -> None:
    connection, engine, relocks = engine_with_ledger()
    boundary = HandoverBoundary(state=engine, case=RAKESH_CASE)
    asyncio.run(advance_to_read_back(engine))
    assert account_tool_allowed(engine) is True

    try:
        outcome = asyncio.run(boundary.handle_turn("lo baat karo"))
        assert outcome is not None
        assert engine.snapshot.identity is IdentityState.UNVERIFIED
        assert engine.snapshot.promise is PromiseState.READ_BACK
        assert account_tool_allowed(engine) is False
        assert relocks == ["UNVERIFIED"]
        assert outcome.response_template is TemplateId.ASK_FOR_BORROWER
        assert is_bank_member(outcome.response_text)

        spouse_context = boundary.build_new_speaker_context(
            "Sahyog Finance ka balance ₹47,382 aur due 2026-07-15 hai kya?"
        )
        payload = json.dumps(spouse_context.as_api_messages(), ensure_ascii=False)
        assert spouse_context.contains_private_account_context is False
        assert len(spouse_context.messages) == 3
        assert RAKESH_CASE.account.lender_name not in payload
        assert "47,382" not in payload
        assert "2026-07-15" not in payload
        assert "read_mock_account" not in {tool.value for tool in spouse_context.available_tools}

        event = connection.execute(
            """
            SELECT state_before, state_after, redacted_reason
            FROM events
            ORDER BY seq DESC
            LIMIT 1
            """
        ).fetchone()
        assert '"identity":"CONFIRMED"' in event["state_before"]
        assert '"identity":"UNVERIFIED"' in event["state_after"]
        assert event["redacted_reason"] == "explicit_handover"
    finally:
        connection.close()


def test_identified_spouse_enters_third_party_with_only_content_free_speech() -> None:
    connection, engine, _relocks = engine_with_ledger()
    boundary = HandoverBoundary(state=engine, case=RAKESH_CASE)
    asyncio.run(advance_to_read_back(engine))

    try:
        outcome = asyncio.run(boundary.handle_turn("main unki wife hoon"))
        assert outcome is not None
        assert outcome.identity_state is IdentityState.THIRD_PARTY
        assert outcome.response_template is TemplateId.THIRD_PARTY_CALLBACK
        assert is_bank_member(outcome.response_text)
        rendered = outcome.response_text.casefold()
        assert "balance" not in rendered
        assert "loan" not in rendered
        assert RAKESH_CASE.account.lender_name.casefold() not in rendered
    finally:
        connection.close()


def test_callable_meera_handover_uses_reviewed_meera_copy() -> None:
    connection, engine, _relocks = engine_with_ledger()
    boundary = HandoverBoundary(state=engine, case=CONTACT_CAPPED_CASE)
    asyncio.run(advance_to_read_back(engine))

    try:
        outcome = asyncio.run(boundary.handle_turn("lo baat karo"))
        assert outcome is not None
        assert "Meera" in outcome.response_text
        assert "Rakesh" not in outcome.response_text
        assert is_bank_member(outcome.response_text)
    finally:
        connection.close()


def test_borrower_return_starts_a_completely_fresh_verification_session() -> None:
    connection, engine, _relocks = engine_with_ledger()
    boundary = HandoverBoundary(state=engine, case=RAKESH_CASE)
    asyncio.run(advance_to_read_back(engine))

    try:
        asyncio.run(boundary.handle_turn("main unki wife hoon"))
        session = asyncio.run(boundary.begin_fresh_reverification())

        assert engine.snapshot.identity is IdentityState.VERIFYING
        assert session.attempts == 0
        assert session.status.value == "PENDING"
    finally:
        connection.close()
