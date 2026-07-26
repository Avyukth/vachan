"""Direct-tamper regressions for the append-only evidence ledger."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import DEMO_MOCK_LABEL, ActiveCallExists, EvidenceLedger, migrate_schema
from app.seeds import DEMO_CASES, DEMO_TIME_ANCHOR, reset_and_reseed_demo_cases
from app.states import CallState, IdentityState, PromiseState
from app.tools import PermissionContext, ToolName, evaluate_tool_permission

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
SNAPSHOT = StateSnapshot(
    call=CallState.ACTIVE,
    identity=IdentityState.UNVERIFIED,
    promise=PromiseState.NONE,
)


@pytest.fixture
def ledger() -> EvidenceLedger:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    evidence = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(evidence)
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES ('call-immutable', 'case-rakesh-001', ?, 'streaming_pcm16_ws')
        """,
        (NOW.isoformat(),),
    )
    try:
        yield evidence
    finally:
        evidence.close()


def _append_denied_tool_decision(ledger: EvidenceLedger) -> int:
    decision = evaluate_tool_permission(
        ToolName.READ_MOCK_ACCOUNT,
        PermissionContext(
            call_state=SNAPSHOT.call,
            identity_state=SNAPSHOT.identity,
            promise_state=SNAPSHOT.promise,
        ),
    )
    assert not decision.allowed
    return asyncio.run(
        ledger.append_tool_decision(
            call_id="call-immutable",
            ts=NOW,
            decision=decision,
            state=SNAPSHOT,
        )
    )


def _insert_candidate(ledger: EvidenceLedger) -> None:
    ledger.connection.execute(
        """
        INSERT INTO promise_candidates (
            id, call_id, caller_phrase, amount_minor, date_iso, revision,
            read_back_ts, confirmed_ts
        ) VALUES (
            'candidate-immutable', 'call-immutable', 'reviewed test phrase',
            150000, '2026-07-31', 1, ?, ?
        )
        """,
        (
            (NOW + timedelta(seconds=1)).isoformat(),
            (NOW + timedelta(seconds=2)).isoformat(),
        ),
    )


def _insert_promise(ledger: EvidenceLedger) -> None:
    _insert_candidate(ledger)
    ledger.connection.execute(
        """
        INSERT INTO promises (
            call_id, candidate_id, candidate_revision, amount_minor,
            date_iso, idempotency_key, committed_ts
        ) VALUES (
            'call-immutable', 'candidate-immutable', 1, 150000,
            '2026-07-31', 'candidate-immutable:1', ?
        )
        """,
        ((NOW + timedelta(seconds=3)).isoformat(),),
    )


def _insert_operator_note(ledger: EvidenceLedger) -> None:
    ledger.connection.execute(
        """
        INSERT INTO operator_notes (call_id, ts, author, text)
        VALUES ('call-immutable', ?, 'Priya', 'Reviewed mock note')
        """,
        (NOW.isoformat(),),
    )


def _end_call(ledger: EvidenceLedger, call_id: str = "call-immutable") -> None:
    ledger.connection.execute(
        """
        UPDATE calls
        SET ended = ?, disposition = ?
        WHERE id = ?
        """,
        (
            (NOW + timedelta(minutes=1)).isoformat(),
            Disposition.ENDED_OPERATOR.value,
            call_id,
        ),
    )


def _insert_non_demo_case_and_evidence(ledger: EvidenceLedger) -> None:
    ledger.connection.execute(
        """
        INSERT INTO cases (
            id, name, eligibility, contact_cap_remaining, mock_label,
            verification_birth_day, verification_birth_month,
            verification_reference_last4, lender_name, outstanding_minor,
            emi_schedule_json, demo_time_anchor
        ) VALUES (
            'non-demo-case', 'Non-demo control', 1, 1, 'NOT DEMO',
            1, 1, '0000', 'Control', 0, '[]', ?
        )
        """,
        (DEMO_TIME_ANCHOR.isoformat(),),
    )
    ledger.connection.execute(
        """
        INSERT INTO calls (id, case_id, started, ended, transport, disposition)
        VALUES (
            'call-non-demo', 'non-demo-case', ?, ?,
            'streaming_pcm16_ws', 'ENDED_OPERATOR'
        )
        """,
        (
            NOW.isoformat(),
            (NOW + timedelta(minutes=1)).isoformat(),
        ),
    )
    ledger.connection.execute(
        """
        INSERT INTO events (
            call_id, seq, ts, type, state_before, state_after, redacted_reason
        ) VALUES (
            'call-non-demo', 1, ?, 'STATE_TRANSITION',
            '{"call":"ENDED","identity":"UNVERIFIED","promise":"NONE"}',
            '{"call":"ENDED","identity":"UNVERIFIED","promise":"NONE"}',
            'non_demo_control'
        )
        """,
        (NOW.isoformat(),),
    )


def test_denied_tool_decision_cannot_be_rewritten_or_erased_with_its_event(
    ledger: EvidenceLedger,
) -> None:
    seq = _append_denied_tool_decision(ledger)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(
            """
            UPDATE tool_decisions
            SET allowed = 1, reason = 'allowed'
            WHERE call_id = 'call-immutable' AND seq = ?
            """,
            (seq,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(
            "DELETE FROM events WHERE call_id = 'call-immutable' AND seq = ?",
            (seq,),
        )

    decision = ledger.connection.execute(
        """
        SELECT allowed, reason
        FROM tool_decisions
        WHERE call_id = 'call-immutable' AND seq = ?
        """,
        (seq,),
    ).fetchone()
    event_count = ledger.connection.execute(
        """
        SELECT COUNT(*)
        FROM events
        WHERE call_id = 'call-immutable' AND seq = ?
        """,
        (seq,),
    ).fetchone()[0]
    assert dict(decision) == {
        "allowed": 0,
        "reason": "identity_state=UNVERIFIED requires one of ['CONFIRMED']",
    }
    assert event_count == 1


@pytest.mark.parametrize(
    "delete_sql",
    [
        "DELETE FROM calls WHERE id = 'call-immutable'",
        "DELETE FROM cases WHERE id = 'case-rakesh-001'",
    ],
)
def test_parent_cascade_cannot_erase_a_denied_tool_decision(
    ledger: EvidenceLedger,
    delete_sql: str,
) -> None:
    seq = _append_denied_tool_decision(ledger)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(delete_sql)

    assert (
        ledger.connection.execute(
            """
            SELECT COUNT(*)
            FROM tool_decisions
            WHERE call_id = 'call-immutable' AND seq = ?
            """,
            (seq,),
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    ("table", "setup", "update_sql"),
    [
        (
            "events",
            lambda ledger: asyncio.run(
                ledger.append_event(
                    call_id="call-immutable",
                    ts=NOW,
                    event_type=LedgerEventType.STATE_TRANSITION,
                    state_before=SNAPSHOT,
                    state_after=SNAPSHOT,
                    redacted_reason="immutable_test",
                )
            ),
            "UPDATE events SET redacted_reason = 'rewritten'",
        ),
        (
            "tool_decisions",
            _append_denied_tool_decision,
            "UPDATE tool_decisions SET allowed = 1, reason = 'allowed'",
        ),
        (
            "promise_candidates",
            _insert_candidate,
            "UPDATE promise_candidates SET amount_minor = 1",
        ),
        (
            "promises",
            _insert_promise,
            "UPDATE promises SET amount_minor = 1",
        ),
        (
            "operator_notes",
            _insert_operator_note,
            "UPDATE operator_notes SET text = 'rewritten'",
        ),
    ],
)
def test_proof_rows_reject_direct_updates(
    ledger: EvidenceLedger,
    table: str,
    setup,
    update_sql: str,
) -> None:
    setup(ledger)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(update_sql)

    assert ledger.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= 1


def test_sanctioned_reset_is_scoped_authorized_and_audited(
    ledger: EvidenceLedger,
) -> None:
    _append_denied_tool_decision(ledger)
    _insert_non_demo_case_and_evidence(ledger)
    _end_call(ledger)

    assert ledger.connection.execute("SELECT vachan_demo_reset_authorized()").fetchone()[0] == 0

    ledger.replace_demo_cases(DEMO_CASES, demo_time_anchor=DEMO_TIME_ANCHOR)

    cases = {
        row["id"]: row["mock_label"]
        for row in ledger.connection.execute(
            "SELECT id, mock_label FROM cases ORDER BY id"
        ).fetchall()
    }
    assert cases == {
        "case-capped-001": DEMO_MOCK_LABEL,
        "case-capped-002": DEMO_MOCK_LABEL,
        "case-rakesh-001": DEMO_MOCK_LABEL,
        "non-demo-case": "NOT DEMO",
    }
    assert (
        ledger.connection.execute(
            "SELECT COUNT(*) FROM calls WHERE case_id != 'non-demo-case'"
        ).fetchone()[0]
        == 0
    )
    assert (
        ledger.connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = 'call-non-demo'"
        ).fetchone()[0]
        == 1
    )
    audit = ledger.connection.execute(
        """
        SELECT governed_case_count, removed_call_count, redacted_reason
        FROM demo_resets
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    assert dict(audit) == {
        "governed_case_count": 3,
        "removed_call_count": 1,
        "redacted_reason": "sanctioned_demo_reset",
    }
    assert ledger.connection.execute("SELECT vachan_demo_reset_authorized()").fetchone()[0] == 0

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute("UPDATE demo_resets SET removed_call_count = 999")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute("DELETE FROM demo_resets")


def test_refused_active_call_reset_adds_no_audit_and_closes_authorization(
    ledger: EvidenceLedger,
) -> None:
    audit_count = ledger.connection.execute("SELECT COUNT(*) FROM demo_resets").fetchone()[0]

    with pytest.raises(ActiveCallExists):
        ledger.replace_demo_cases(DEMO_CASES, demo_time_anchor=DEMO_TIME_ANCHOR)

    assert (
        ledger.connection.execute("SELECT COUNT(*) FROM demo_resets").fetchone()[0] == audit_count
    )
    assert ledger.connection.execute("SELECT vachan_demo_reset_authorized()").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("table", "setup"),
    [
        (
            "events",
            lambda ledger: asyncio.run(
                ledger.append_event(
                    call_id="call-immutable",
                    ts=NOW,
                    event_type=LedgerEventType.STATE_TRANSITION,
                    state_before=SNAPSHOT,
                    state_after=SNAPSHOT,
                    redacted_reason="immutable_test",
                )
            ),
        ),
        ("tool_decisions", _append_denied_tool_decision),
        ("promise_candidates", _insert_candidate),
        ("promises", _insert_promise),
        ("operator_notes", _insert_operator_note),
    ],
)
def test_proof_rows_reject_direct_deletes(
    ledger: EvidenceLedger,
    table: str,
    setup,
) -> None:
    setup(ledger)

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(f"DELETE FROM {table}")

    assert ledger.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] >= 1


def test_reset_authority_cannot_be_forged_through_ledger_attributes(
    ledger: EvidenceLedger,
) -> None:
    _append_denied_tool_decision(ledger)
    _end_call(ledger)
    audit_count = ledger.connection.execute("SELECT COUNT(*) FROM demo_resets").fetchone()[0]

    # Regression for the concrete audit bypass against the original mutable
    # `_demo_reset_authorized` field and reusable context manager.
    with pytest.raises(AttributeError):
        ledger._demo_reset_authorized = True
    assert not hasattr(ledger, "_authorize_demo_reset")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger.connection.execute(
            "DELETE FROM cases WHERE mock_label = ?",
            (DEMO_MOCK_LABEL,),
        )

    assert ledger.connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 3
    assert ledger.connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1
    assert ledger.connection.execute("SELECT COUNT(*) FROM tool_decisions").fetchone()[0] == 1
    assert (
        ledger.connection.execute("SELECT COUNT(*) FROM demo_resets").fetchone()[0] == audit_count
    )


@pytest.mark.parametrize(
    ("control_name", "arguments"),
    [
        ("create_function", ("vachan_demo_reset_authorized", 0, lambda: 1)),
        ("set_authorizer", (None,)),
        ("executescript", ("DROP TRIGGER prevent_cases_delete;",)),
    ],
)
def test_public_connection_cannot_replace_reset_guards(
    ledger: EvidenceLedger,
    control_name: str,
    arguments: tuple[object, ...],
) -> None:
    with pytest.raises(AttributeError):
        getattr(ledger.connection, control_name)(*arguments)


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TRIGGER prevent_cases_delete",
        "PRAGMA writable_schema = ON",
        "CREATE TABLE reset_bypass (id INTEGER)",
        "/* bypass simple prefix checks */ DROP TRIGGER prevent_cases_delete",
    ],
)
def test_public_connection_cannot_modify_guard_schema(
    ledger: EvidenceLedger,
    sql: str,
) -> None:
    with pytest.raises(sqlite3.DatabaseError, match="connection controls|not authorized"):
        ledger.connection.execute(sql)


def test_public_cursor_does_not_leak_privileged_connection(
    ledger: EvidenceLedger,
) -> None:
    cursor = ledger.connection.execute("SELECT COUNT(*) FROM cases")

    with pytest.raises(AttributeError):
        _ = cursor.connection
    with pytest.raises(AttributeError):
        cursor.execute("DROP TRIGGER prevent_cases_delete")
