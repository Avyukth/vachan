"""SQLite evidence-ledger schema and integrity tests."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import (
    SCHEMA_VERSION,
    ActiveCallExists,
    EvidenceLedger,
    derive_idempotency_key,
    migrate_schema,
)
from app.seeds import DEMO_CASES, DEMO_TIME_ANCHOR, reset_and_reseed_demo_cases
from app.states import CallState, IdentityState, PromiseState
from app.tools import PermissionContext, ToolName, evaluate_tool_permission

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
EXPECTED_TABLES = {
    "calls",
    "cases",
    "demo_resets",
    "events",
    "operator_notes",
    "promise_candidates",
    "promises",
    "tool_decisions",
}


@pytest.fixture
def connection() -> sqlite3.Connection:
    database = sqlite3.connect(":memory:", isolation_level=None)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    migrate_schema(database)
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def ledger(connection: sqlite3.Connection) -> EvidenceLedger:
    return EvidenceLedger(connection)


def seed_cases(ledger: EvidenceLedger) -> None:
    assert reset_and_reseed_demo_cases(ledger) == ("case-rakesh-001", "case-capped-001")


def start_call(
    connection: sqlite3.Connection,
    *,
    call_id: str = "call-001",
    case_id: str = "case-rakesh-001",
) -> None:
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (call_id, case_id, NOW.isoformat(), "streaming_pcm16_ws"),
    )


def state_snapshot() -> StateSnapshot:
    return StateSnapshot(
        call=CallState.ACTIVE,
        identity=IdentityState.CONFIRMED,
        promise=PromiseState.NONE,
    )


def insert_candidate(
    connection: sqlite3.Connection,
    *,
    candidate_id: str = "candidate-001",
    call_id: str = "call-001",
    revision: int = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO promise_candidates (
            id, call_id, caller_phrase, amount_minor, date_iso, revision,
            read_back_ts, confirmed_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            candidate_id,
            call_id,
            "pandrah sau, Friday",
            150_000,
            "2026-07-31",
            revision,
            (NOW + timedelta(seconds=1)).isoformat(),
            (NOW + timedelta(seconds=2)).isoformat(),
        ),
    )


def test_schema_migration_is_idempotent_and_has_expected_domain_tables(
    connection: sqlite3.Connection,
) -> None:
    migrate_schema(connection)
    tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_schema
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        )
    }
    assert tables == EXPECTED_TABLES
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_v1_database_additively_migrates_reset_audit_and_delete_guards(
    connection: sqlite3.Connection,
) -> None:
    connection.execute("DROP TABLE demo_resets")
    connection.execute("PRAGMA user_version = 1")

    migrate_schema(connection)

    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert (
        connection.execute(
            """
            SELECT COUNT(*) FROM sqlite_schema
            WHERE type = 'table' AND name = 'demo_resets'
            """
        ).fetchone()[0]
        == 1
    )
    trigger_names = {
        row["name"]
        for row in connection.execute(
            """
            SELECT name FROM sqlite_schema
            WHERE type = 'trigger' AND name LIKE 'prevent_%_delete'
            """
        )
    }
    assert {
        "prevent_events_delete",
        "prevent_tool_decisions_delete",
        "prevent_promise_candidates_delete",
        "prevent_promises_delete",
        "prevent_operator_notes_delete",
        "prevent_demo_resets_delete",
    }.issubset(trigger_names)


def test_case_schema_has_no_generic_prompt_log_or_blocked_draft_columns(
    connection: sqlite3.Connection,
) -> None:
    event_columns = {row["name"] for row in connection.execute("PRAGMA table_info(events)")}
    assert event_columns == {
        "call_id",
        "seq",
        "ts",
        "type",
        "state_before",
        "state_after",
        "redacted_reason",
    }
    assert not {"payload", "draft", "body", "prompt", "expected_value"} & event_columns


def test_database_prevents_two_active_calls_for_one_case(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)

    with pytest.raises(sqlite3.IntegrityError, match="calls.case_id"):
        start_call(connection, call_id="call-002")


def test_idempotency_key_is_candidate_revision_and_duplicate_insert_fails(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    insert_candidate(connection)

    key = asyncio.run(
        ledger.commit_promise(
            call_id="call-001",
            candidate_id="candidate-001",
            revision=1,
            amount_minor=150_000,
            date_iso="2026-07-31",
            committed_ts=NOW + timedelta(seconds=3),
        )
    )
    assert key == derive_idempotency_key("candidate-001", 1) == "candidate-001:1"

    with pytest.raises(sqlite3.IntegrityError):
        asyncio.run(
            ledger.commit_promise(
                call_id="call-001",
                candidate_id="candidate-001",
                revision=1,
                amount_minor=150_000,
                date_iso="2026-07-31",
                committed_ts=NOW + timedelta(seconds=4),
            )
        )
    assert connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("table", "setup_sql", "update_sql"),
    [
        (
            "events",
            """
            INSERT INTO events (
                call_id, seq, ts, type, state_before, state_after, redacted_reason
            ) VALUES ('call-001', 1, '2026-07-26T12:00:00+00:00', 'TOOL_DECISION',
                      '{"call":"ACTIVE"}', '{"call":"ACTIVE"}', 'allowed')
            """,
            "UPDATE events SET redacted_reason = 'edited'",
        ),
        (
            "promises",
            """
            INSERT INTO promises (
                call_id, candidate_id, candidate_revision, amount_minor,
                date_iso, idempotency_key, committed_ts
            ) VALUES ('call-001', 'candidate-001', 1, 150000, '2026-07-31',
                      'candidate-001:1', '2026-07-26T12:00:03+00:00')
            """,
            "UPDATE promises SET amount_minor = 1",
        ),
        (
            "operator_notes",
            """
            INSERT INTO operator_notes (call_id, ts, author, text)
            VALUES ('call-001', '2026-07-26T12:00:00+00:00', 'Priya', 'Mock note')
            """,
            "UPDATE operator_notes SET text = 'edited'",
        ),
    ],
)
def test_evidence_tables_reject_updates(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
    table: str,
    setup_sql: str,
    update_sql: str,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    if table == "promises":
        insert_candidate(connection)
    connection.execute(setup_sql)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute(update_sql)


def test_event_sequence_trigger_rejects_gaps(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    snapshot_json = '{"call":"ACTIVE","identity":"CONFIRMED","promise":"NONE"}'

    with pytest.raises(sqlite3.IntegrityError, match="next monotonic value"):
        connection.execute(
            """
            INSERT INTO events (
                call_id, seq, ts, type, state_before, state_after, redacted_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "call-001",
                2,
                NOW.isoformat(),
                "TOOL_DECISION",
                snapshot_json,
                snapshot_json,
                "gap_attempt",
            ),
        )


def test_concurrent_event_writes_have_no_gaps_or_duplicates(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    snapshot = state_snapshot()

    async def append(index: int) -> int:
        return await ledger.append_event(
            call_id="call-001",
            ts=NOW + timedelta(milliseconds=index),
            event_type=LedgerEventType.TOOL_DECISION,
            state_before=snapshot,
            state_after=snapshot,
            redacted_reason=f"decision_{index}",
        )

    async def run_concurrent_writes() -> list[int]:
        return list(await asyncio.gather(*(append(index) for index in range(20))))

    sequences = asyncio.run(run_concurrent_writes())

    assert sorted(sequences) == list(range(1, 21))
    rows = connection.execute(
        "SELECT seq FROM events WHERE call_id = ? ORDER BY seq",
        ("call-001",),
    ).fetchall()
    assert [row["seq"] for row in rows] == list(range(1, 21))


def test_domain_mutation_rolls_back_when_its_evidence_insert_fails(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    snapshot = state_snapshot()
    connection.execute(
        """
        CREATE TRIGGER reject_atomic_test_event
        BEFORE INSERT ON events
        WHEN NEW.type = 'REJECT_ATOMIC_TEST'
        BEGIN
            SELECT RAISE(ABORT, 'injected evidence failure');
        END
        """
    )

    def insert_domain_row() -> None:
        insert_candidate(connection)

    with pytest.raises(sqlite3.IntegrityError, match="injected evidence failure"):
        ledger.mutate_with_event(
            call_id="call-001",
            ts=NOW,
            event_type="REJECT_ATOMIC_TEST",
            state_before=snapshot,
            state_after=snapshot,
            redacted_reason="injected_atomic_failure",
            mutation=insert_domain_row,
        )

    assert connection.execute("SELECT COUNT(*) FROM promise_candidates").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_operator_ending_atomically_persists_final_evidence_and_disposition(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    ended = StateSnapshot(
        call=CallState.ENDED,
        identity=IdentityState.UNVERIFIED,
        promise=PromiseState.NONE,
    )

    seq = asyncio.run(
        ledger.set_ended_operator(
            call_id="call-001",
            ts=NOW + timedelta(minutes=1),
            reason="Operator completed the conversation",
            state=ended,
        )
    )

    assert seq == 1
    call = connection.execute(
        """
        SELECT ended, disposition, operator_intervened
        FROM calls WHERE id = ?
        """,
        ("call-001",),
    ).fetchone()
    assert dict(call) == {
        "ended": (NOW + timedelta(minutes=1)).isoformat(),
        "disposition": Disposition.ENDED_OPERATOR.value,
        "operator_intervened": 1,
    }
    event = connection.execute(
        """
        SELECT seq, type, state_before, state_after, redacted_reason
        FROM events WHERE call_id = ?
        """,
        ("call-001",),
    ).fetchone()
    assert event["seq"] == 1
    assert event["type"] == LedgerEventType.DISPOSITION_SET.value
    assert event["state_before"] == event["state_after"]
    assert event["redacted_reason"] == "operator_end:Operator completed the conversation"


def test_duplicate_operator_ending_adds_no_second_event(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    ended = StateSnapshot(
        call=CallState.ENDED,
        identity=IdentityState.UNVERIFIED,
        promise=PromiseState.NONE,
    )
    asyncio.run(
        ledger.set_ended_operator(
            call_id="call-001",
            ts=NOW,
            reason="Operator completed the conversation",
            state=ended,
        )
    )

    with pytest.raises(RuntimeError, match="terminal disposition"):
        asyncio.run(
            ledger.set_ended_operator(
                call_id="call-001",
                ts=NOW + timedelta(seconds=1),
                reason="Duplicate ending",
                state=ended,
            )
        )

    assert (
        connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = ?",
            ("call-001",),
        ).fetchone()[0]
        == 1
    )


def test_tool_decision_and_event_are_inserted_atomically(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    start_call(connection)
    snapshot = state_snapshot()
    decision = evaluate_tool_permission(
        ToolName.READ_MOCK_ACCOUNT,
        PermissionContext(
            call_state=snapshot.call,
            identity_state=snapshot.identity,
            promise_state=snapshot.promise,
        ),
    )

    seq = asyncio.run(
        ledger.append_tool_decision(
            call_id="call-001",
            ts=NOW,
            decision=decision,
            state=snapshot,
        )
    )

    event = connection.execute(
        "SELECT type, redacted_reason FROM events WHERE call_id = ? AND seq = ?",
        ("call-001", seq),
    ).fetchone()
    detail = connection.execute(
        """
        SELECT tool, allowed, identity_state, promise_state, reason
        FROM tool_decisions
        WHERE call_id = ? AND seq = ?
        """,
        ("call-001", seq),
    ).fetchone()
    assert dict(event) == {
        "type": LedgerEventType.TOOL_DECISION.value,
        "redacted_reason": "tool_allowed:read_mock_account",
    }
    assert dict(detail) == {
        "tool": "read_mock_account",
        "allowed": 1,
        "identity_state": "CONFIRMED",
        "promise_state": "NONE",
        "reason": "allowed",
    }


def test_demo_reset_is_scoped_and_refused_during_active_call(
    connection: sqlite3.Connection,
    ledger: EvidenceLedger,
) -> None:
    seed_cases(ledger)
    connection.execute(
        """
        INSERT INTO cases (
            id, name, eligibility, contact_cap_remaining, mock_label,
            verification_birth_day, verification_birth_month,
            verification_reference_last4, lender_name, outstanding_minor,
            emi_schedule_json, demo_time_anchor
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "non-demo-case",
            "Non-demo control",
            True,
            1,
            "NOT DEMO",
            1,
            1,
            "0000",
            "Control",
            0,
            "[]",
            DEMO_TIME_ANCHOR.isoformat(),
        ),
    )
    start_call(connection)

    with pytest.raises(ActiveCallExists):
        ledger.replace_demo_cases(DEMO_CASES, demo_time_anchor=DEMO_TIME_ANCHOR)

    connection.execute(
        """
        UPDATE calls
        SET ended = ?, disposition = ?
        WHERE id = ?
        """,
        (
            (NOW + timedelta(minutes=1)).isoformat(),
            Disposition.ENDED_OPERATOR.value,
            "call-001",
        ),
    )
    ledger.replace_demo_cases(DEMO_CASES, demo_time_anchor=DEMO_TIME_ANCHOR)

    ids = {row["id"] for row in connection.execute("SELECT id FROM cases ORDER BY id").fetchall()}
    assert ids == {"case-capped-001", "case-rakesh-001", "non-demo-case"}
    assert connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
