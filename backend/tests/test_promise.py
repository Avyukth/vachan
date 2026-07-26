"""Promise normalization and event-sourced lifecycle tests."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from app.db import EvidenceLedger
from app.promise import (
    AmbiguousAmountError,
    AmbiguousDateError,
    InvalidAmountError,
    InvalidPromiseDateError,
    PromiseAlreadyCommitted,
    PromiseCandidate,
    PromiseEngine,
    PromiseEvent,
    PromiseEventType,
    PromiseFlowError,
    SQLitePromiseRepository,
    expected_idempotency_key,
    normalize_amount_minor,
    normalize_promise_date,
    render_promise_read_back,
)
from app.seeds import DEMO_TIME_ANCHOR
from app.states import PromiseState

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("phrase", "expected_minor"),
    [
        ("pandrah sau", 150_000),
        ("dedh hazaar", 150_000),
        ("ek hazaar paanchas", 105_000),
        ("paanch sau", 50_000),
        ("1500", 150_000),
        ("Rs 1,500", 150_000),
        ("पंद्रह सौ रुपये", 150_000),
    ],
)
def test_amount_vectors_normalize_to_integer_paise(
    phrase: str,
    expected_minor: int,
) -> None:
    assert normalize_amount_minor(phrase) == expected_minor


@pytest.mark.parametrize("phrase", ["1.5k", "1.5 k", "agle 1k", ""])
def test_ambiguous_or_unsupported_amounts_fail_closed(phrase: str) -> None:
    error = (
        AmbiguousAmountError if phrase and ("." in phrase or "k" in phrase) else InvalidAmountError
    )
    with pytest.raises(error):
        normalize_amount_minor(phrase)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("Friday", date(2026, 7, 31)),
        ("on Friday", date(2026, 7, 31)),
        ("this Friday", date(2026, 7, 31)),
        ("Friday ko", date(2026, 7, 31)),
        ("Friday को", date(2026, 7, 31)),
        ("shukravaar", date(2026, 7, 31)),
        ("shukravaar ko", date(2026, 7, 31)),
        ("शुक्रवार", date(2026, 7, 31)),
        ("शुक्रवार को", date(2026, 7, 31)),
        ("kal", date(2026, 7, 27)),
        ("31 July", date(2026, 7, 31)),
        ("31/07/2026", date(2026, 7, 31)),
        ("2026-07-31", date(2026, 7, 31)),
    ],
)
def test_date_vectors_use_seeded_asia_kolkata_clock(
    phrase: str,
    expected: date,
) -> None:
    assert normalize_promise_date(phrase, demo_time_anchor=DEMO_TIME_ANCHOR) == expected


def test_ambiguous_date_is_never_guessed() -> None:
    with pytest.raises(AmbiguousDateError):
        normalize_promise_date("agle hafte", demo_time_anchor=DEMO_TIME_ANCHOR)


@pytest.mark.parametrize(
    "phrase",
    [
        "30 February",
        "1 July",
        "not-a-date",
        "next Friday",
        "Friday after lunch",
        "this Friday ko",
    ],
)
def test_impossible_past_or_unknown_dates_are_rejected(phrase: str) -> None:
    with pytest.raises(InvalidPromiseDateError):
        normalize_promise_date(phrase, demo_time_anchor=DEMO_TIME_ANCHOR)


def test_date_normalization_rejects_wall_time_without_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_promise_date(
            "Friday",
            demo_time_anchor=datetime(2026, 7, 26, 12, 0),
        )


def test_read_back_contains_words_digits_weekday_and_absolute_date() -> None:
    candidate = PromiseCandidate(
        candidate_id="candidate-001",
        call_id="call-001",
        caller_phrase="pandrah sau Friday",
        amount_minor=150_000,
        date_iso=date(2026, 7, 31),
        revision=1,
    )

    read_back = render_promise_read_back(candidate)

    assert "Pandrah sau rupaye" in read_back
    assert "1-5-0-0" in read_back
    assert "shukravaar" in read_back
    assert "31 July 2026" in read_back
    assert read_back.endswith("Sahi hai?")


def test_events_are_redacted_and_contain_no_amount_date_or_caller_phrase() -> None:
    event_fields = set(PromiseEvent.__dataclass_fields__)

    assert event_fields == {
        "event_type",
        "candidate_id",
        "revision",
        "state_before",
        "state_after",
        "redacted_reason",
    }
    assert not {"amount_minor", "date_iso", "caller_phrase", "read_back_text"} & event_fields


def _start_call(connection: sqlite3.Connection, call_id: str = "call-promise-001") -> None:
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, 'case-rakesh-001', ?, 'streaming_pcm16_ws')
        """,
        (call_id, NOW.isoformat()),
    )


def _engine(
    connection: sqlite3.Connection,
    *,
    call_id: str = "call-promise-001",
) -> tuple[PromiseEngine, list[PromiseEvent]]:
    events: list[PromiseEvent] = []
    engine = PromiseEngine(
        call_id=call_id,
        repository=SQLitePromiseRepository(EvidenceLedger(connection)),
        demo_time_anchor=DEMO_TIME_ANCHOR,
        clock=lambda: NOW,
        record_event=events.append,
    )
    return engine, events


def test_candidate_read_back_explicit_yes_commits_exactly_once(
    db_connection: sqlite3.Connection,
) -> None:
    _start_call(db_connection)
    engine, events = _engine(db_connection)

    async def exercise() -> None:
        candidate = await engine.create_candidate(
            caller_phrase="pandrah sau, Friday",
            amount="pandrah sau",
            date_phrase="Friday",
        )
        assert expected_idempotency_key(candidate) == "call-promise-001-promise:1"
        await engine.read_back()
        outcome = await engine.respond_to_read_back(explicit_affirmative=True)
        assert outcome is not None
        assert outcome.inserted is True
        assert outcome.idempotency_key == expected_idempotency_key(candidate)

    asyncio.run(exercise())

    assert engine.state is PromiseState.COMMITTED
    assert [event.event_type for event in events] == [
        PromiseEventType.CANDIDATE_CREATED,
        PromiseEventType.READ_BACK,
        PromiseEventType.EXPLICITLY_CONFIRMED,
        PromiseEventType.COMMITTED,
    ]
    assert db_connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 1
    assert db_connection.execute("SELECT amount_minor FROM promises").fetchone()[0] == 150_000


def test_correction_appends_revision_and_forces_second_read_back(
    db_connection: sqlite3.Connection,
) -> None:
    _start_call(db_connection)
    engine, events = _engine(db_connection)

    async def exercise() -> None:
        await engine.create_candidate(
            caller_phrase="pandrah sau, Friday",
            amount="1500",
            date_phrase="Friday",
        )
        await engine.read_back()
        corrected = await engine.correct_candidate(
            caller_phrase="nahi, ek hazaar paanchas",
            amount="ek hazaar paanchas",
        )
        assert corrected.revision == 2
        assert corrected.amount_minor == 105_000
        with pytest.raises(PromiseFlowError, match="only after read-back"):
            await engine.respond_to_read_back(explicit_affirmative=True)
        second_read_back = await engine.read_back()
        assert "1-0-5-0" in second_read_back
        await engine.respond_to_read_back(explicit_affirmative=True)

    asyncio.run(exercise())

    revisions = db_connection.execute(
        """
        SELECT revision, amount_minor, read_back_ts, confirmed_ts
        FROM promise_candidates ORDER BY revision
        """
    ).fetchall()
    assert [(row["revision"], row["amount_minor"]) for row in revisions] == [
        (1, 150_000),
        (2, 105_000),
    ]
    assert revisions[0]["confirmed_ts"] is None
    assert revisions[1]["read_back_ts"] is not None
    assert revisions[1]["confirmed_ts"] is not None
    promise = db_connection.execute(
        "SELECT candidate_revision, amount_minor FROM promises"
    ).fetchone()
    assert tuple(promise) == (2, 105_000)
    assert PromiseEventType.CANDIDATE_CORRECTED in {event.event_type for event in events}


def test_no_at_read_back_abandons_without_promise_row(
    db_connection: sqlite3.Connection,
) -> None:
    _start_call(db_connection)
    engine, events = _engine(db_connection)

    async def exercise() -> None:
        await engine.create_candidate(
            caller_phrase="1500 Friday",
            amount=1500,
            date_phrase="Friday",
        )
        await engine.read_back()
        result = await engine.respond_to_read_back(explicit_affirmative=False)
        assert result is None

    asyncio.run(exercise())

    assert engine.state is PromiseState.ABANDONED
    assert events[-1].event_type is PromiseEventType.ABANDONED
    assert db_connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 0


def test_duplicate_affirmative_is_suppressed_and_logged(
    db_connection: sqlite3.Connection,
) -> None:
    _start_call(db_connection)
    engine, events = _engine(db_connection)

    async def exercise() -> None:
        await engine.create_candidate(
            caller_phrase="1500 Friday",
            amount=1500,
            date_phrase="Friday",
        )
        await engine.read_back()
        first = await engine.respond_to_read_back(explicit_affirmative=True)
        duplicate = await engine.respond_to_read_back(explicit_affirmative=True)
        assert first is not None and first.inserted is True
        assert duplicate is not None and duplicate.inserted is False
        assert first.idempotency_key == duplicate.idempotency_key

    asyncio.run(exercise())

    assert db_connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 1
    assert events[-1].event_type is PromiseEventType.DUPLICATE_SUPPRESSED
    assert events[-1].redacted_reason == "duplicate_affirmative_suppressed"


def test_call_ending_before_confirmation_abandons_without_write(
    db_connection: sqlite3.Connection,
) -> None:
    _start_call(db_connection)
    engine, _ = _engine(db_connection)

    async def exercise() -> None:
        await engine.create_candidate(
            caller_phrase="1500 Friday",
            amount=1500,
            date_phrase="Friday",
        )
        await engine.abandon()

    asyncio.run(exercise())

    assert engine.state is PromiseState.ABANDONED
    assert db_connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 0


def test_repository_rejects_different_committed_revision_for_same_call(
    db_connection: sqlite3.Connection,
) -> None:
    _start_call(db_connection)
    repository = SQLitePromiseRepository(EvidenceLedger(db_connection))
    first = PromiseCandidate(
        candidate_id="call-promise-001-promise",
        call_id="call-promise-001",
        caller_phrase="1500 Friday",
        amount_minor=150_000,
        date_iso=date(2026, 7, 31),
        revision=1,
    )
    corrected = PromiseCandidate(
        candidate_id=first.candidate_id,
        call_id=first.call_id,
        caller_phrase="1050 Friday",
        amount_minor=105_000,
        date_iso=first.date_iso,
        revision=2,
    )

    async def exercise() -> None:
        await repository.save_candidate(first)
        await repository.mark_read_back(first, ts=NOW)
        await repository.mark_confirmed(first, ts=NOW + timedelta(seconds=1))
        await repository.commit(first, ts=NOW + timedelta(seconds=2))
        await repository.save_candidate(corrected)
        await repository.mark_read_back(corrected, ts=NOW + timedelta(seconds=3))
        await repository.mark_confirmed(corrected, ts=NOW + timedelta(seconds=4))
        with pytest.raises(PromiseAlreadyCommitted):
            await repository.commit(corrected, ts=NOW + timedelta(seconds=5))

    asyncio.run(exercise())

    assert db_connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 1
