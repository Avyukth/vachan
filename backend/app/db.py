"""SQLite schema and write boundary for Vachan's evidence ledger.

The ledger uses the standard-library sqlite3 driver deliberately: schema
constraints are visible, migrations are explicit, and domain logic remains
independent of an ORM. All runtime event writes go through ``EvidenceLedger``
so sequence allocation occurs under one asyncio lock and one
``BEGIN IMMEDIATE`` transaction.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from app.contracts import Disposition, LedgerEventType, StateSnapshot

if TYPE_CHECKING:
    from app.seeds import MockCaseSeed
    from app.tools import ToolDecision

SCHEMA_VERSION = 2
DEMO_MOCK_LABEL = "DEMO / MOCK DATA"
MutationT = TypeVar("MutationT")

_DISPOSITION_VALUES_SQL = ", ".join(f"'{item.value}'" for item in Disposition)

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    eligibility INTEGER NOT NULL CHECK (eligibility IN (0, 1)),
    contact_cap_remaining INTEGER NOT NULL CHECK (contact_cap_remaining >= 0),
    mock_label TEXT NOT NULL,
    verification_birth_day INTEGER NOT NULL CHECK (verification_birth_day BETWEEN 1 AND 31),
    verification_birth_month INTEGER NOT NULL CHECK (verification_birth_month BETWEEN 1 AND 12),
    verification_reference_last4 TEXT NOT NULL CHECK (length(verification_reference_last4) = 4),
    lender_name TEXT NOT NULL,
    outstanding_minor INTEGER NOT NULL CHECK (outstanding_minor >= 0),
    emi_schedule_json TEXT NOT NULL CHECK (json_valid(emi_schedule_json)),
    demo_time_anchor TEXT NOT NULL CHECK (datetime(demo_time_anchor) IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    started TEXT NOT NULL CHECK (datetime(started) IS NOT NULL),
    ended TEXT CHECK (ended IS NULL OR datetime(ended) IS NOT NULL),
    transport TEXT NOT NULL CHECK (length(trim(transport)) > 0),
    disposition TEXT CHECK (
        disposition IS NULL OR disposition IN ({_DISPOSITION_VALUES_SQL})
    ),
    operator_intervened INTEGER NOT NULL DEFAULT 0 CHECK (operator_intervened IN (0, 1)),
    CHECK (
        (ended IS NULL AND disposition IS NULL)
        OR (ended IS NOT NULL AND disposition IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_call_per_case
ON calls(case_id) WHERE disposition IS NULL;

CREATE TABLE IF NOT EXISTS events (
    call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL CHECK (seq > 0),
    ts TEXT NOT NULL CHECK (datetime(ts) IS NOT NULL),
    type TEXT NOT NULL CHECK (length(trim(type)) > 0),
    state_before TEXT NOT NULL CHECK (json_valid(state_before)),
    state_after TEXT NOT NULL CHECK (json_valid(state_after)),
    redacted_reason TEXT NOT NULL CHECK (length(trim(redacted_reason)) > 0),
    PRIMARY KEY (call_id, seq)
);

CREATE TRIGGER IF NOT EXISTS enforce_events_monotonic_seq
BEFORE INSERT ON events
WHEN NEW.seq != COALESCE(
    (SELECT MAX(seq) + 1 FROM events WHERE call_id = NEW.call_id),
    1
)
BEGIN
    SELECT RAISE(ABORT, 'events.seq must be the next monotonic value for the call');
END;

CREATE TABLE IF NOT EXISTS tool_decisions (
    call_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    tool TEXT NOT NULL CHECK (length(trim(tool)) > 0),
    allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
    identity_state TEXT NOT NULL,
    promise_state TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    PRIMARY KEY (call_id, seq),
    FOREIGN KEY (call_id, seq) REFERENCES events(call_id, seq) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS promise_candidates (
    id TEXT NOT NULL,
    call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    caller_phrase TEXT NOT NULL CHECK (length(trim(caller_phrase)) > 0),
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    date_iso TEXT NOT NULL CHECK (date(date_iso) IS NOT NULL AND date_iso = date(date_iso)),
    revision INTEGER NOT NULL CHECK (revision > 0),
    read_back_ts TEXT CHECK (read_back_ts IS NULL OR datetime(read_back_ts) IS NOT NULL),
    confirmed_ts TEXT CHECK (confirmed_ts IS NULL OR datetime(confirmed_ts) IS NOT NULL),
    PRIMARY KEY (id, revision),
    UNIQUE (call_id, revision)
);

CREATE TABLE IF NOT EXISTS promises (
    call_id TEXT NOT NULL UNIQUE REFERENCES calls(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL,
    candidate_revision INTEGER NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    date_iso TEXT NOT NULL CHECK (date(date_iso) IS NOT NULL AND date_iso = date(date_iso)),
    idempotency_key TEXT NOT NULL UNIQUE,
    committed_ts TEXT NOT NULL CHECK (datetime(committed_ts) IS NOT NULL),
    PRIMARY KEY (candidate_id, candidate_revision),
    FOREIGN KEY (candidate_id, candidate_revision)
        REFERENCES promise_candidates(id, revision)
);

CREATE TABLE IF NOT EXISTS operator_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    ts TEXT NOT NULL CHECK (datetime(ts) IS NOT NULL),
    author TEXT NOT NULL CHECK (length(trim(author)) > 0),
    text TEXT NOT NULL CHECK (length(trim(text)) > 0)
);

CREATE TABLE IF NOT EXISTS demo_resets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL CHECK (datetime(ts) IS NOT NULL),
    governed_case_count INTEGER NOT NULL CHECK (governed_case_count >= 0),
    removed_call_count INTEGER NOT NULL CHECK (removed_call_count >= 0),
    redacted_reason TEXT NOT NULL CHECK (redacted_reason = 'sanctioned_demo_reset')
);

CREATE TRIGGER IF NOT EXISTS prevent_events_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_tool_decisions_update
BEFORE UPDATE ON tool_decisions
BEGIN
    SELECT RAISE(ABORT, 'tool_decisions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_promise_candidates_revision_update
BEFORE UPDATE ON promise_candidates
WHEN OLD.id != NEW.id
  OR OLD.call_id != NEW.call_id
  OR OLD.caller_phrase != NEW.caller_phrase
  OR OLD.amount_minor != NEW.amount_minor
  OR OLD.date_iso != NEW.date_iso
  OR OLD.revision != NEW.revision
BEGIN
    SELECT RAISE(ABORT, 'promise candidate revisions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_promises_update
BEFORE UPDATE ON promises
BEGIN
    SELECT RAISE(ABORT, 'promises are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_operator_notes_update
BEFORE UPDATE ON operator_notes
BEGIN
    SELECT RAISE(ABORT, 'operator_notes are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_demo_resets_update
BEFORE UPDATE ON demo_resets
BEGIN
    SELECT RAISE(ABORT, 'demo_resets are append-only');
END;

CREATE TRIGGER IF NOT EXISTS prevent_cases_delete
BEFORE DELETE ON cases
WHEN vachan_demo_reset_authorized() != 1
BEGIN
    SELECT RAISE(ABORT, 'cases are append-only outside sanctioned reset');
END;

CREATE TRIGGER IF NOT EXISTS prevent_calls_delete
BEFORE DELETE ON calls
WHEN vachan_demo_reset_authorized() != 1
BEGIN
    SELECT RAISE(ABORT, 'calls are append-only outside sanctioned reset');
END;

CREATE TRIGGER IF NOT EXISTS prevent_events_delete
BEFORE DELETE ON events
WHEN vachan_demo_reset_authorized() != 1
BEGIN
    SELECT RAISE(ABORT, 'events are append-only outside sanctioned reset');
END;

CREATE TRIGGER IF NOT EXISTS prevent_tool_decisions_delete
BEFORE DELETE ON tool_decisions
WHEN vachan_demo_reset_authorized() != 1
BEGIN
    SELECT RAISE(ABORT, 'tool_decisions are append-only outside sanctioned reset');
END;

CREATE TRIGGER IF NOT EXISTS prevent_promise_candidates_delete
BEFORE DELETE ON promise_candidates
WHEN vachan_demo_reset_authorized() != 1
BEGIN
    SELECT RAISE(ABORT, 'promise candidate revisions are append-only outside sanctioned reset');
END;

CREATE TRIGGER IF NOT EXISTS prevent_promises_delete
BEFORE DELETE ON promises
WHEN vachan_demo_reset_authorized() != 1
BEGIN
    SELECT RAISE(ABORT, 'promises are append-only outside sanctioned reset');
END;

CREATE TRIGGER IF NOT EXISTS prevent_operator_notes_delete
BEFORE DELETE ON operator_notes
WHEN vachan_demo_reset_authorized() != 1
BEGIN
    SELECT RAISE(ABORT, 'operator_notes are append-only outside sanctioned reset');
END;

CREATE TRIGGER IF NOT EXISTS prevent_demo_resets_delete
BEFORE DELETE ON demo_resets
BEGIN
    SELECT RAISE(ABORT, 'demo_resets are append-only');
END;
"""


class ActiveCallExists(RuntimeError):
    """Demo reset was refused because at least one call is still active."""


def connect_database(path: str | Path = "vachan.db") -> sqlite3.Connection:
    """Open a configured SQLite connection without creating any secret output."""

    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if str(path) != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    return connection


def migrate_schema(connection: sqlite3.Connection) -> None:
    """Idempotently apply the additive schema and record ``user_version``."""

    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database user_version {current_version} is newer than supported {SCHEMA_VERSION}"
        )

    # Trigger evaluation fails closed even before an EvidenceLedger is
    # constructed. The ledger replaces this function with its private,
    # connection-scoped authorization callback.
    connection.create_function("vachan_demo_reset_authorized", 0, lambda: 0)
    connection.executescript(SCHEMA_SQL)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def derive_idempotency_key(candidate_id: str, revision: int) -> str:
    """Return the frozen candidate/revision key used by ``promises``."""

    normalized_id = candidate_id.strip()
    if not normalized_id:
        raise ValueError("candidate_id must not be empty")
    if revision < 1:
        raise ValueError("revision must be positive")
    return f"{normalized_id}:{revision}"


def _iso_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("ledger timestamps must be timezone-aware")
    return value.isoformat()


def _snapshot_json(snapshot: StateSnapshot) -> str:
    return json.dumps(
        {
            "call": snapshot.call.value,
            "identity": snapshot.identity.value,
            "promise": snapshot.promise.value,
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _next_event_sequence(connection: sqlite3.Connection, call_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE call_id = ?",
        (call_id,),
    ).fetchone()
    return int(row[0])


def _insert_event_row(
    connection: sqlite3.Connection,
    *,
    call_id: str,
    seq: int,
    ts: datetime,
    event_type: str,
    state_before: StateSnapshot,
    state_after: StateSnapshot,
    redacted_reason: str,
) -> None:
    connection.execute(
        """
        INSERT INTO events (
            call_id, seq, ts, type, state_before, state_after, redacted_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            call_id,
            seq,
            _iso_timestamp(ts),
            event_type,
            _snapshot_json(state_before),
            _snapshot_json(state_after),
            redacted_reason,
        ),
    )


@contextmanager
def _immediate_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    else:
        connection.execute("COMMIT")


class EvidenceLedger:
    """Single-process SQLite repository with serialized evidence writes."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self._write_lock = asyncio.Lock()
        self._demo_reset_authorized = False
        self.connection.create_function(
            "vachan_demo_reset_authorized",
            0,
            lambda: int(self._demo_reset_authorized),
        )

    @contextmanager
    def _authorize_demo_reset(self) -> Iterator[None]:
        """Open the reset-only deletion window on this connection synchronously."""

        if self._demo_reset_authorized:
            raise RuntimeError("demo reset authorization is not re-entrant")
        self._demo_reset_authorized = True
        try:
            yield
        finally:
            self._demo_reset_authorized = False

    @classmethod
    def open(cls, path: str | Path = "vachan.db") -> EvidenceLedger:
        """Open and migrate a ledger."""

        connection = connect_database(path)
        migrate_schema(connection)
        return cls(connection)

    async def append_event(
        self,
        *,
        call_id: str,
        ts: datetime,
        event_type: LedgerEventType | str,
        state_before: StateSnapshot,
        state_after: StateSnapshot,
        redacted_reason: str,
    ) -> int:
        """Allocate and append the next call-local sequence atomically."""

        async with self._write_lock:
            _, seq = self.mutate_with_event(
                call_id=call_id,
                ts=ts,
                event_type=event_type,
                state_before=state_before,
                state_after=state_after,
                redacted_reason=redacted_reason,
                mutation=lambda: None,
            )
        return seq

    def mutate_with_event(
        self,
        *,
        call_id: str,
        ts: datetime,
        event_type: LedgerEventType | str,
        state_before: StateSnapshot,
        state_after: StateSnapshot,
        redacted_reason: str,
        mutation: Callable[[], MutationT],
    ) -> tuple[MutationT, int]:
        """Commit one synchronous domain mutation and its evidence together.

        This boundary deliberately contains no ``await``. Callers use it only
        after their authorization recheck, so neither state nor another task
        can interleave between the domain write and append-only evidence.
        """

        event_name = event_type.value if isinstance(event_type, LedgerEventType) else event_type
        if not event_name.strip():
            raise ValueError("event_type must not be empty")
        if not redacted_reason.strip():
            raise ValueError("redacted_reason must not be empty")

        with _immediate_transaction(self.connection):
            result = mutation()
            seq = _next_event_sequence(self.connection, call_id)
            _insert_event_row(
                self.connection,
                call_id=call_id,
                seq=seq,
                ts=ts,
                event_type=event_name,
                state_before=state_before,
                state_after=state_after,
                redacted_reason=redacted_reason,
            )
        return result, seq

    async def set_ended_operator(
        self,
        *,
        call_id: str,
        ts: datetime,
        reason: str,
        state: StateSnapshot,
    ) -> int:
        """Atomically persist the operator disposition and its final evidence."""

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("operator end reason must not be empty")
        if state.call.value != "ENDED":
            raise ValueError("operator end state must be ENDED")

        async with self._write_lock:
            with _immediate_transaction(self.connection):
                call = self.connection.execute(
                    "SELECT disposition FROM calls WHERE id = ?",
                    (call_id,),
                ).fetchone()
                if call is None:
                    raise LookupError("active call does not exist")
                if call["disposition"] is not None:
                    raise RuntimeError("call already has a terminal disposition")

                seq = _next_event_sequence(self.connection, call_id)
                _insert_event_row(
                    self.connection,
                    call_id=call_id,
                    seq=seq,
                    ts=ts,
                    event_type=LedgerEventType.DISPOSITION_SET.value,
                    state_before=state,
                    state_after=state,
                    redacted_reason=f"operator_end:{normalized_reason}",
                )
                updated = self.connection.execute(
                    """
                    UPDATE calls
                    SET ended = ?, disposition = ?, operator_intervened = 1
                    WHERE id = ? AND disposition IS NULL
                    """,
                    (
                        _iso_timestamp(ts),
                        Disposition.ENDED_OPERATOR.value,
                        call_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("operator ending lost its active-call race")
        return seq

    async def append_tool_decision(
        self,
        *,
        call_id: str,
        ts: datetime,
        decision: ToolDecision,
        state: StateSnapshot,
    ) -> int:
        """Atomically append one decision event and its typed detail row."""

        expected_states = (
            state.call.value,
            state.identity.value,
            state.promise.value,
        )
        decision_states = (
            decision.call_state,
            decision.identity_state,
            decision.promise_state,
        )
        if decision_states != expected_states:
            raise ValueError("tool decision states must match the authoritative snapshot")

        redacted_reason = (
            f"tool_allowed:{decision.tool.value}"
            if decision.allowed
            else f"tool_denied:{decision.tool.value}"
        )
        async with self._write_lock:
            with _immediate_transaction(self.connection):
                seq = _next_event_sequence(self.connection, call_id)
                _insert_event_row(
                    self.connection,
                    call_id=call_id,
                    seq=seq,
                    ts=ts,
                    event_type=LedgerEventType.TOOL_DECISION.value,
                    state_before=state,
                    state_after=state,
                    redacted_reason=redacted_reason,
                )
                self.connection.execute(
                    """
                    INSERT INTO tool_decisions (
                        call_id, seq, tool, allowed, identity_state, promise_state, reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        seq,
                        decision.tool.value,
                        decision.allowed,
                        decision.identity_state,
                        decision.promise_state,
                        decision.reason,
                    ),
                )
        return seq

    async def commit_promise(
        self,
        *,
        call_id: str,
        candidate_id: str,
        revision: int,
        amount_minor: int,
        date_iso: str,
        committed_ts: datetime,
    ) -> str:
        """Insert one committed promise and return its deterministic key."""

        idempotency_key = derive_idempotency_key(candidate_id, revision)
        async with self._write_lock:
            with _immediate_transaction(self.connection):
                self.connection.execute(
                    """
                    INSERT INTO promises (
                        call_id, candidate_id, candidate_revision, amount_minor,
                        date_iso, idempotency_key, committed_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        call_id,
                        candidate_id,
                        revision,
                        amount_minor,
                        date_iso,
                        idempotency_key,
                        _iso_timestamp(committed_ts),
                    ),
                )
        return idempotency_key

    def replace_demo_cases(
        self,
        cases: Sequence[MockCaseSeed],
        *,
        demo_time_anchor: datetime,
    ) -> None:
        """Implement the sanctioned reset for governed demo rows only."""

        anchor = _iso_timestamp(demo_time_anchor)
        with self._authorize_demo_reset(), _immediate_transaction(self.connection):
            active_call = self.connection.execute(
                "SELECT 1 FROM calls WHERE disposition IS NULL LIMIT 1"
            ).fetchone()
            if active_call is not None:
                raise ActiveCallExists("demo reset is unavailable during an active call")

            governed_case_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM cases WHERE mock_label = ?",
                    (DEMO_MOCK_LABEL,),
                ).fetchone()[0]
            )
            removed_call_count = int(
                self.connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM calls
                    JOIN cases ON cases.id = calls.case_id
                    WHERE cases.mock_label = ?
                    """,
                    (DEMO_MOCK_LABEL,),
                ).fetchone()[0]
            )

            self.connection.execute(
                "DELETE FROM cases WHERE mock_label = ?",
                (DEMO_MOCK_LABEL,),
            )
            for case in cases:
                emi_schedule_json = json.dumps(
                    [
                        {
                            "due_date": installment.due_date.isoformat(),
                            "amount_minor": installment.amount_minor,
                            "status": installment.status,
                        }
                        for installment in case.account.emi_schedule
                    ],
                    separators=(",", ":"),
                    sort_keys=True,
                )
                self.connection.execute(
                    """
                    INSERT INTO cases (
                        id, name, eligibility, contact_cap_remaining, mock_label,
                        verification_birth_day, verification_birth_month,
                        verification_reference_last4, lender_name, outstanding_minor,
                        emi_schedule_json, demo_time_anchor
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case.case_id,
                        case.borrower_display_name,
                        case.eligible,
                        case.contact_cap_remaining,
                        case.mock_data_label,
                        case.verification.birth_day,
                        case.verification.birth_month,
                        case.verification.reference_last4,
                        case.account.lender_name,
                        case.account.outstanding_minor,
                        emi_schedule_json,
                        anchor,
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO demo_resets (
                    ts, governed_case_count, removed_call_count, redacted_reason
                ) VALUES (?, ?, ?, 'sanctioned_demo_reset')
                """,
                (
                    datetime.now(UTC).isoformat(),
                    governed_case_count,
                    removed_call_count,
                ),
            )

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self.connection.close()
