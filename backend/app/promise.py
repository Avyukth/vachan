"""Promise candidate normalization, read-back, and idempotent commit logic.

The language model may propose an amount, date, or confirmation, but this
module owns every resulting value and state change.  Normalization is
deterministic against the seeded demo clock, corrections are new immutable
candidate revisions, and a promise reaches SQLite only after a read-back and
an explicit affirmative.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import sqlite3
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from app.contracts import LedgerEventType
from app.db import EvidenceLedger, derive_idempotency_key
from app.seeds import DEMO_TIME_ZONE
from app.states import PromiseState, validate_transition


class PromiseNormalizationError(ValueError):
    """Base class for a caller value that code cannot normalize safely."""


class AmbiguousAmountError(PromiseNormalizationError):
    """An amount uses shorthand that Vachan deliberately refuses to guess."""


class InvalidAmountError(PromiseNormalizationError):
    """An amount is absent, unsupported, or not a positive whole rupee value."""


class AmbiguousDateError(PromiseNormalizationError):
    """A date phrase does not identify one calendar date."""


class InvalidPromiseDateError(PromiseNormalizationError):
    """A date is impossible, unsupported, or before the seeded demo date."""


class PromiseFlowError(RuntimeError):
    """Base class for an invalid promise lifecycle operation."""


class PromiseAlreadyCommitted(PromiseFlowError):
    """A call already owns a different committed candidate revision."""


class PromisePersistenceError(PromiseFlowError):
    """Candidate persistence did not match the engine's authoritative state."""


_CURRENCY_MARKERS = frozenset(
    {
        "rs",
        "rupee",
        "rupees",
        "rupaya",
        "rupaye",
        "rupaiye",
        "रुपया",
        "रुपए",
        "रुपये",
    }
)

_NUMBER_WORDS: Mapping[str, int] = {
    "zero": 0,
    "shunya": 0,
    "शून्य": 0,
    "one": 1,
    "ek": 1,
    "एक": 1,
    "two": 2,
    "do": 2,
    "दो": 2,
    "three": 3,
    "teen": 3,
    "तीन": 3,
    "four": 4,
    "char": 4,
    "chaar": 4,
    "चार": 4,
    "five": 5,
    "paanch": 5,
    "panch": 5,
    "पाँच": 5,
    "पांच": 5,
    "six": 6,
    "chhe": 6,
    "छह": 6,
    "seven": 7,
    "saat": 7,
    "सात": 7,
    "eight": 8,
    "aath": 8,
    "आठ": 8,
    "nine": 9,
    "nau": 9,
    "नौ": 9,
    "ten": 10,
    "das": 10,
    "दस": 10,
    "eleven": 11,
    "gyarah": 11,
    "ग्यारह": 11,
    "twelve": 12,
    "baarah": 12,
    "barah": 12,
    "बारह": 12,
    "thirteen": 13,
    "terah": 13,
    "तेरह": 13,
    "fourteen": 14,
    "chaudah": 14,
    "चौदह": 14,
    "fifteen": 15,
    "pandrah": 15,
    "पंद्रह": 15,
    "sixteen": 16,
    "solah": 16,
    "सोलह": 16,
    "seventeen": 17,
    "satrah": 17,
    "सत्रह": 17,
    "eighteen": 18,
    "atharah": 18,
    "अठारह": 18,
    "nineteen": 19,
    "unnees": 19,
    "उन्नीस": 19,
    "twenty": 20,
    "bees": 20,
    "बीस": 20,
    "thirty": 30,
    "tees": 30,
    "तीस": 30,
    "forty": 40,
    "chaalis": 40,
    "चालीस": 40,
    "fifty": 50,
    "pachaas": 50,
    "paanchas": 50,
    "पचास": 50,
    "sixty": 60,
    "saath": 60,
    "साठ": 60,
    "seventy": 70,
    "sattar": 70,
    "सत्तर": 70,
    "eighty": 80,
    "assi": 80,
    "अस्सी": 80,
    "ninety": 90,
    "nabbe": 90,
    "नब्बे": 90,
}

_SCALES: Mapping[str, int] = {
    "hundred": 100,
    "sau": 100,
    "सौ": 100,
    "thousand": 1_000,
    "hazaar": 1_000,
    "hazar": 1_000,
    "हज़ार": 1_000,
    "हजार": 1_000,
    "lakh": 100_000,
    "लाख": 100_000,
}

_MONTHS: Mapping[str, int] = {
    "january": 1,
    "jan": 1,
    "janavari": 1,
    "जनवरी": 1,
    "february": 2,
    "feb": 2,
    "faravari": 2,
    "फरवरी": 2,
    "march": 3,
    "मार्च": 3,
    "april": 4,
    "अप्रैल": 4,
    "may": 5,
    "mai": 5,
    "मई": 5,
    "june": 6,
    "jun": 6,
    "जून": 6,
    "july": 7,
    "julai": 7,
    "जुलाई": 7,
    "august": 8,
    "agast": 8,
    "अगस्त": 8,
    "september": 9,
    "sitambar": 9,
    "सितंबर": 9,
    "october": 10,
    "aktubar": 10,
    "अक्टूबर": 10,
    "november": 11,
    "navambar": 11,
    "नवंबर": 11,
    "december": 12,
    "disambar": 12,
    "दिसंबर": 12,
}

_WEEKDAYS: Mapping[str, int] = {
    "monday": 0,
    "somvaar": 0,
    "somvar": 0,
    "सोमवार": 0,
    "tuesday": 1,
    "mangalvaar": 1,
    "mangalvar": 1,
    "मंगलवार": 1,
    "wednesday": 2,
    "budhvaar": 2,
    "budhvar": 2,
    "बुधवार": 2,
    "thursday": 3,
    "guruvaar": 3,
    "guruvar": 3,
    "गुरुवार": 3,
    "friday": 4,
    "shukravaar": 4,
    "shukravar": 4,
    "शुक्रवार": 4,
    "saturday": 5,
    "shanivaar": 5,
    "shanivar": 5,
    "शनिवार": 5,
    "sunday": 6,
    "ravivaar": 6,
    "ravivar": 6,
    "रविवार": 6,
}

_WEEKDAY_READ_BACK = (
    "somvaar",
    "mangalvaar",
    "budhvaar",
    "guruvaar",
    "shukravaar",
    "shanivaar",
    "ravivaar",
)

_AMBIGUOUS_DATES = frozenset(
    {
        "next week",
        "agle hafte",
        "agale hafte",
        "अगले हफ्ते",
        "अगले सप्ताह",
    }
)

_HINDI_SMALL = (
    "shunya",
    "ek",
    "do",
    "teen",
    "chaar",
    "paanch",
    "chhe",
    "saat",
    "aath",
    "nau",
    "das",
    "gyarah",
    "baarah",
    "terah",
    "chaudah",
    "pandrah",
    "solah",
    "satrah",
    "atharah",
    "unnees",
)

_HINDI_TENS = {
    20: "bees",
    30: "tees",
    40: "chaalis",
    50: "pachaas",
    60: "saath",
    70: "sattar",
    80: "assi",
    90: "nabbe",
}


def _normalized_words(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("₹", " rs ")
    return re.sub(r"[^\w\u0900-\u097f]+", " ", normalized).split()


def normalize_amount_minor(value: str | int) -> int:
    """Parse a whole-rupee caller amount and return integer paise.

    Compact decimal shorthand such as ``1.5k`` is rejected deliberately:
    collections writes are not a place to infer what a shorthand meant.
    """

    if isinstance(value, bool):
        raise InvalidAmountError("amount must be a positive whole-rupee value")
    if isinstance(value, int):
        if value <= 0:
            raise InvalidAmountError("amount must be positive")
        return value * 100

    raw = unicodedata.normalize("NFKC", value).casefold().strip()
    if not raw:
        raise InvalidAmountError("amount must not be empty")
    if re.search(r"\d+\s*(?:\.\d+|k\b)", raw):
        raise AmbiguousAmountError("compact or decimal amount shorthand requires clarification")

    words = [word for word in _normalized_words(raw) if word not in _CURRENCY_MARKERS]
    if not words:
        raise InvalidAmountError("amount contains no supported number")

    compact_digits = "".join(words).replace(",", "")
    if compact_digits.isdecimal():
        rupees = int(compact_digits)
        if rupees <= 0:
            raise InvalidAmountError("amount must be positive")
        return rupees * 100

    # "dedh" is accepted only as the reviewed 1.5-thousand idiom.  Treating it
    # as a general fractional operator would silently guess unsupported values.
    if words in (["dedh", "hazaar"], ["डेढ़", "हजार"], ["डेढ़", "हज़ार"]):
        return 1_500 * 100

    current = 0
    total = 0
    for word in words:
        if word in _NUMBER_WORDS:
            current += _NUMBER_WORDS[word]
            continue
        scale = _SCALES.get(word)
        if scale is None:
            raise InvalidAmountError("amount contains an unsupported number word")
        if scale == 100:
            current = max(current, 1) * scale
        else:
            total += max(current, 1) * scale
            current = 0

    rupees = total + current
    if rupees <= 0:
        raise InvalidAmountError("amount must be positive")
    return rupees * 100


def _local_anchor_date(anchor: datetime) -> date:
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        raise ValueError("demo_time_anchor must be timezone-aware")
    return anchor.astimezone(DEMO_TIME_ZONE).date()


def _validate_candidate_date(candidate: date, anchor_date: date) -> date:
    if candidate < anchor_date:
        raise InvalidPromiseDateError("promise date must not be in the past")
    return candidate


def normalize_promise_date(phrase: str, *, demo_time_anchor: datetime) -> date:
    """Resolve one date against the seeded Asia/Kolkata demo clock."""

    raw = unicodedata.normalize("NFKC", phrase).casefold().strip()
    words = " ".join(_normalized_words(raw))
    if not words:
        raise InvalidPromiseDateError("promise date must not be empty")
    if words in _AMBIGUOUS_DATES:
        raise AmbiguousDateError("date phrase identifies a range rather than one day")

    anchor_date = _local_anchor_date(demo_time_anchor)
    if words in {"tomorrow", "kal", "कल"}:
        return anchor_date + timedelta(days=1)

    weekday_words = words
    tokens = words.split()
    if len(tokens) == 2 and tokens[0] in {"on", "this"}:
        weekday_words = tokens[1]
    elif len(tokens) == 2 and tokens[1] in {"ko", "को"}:
        weekday_words = tokens[0]

    weekday = _WEEKDAYS.get(weekday_words)
    if weekday is not None:
        days_ahead = (weekday - anchor_date.weekday()) % 7 or 7
        return anchor_date + timedelta(days=days_ahead)

    try:
        iso_candidate = date.fromisoformat(raw)
    except ValueError:
        iso_candidate = None
    if iso_candidate is not None:
        return _validate_candidate_date(iso_candidate, anchor_date)

    numeric_match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", raw)
    if numeric_match is not None:
        try:
            numeric_candidate = date(
                int(numeric_match.group(3)),
                int(numeric_match.group(2)),
                int(numeric_match.group(1)),
            )
        except ValueError as error:
            raise InvalidPromiseDateError("promise date is not a real calendar day") from error
        return _validate_candidate_date(numeric_candidate, anchor_date)

    absolute_match = re.fullmatch(r"(\d{1,2})\s+([^\s]+)(?:\s+(\d{4}))?", words)
    if absolute_match is None:
        raise InvalidPromiseDateError("date phrase is unsupported")
    month = _MONTHS.get(absolute_match.group(2))
    if month is None:
        raise InvalidPromiseDateError("date phrase contains an unsupported month")
    year = int(absolute_match.group(3) or anchor_date.year)
    try:
        absolute_candidate = date(year, month, int(absolute_match.group(1)))
    except ValueError as error:
        raise InvalidPromiseDateError("promise date is not a real calendar day") from error
    return _validate_candidate_date(absolute_candidate, anchor_date)


def _hindi_under_hundred(value: int) -> str:
    if value < 20:
        return _HINDI_SMALL[value]
    tens = value // 10 * 10
    remainder = value % 10
    return _HINDI_TENS[tens] if remainder == 0 else f"{_HINDI_TENS[tens]} {_HINDI_SMALL[remainder]}"


def amount_in_hindi_words(rupees: int) -> str:
    """Render deterministic Hindi-transliterated words for read-back."""

    if rupees <= 0 or rupees >= 10_000_000:
        raise InvalidAmountError("read-back amount is outside the supported demo range")
    if rupees < 100:
        return _hindi_under_hundred(rupees)
    if rupees < 2_000 and rupees % 100 == 0 and rupees // 100 < 20:
        return f"{_HINDI_SMALL[rupees // 100]} sau"

    parts: list[str] = []
    remainder = rupees
    if remainder >= 100_000:
        lakhs, remainder = divmod(remainder, 100_000)
        parts.append(f"{_hindi_under_hundred(lakhs)} lakh")
    if remainder >= 1_000:
        thousands, remainder = divmod(remainder, 1_000)
        parts.append(f"{_hindi_under_hundred(thousands)} hazaar")
    if remainder >= 100:
        hundreds, remainder = divmod(remainder, 100)
        parts.append(f"{_HINDI_SMALL[hundreds]} sau")
    if remainder:
        parts.append(_hindi_under_hundred(remainder))
    return " ".join(parts)


@dataclass(frozen=True, slots=True)
class PromiseCandidate:
    """One immutable normalized revision awaiting explicit confirmation."""

    candidate_id: str
    call_id: str
    caller_phrase: str
    amount_minor: int
    date_iso: date
    revision: int

    def __post_init__(self) -> None:
        if not self.candidate_id.strip() or not self.call_id.strip():
            raise ValueError("candidate_id and call_id must not be empty")
        if not self.caller_phrase.strip():
            raise ValueError("caller_phrase must not be empty")
        if self.amount_minor <= 0 or self.amount_minor % 100:
            raise InvalidAmountError("candidate amount must be positive whole rupees in paise")
        if self.revision < 1:
            raise ValueError("candidate revision must be positive")


def render_promise_read_back(candidate: PromiseCandidate) -> str:
    """Render words, digit-by-digit amount, weekday, and absolute date."""

    rupees = candidate.amount_minor // 100
    words = amount_in_hindi_words(rupees).capitalize()
    digits = "-".join(str(rupees))
    weekday = _WEEKDAY_READ_BACK[candidate.date_iso.weekday()]
    absolute_date = candidate.date_iso.strftime("%d %B %Y").lstrip("0")
    return f"{words} rupaye — {digits} — {weekday}, {absolute_date}. Sahi hai?"


class PromiseEventType(StrEnum):
    """Redacted lifecycle event names emitted by :class:`PromiseEngine`."""

    CANDIDATE_CREATED = LedgerEventType.PROMISE_CANDIDATE_CREATED.value
    CANDIDATE_CORRECTED = LedgerEventType.PROMISE_CANDIDATE_CORRECTED.value
    READ_BACK = LedgerEventType.PROMISE_READ_BACK.value
    EXPLICITLY_CONFIRMED = LedgerEventType.PROMISE_EXPLICITLY_CONFIRMED.value
    COMMITTED = LedgerEventType.PROMISE_COMMITTED.value
    ABANDONED = "PROMISE_ABANDONED"
    DUPLICATE_SUPPRESSED = "PROMISE_DUPLICATE_SUPPRESSED"


@dataclass(frozen=True, slots=True)
class PromiseEvent:
    """Safe-to-log evidence; amount, date, and caller phrase stay elsewhere."""

    event_type: PromiseEventType
    candidate_id: str
    revision: int
    state_before: PromiseState
    state_after: PromiseState
    redacted_reason: str


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    """Result of the one-per-call persistence boundary."""

    idempotency_key: str
    inserted: bool


class PromiseRepository(Protocol):
    """Persistence required by the deterministic promise engine."""

    async def save_candidate(self, candidate: PromiseCandidate) -> None: ...

    async def mark_read_back(self, candidate: PromiseCandidate, *, ts: datetime) -> None: ...

    async def mark_confirmed(self, candidate: PromiseCandidate, *, ts: datetime) -> None: ...

    async def commit(self, candidate: PromiseCandidate, *, ts: datetime) -> CommitOutcome: ...


EventRecorder = Callable[[PromiseEvent], Awaitable[None] | None]
Clock = Callable[[], datetime]


def _aware_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("promise timestamps must be timezone-aware")
    return value.isoformat()


class SQLitePromiseRepository:
    """Candidate revision storage plus idempotent use of ``EvidenceLedger``."""

    def __init__(self, ledger: EvidenceLedger) -> None:
        self._ledger = ledger
        self._connection = ledger.connection
        self._lock = asyncio.Lock()

    async def save_candidate(self, candidate: PromiseCandidate) -> None:
        async with self._lock:
            self._connection.execute(
                """
                INSERT INTO promise_candidates (
                    id, call_id, caller_phrase, amount_minor, date_iso, revision,
                    read_back_ts, confirmed_ts
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    candidate.candidate_id,
                    candidate.call_id,
                    candidate.caller_phrase,
                    candidate.amount_minor,
                    candidate.date_iso.isoformat(),
                    candidate.revision,
                ),
            )

    async def mark_read_back(self, candidate: PromiseCandidate, *, ts: datetime) -> None:
        async with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE promise_candidates
                SET read_back_ts = ?
                WHERE id = ? AND revision = ? AND read_back_ts IS NULL
                """,
                (
                    _aware_timestamp(ts),
                    candidate.candidate_id,
                    candidate.revision,
                ),
            )
        if cursor.rowcount != 1:
            raise PromisePersistenceError("candidate could not be marked read back exactly once")

    async def mark_confirmed(self, candidate: PromiseCandidate, *, ts: datetime) -> None:
        async with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE promise_candidates
                SET confirmed_ts = ?
                WHERE id = ? AND revision = ?
                  AND read_back_ts IS NOT NULL AND confirmed_ts IS NULL
                """,
                (
                    _aware_timestamp(ts),
                    candidate.candidate_id,
                    candidate.revision,
                ),
            )
        if cursor.rowcount != 1:
            raise PromisePersistenceError("candidate confirmation requires one persisted read-back")

    def _existing_commit(self, candidate: PromiseCandidate) -> CommitOutcome | None:
        row = self._connection.execute(
            """
            SELECT candidate_id, candidate_revision, idempotency_key
            FROM promises WHERE call_id = ?
            """,
            (candidate.call_id,),
        ).fetchone()
        if row is None:
            return None
        if (
            row["candidate_id"] != candidate.candidate_id
            or row["candidate_revision"] != candidate.revision
        ):
            raise PromiseAlreadyCommitted("a call may not commit a different candidate revision")
        return CommitOutcome(idempotency_key=str(row["idempotency_key"]), inserted=False)

    async def commit(self, candidate: PromiseCandidate, *, ts: datetime) -> CommitOutcome:
        async with self._lock:
            existing = self._existing_commit(candidate)
            if existing is not None:
                return existing
            try:
                key = await self._ledger.commit_promise(
                    call_id=candidate.call_id,
                    candidate_id=candidate.candidate_id,
                    revision=candidate.revision,
                    amount_minor=candidate.amount_minor,
                    date_iso=candidate.date_iso.isoformat(),
                    committed_ts=ts,
                )
            except sqlite3.IntegrityError:
                # A concurrent duplicate is safe only when it resolves to the
                # exact same candidate/revision.  Every other conflict fails.
                concurrent = self._existing_commit(candidate)
                if concurrent is None:
                    raise
                return concurrent
        return CommitOutcome(idempotency_key=key, inserted=True)


class PromiseEngine:
    """Call-scoped promise lifecycle with no model-owned transitions."""

    def __init__(
        self,
        *,
        call_id: str,
        repository: PromiseRepository,
        demo_time_anchor: datetime,
        clock: Clock,
        record_event: EventRecorder,
    ) -> None:
        if not call_id.strip():
            raise ValueError("call_id must not be empty")
        _local_anchor_date(demo_time_anchor)
        self.call_id = call_id
        self._repository = repository
        self._demo_time_anchor = demo_time_anchor
        self._clock = clock
        self._record_event = record_event
        self._state = PromiseState.NONE
        self._candidate: PromiseCandidate | None = None

    @property
    def state(self) -> PromiseState:
        return self._state

    @property
    def candidate(self) -> PromiseCandidate | None:
        return self._candidate

    async def _record(
        self,
        event_type: PromiseEventType,
        *,
        before: PromiseState,
        after: PromiseState,
        reason: str,
    ) -> None:
        candidate = self._candidate
        if candidate is None:
            raise PromiseFlowError("a promise event requires an active candidate")
        event = PromiseEvent(
            event_type=event_type,
            candidate_id=candidate.candidate_id,
            revision=candidate.revision,
            state_before=before,
            state_after=after,
            redacted_reason=reason,
        )
        result = self._record_event(event)
        if inspect.isawaitable(result):
            await result

    def _plan_transition(self, target: PromiseState) -> tuple[PromiseState, PromiseState]:
        before = self._state
        validate_transition(before, target)
        return before, target

    def _apply_transition(self, target: PromiseState) -> None:
        self._state = target

    async def create_candidate(
        self,
        *,
        caller_phrase: str,
        amount: str | int,
        date_phrase: str,
    ) -> PromiseCandidate:
        """Normalize and persist revision one without committing it."""

        if self._state is not PromiseState.NONE:
            raise PromiseFlowError("a call may create only one promise candidate lineage")
        candidate = PromiseCandidate(
            candidate_id=f"{self.call_id}-promise",
            call_id=self.call_id,
            caller_phrase=caller_phrase,
            amount_minor=normalize_amount_minor(amount),
            date_iso=normalize_promise_date(
                date_phrase,
                demo_time_anchor=self._demo_time_anchor,
            ),
            revision=1,
        )
        before, after = self._plan_transition(PromiseState.CANDIDATE)
        await self._repository.save_candidate(candidate)
        self._candidate = candidate
        self._apply_transition(after)
        await self._record(
            PromiseEventType.CANDIDATE_CREATED,
            before=before,
            after=after,
            reason="candidate_normalized",
        )
        return candidate

    async def correct_candidate(
        self,
        *,
        caller_phrase: str,
        amount: str | int | None = None,
        date_phrase: str | None = None,
    ) -> PromiseCandidate:
        """Append a revision and force that revision through another read-back."""

        previous = self._candidate
        if previous is None:
            raise PromiseFlowError("correction requires an existing candidate")
        if amount is None and date_phrase is None:
            raise PromiseFlowError("correction must change amount or date")

        candidate = PromiseCandidate(
            candidate_id=previous.candidate_id,
            call_id=previous.call_id,
            caller_phrase=caller_phrase,
            amount_minor=(
                previous.amount_minor if amount is None else normalize_amount_minor(amount)
            ),
            date_iso=(
                previous.date_iso
                if date_phrase is None
                else normalize_promise_date(
                    date_phrase,
                    demo_time_anchor=self._demo_time_anchor,
                )
            ),
            revision=previous.revision + 1,
        )
        before, after = self._plan_transition(PromiseState.CORRECTED)
        await self._repository.save_candidate(candidate)
        self._candidate = candidate
        self._apply_transition(after)
        await self._record(
            PromiseEventType.CANDIDATE_CORRECTED,
            before=before,
            after=after,
            reason="candidate_revision_appended",
        )
        return candidate

    async def read_back(self) -> str:
        """Persist the read-back fact before returning speakable reviewed text."""

        candidate = self._candidate
        if candidate is None:
            raise PromiseFlowError("read-back requires an existing candidate")
        before, after = self._plan_transition(PromiseState.READ_BACK)
        await self._repository.mark_read_back(candidate, ts=self._clock())
        self._apply_transition(after)
        await self._record(
            PromiseEventType.READ_BACK,
            before=before,
            after=after,
            reason="normalized_candidate_read_back",
        )
        return render_promise_read_back(candidate)

    async def respond_to_read_back(
        self,
        *,
        explicit_affirmative: bool,
    ) -> CommitOutcome | None:
        """Commit on explicit yes, abandon on no, and suppress duplicate yes."""

        candidate = self._candidate
        if candidate is None:
            raise PromiseFlowError("confirmation requires an existing candidate")

        if self._state is PromiseState.COMMITTED and explicit_affirmative:
            outcome = await self._repository.commit(candidate, ts=self._clock())
            await self._record(
                PromiseEventType.DUPLICATE_SUPPRESSED,
                before=PromiseState.COMMITTED,
                after=PromiseState.COMMITTED,
                reason="duplicate_affirmative_suppressed",
            )
            return outcome

        if self._state is not PromiseState.READ_BACK:
            raise PromiseFlowError("explicit confirmation is accepted only after read-back")

        if not explicit_affirmative:
            before, after = self._plan_transition(PromiseState.ABANDONED)
            self._apply_transition(after)
            await self._record(
                PromiseEventType.ABANDONED,
                before=before,
                after=after,
                reason="read_back_rejected",
            )
            return None

        confirmed_at = self._clock()
        before, after = self._plan_transition(PromiseState.CONFIRMED)
        await self._repository.mark_confirmed(candidate, ts=confirmed_at)
        self._apply_transition(after)
        await self._record(
            PromiseEventType.EXPLICITLY_CONFIRMED,
            before=before,
            after=after,
            reason="explicit_affirmative_recorded",
        )

        before, after = self._plan_transition(PromiseState.COMMITTED)
        outcome = await self._repository.commit(candidate, ts=self._clock())
        self._apply_transition(after)
        await self._record(
            PromiseEventType.COMMITTED,
            before=before,
            after=after,
            reason=(
                "promise_committed" if outcome.inserted else "duplicate_affirmative_suppressed"
            ),
        )
        return outcome

    async def abandon(self) -> None:
        """Abandon an unconfirmed candidate when its call ends."""

        if self._candidate is None or self._state is PromiseState.NONE:
            return
        before, after = self._plan_transition(PromiseState.ABANDONED)
        self._apply_transition(after)
        await self._record(
            PromiseEventType.ABANDONED,
            before=before,
            after=after,
            reason="call_ended_before_confirmation",
        )


def expected_idempotency_key(candidate: PromiseCandidate) -> str:
    """Expose the schema contract without duplicating its string format."""

    return derive_idempotency_key(candidate.candidate_id, candidate.revision)
