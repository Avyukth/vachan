"""Deterministic demo verification with redacted evidence.

Expected values and caller submissions exist only inside this module's local
comparison boundary. They are never rendered into prompts, utterances,
exceptions, representations, or evidence rows.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from app.contracts import Disposition
from app.states import IdentityState
from app.templates import TemplateId

if TYPE_CHECKING:
    from app.seeds import MockCaseSeed

MAX_VERIFICATION_ATTEMPTS: Final = 2
DEMO_VERIFICATION_LABEL: Final = "DEMO VERIFICATION — NOT PRODUCTION AUTHENTICATION"

# Verification is deliberately absent from the model boundary. Keeping this
# explicit makes prompt-isolation tests inspect an application contract rather
# than infer safety from a mocked network call.
VERIFICATION_MODEL_PAYLOADS: Final[tuple[()]] = ()
COMPLETE_VERIFICATION_INPUT_MARKER: Final = "[complete verification response withheld]"
INCOMPLETE_VERIFICATION_INPUT_MARKER: Final = "[verification input withheld]"

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUMERIC_DATE_PATTERN = re.compile(r"(?<!\d)(?P<day>[0-3]?\d)\s*[/.\-]\s*(?P<month>[01]?\d)(?!\d)")


class VerificationField(StrEnum):
    """The only expected fields compared by the demo mechanism."""

    BIRTH_DAY_MONTH = "birth_day_month"
    REFERENCE_LAST4 = "reference_last4"


class VerificationStatus(StrEnum):
    """Attempt lifecycle independent of call-state persistence."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class VerificationClosedError(RuntimeError):
    """A caller attempted verification after success or terminal failure."""


class IncompleteVerificationSubmission(ValueError):
    """A caller submission did not contain both verification fields."""


@dataclass(frozen=True, slots=True, repr=False)
class ExpectedVerification:
    """Backend-only expected values loaded from one seeded case."""

    birth_day: int
    birth_month: int
    reference_last4: str

    def __post_init__(self) -> None:
        if not 1 <= self.birth_day <= 31 or not 1 <= self.birth_month <= 12:
            raise ValueError("expected birth day/month is outside the supported range")
        normalized_reference = normalize_reference_last4(self.reference_last4)
        if normalized_reference is None:
            raise ValueError("expected reference must normalize to exactly four characters")

    @classmethod
    def from_case(cls, case: MockCaseSeed) -> ExpectedVerification:
        """Copy expected values into the narrow comparison type."""

        return cls(
            birth_day=case.verification.birth_day,
            birth_month=case.verification.birth_month,
            reference_last4=case.verification.reference_last4,
        )

    def __repr__(self) -> str:
        return "ExpectedVerification(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class VerificationSubmission:
    """Caller-provided fields; representations never expose their values."""

    birth_day_month: str
    reference_last4: str

    def __repr__(self) -> str:
        return "VerificationSubmission(<redacted>)"


@dataclass(frozen=True, slots=True)
class FieldCheck:
    """Safe evidence for one field comparison."""

    field: VerificationField
    passed: bool


@dataclass(frozen=True, slots=True)
class VerificationAttemptEvidence:
    """Append-ready attempt evidence containing no verification values."""

    attempt: int
    checks: tuple[FieldCheck, ...]
    passed: bool

    def __post_init__(self) -> None:
        if not 1 <= self.attempt <= MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("attempt is outside the configured verification limit")
        if tuple(check.field for check in self.checks) != tuple(VerificationField):
            raise ValueError("evidence must contain each verification field exactly once")
        if self.passed != all(check.passed for check in self.checks):
            raise ValueError("attempt result must equal the conjunction of its field checks")

    def as_log_record(self) -> dict[str, object]:
        """Return the only verification-attempt shape safe to persist or log."""

        return {
            "event": "VERIFICATION_ATTEMPT",
            "attempt": self.attempt,
            "fields": [
                {"field": check.field.value, "passed": check.passed} for check in self.checks
            ],
            "passed": self.passed,
        }

    def as_redacted_reason(self) -> str:
        """Serialize the approved shape for the append-only event row."""

        return json.dumps(
            self.as_log_record(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_redacted_reason(cls, value: str) -> VerificationAttemptEvidence:
        """Parse one durable event payload without accepting extra fields."""

        try:
            record = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("verification evidence is not valid JSON") from error
        if not isinstance(record, dict) or set(record) != {
            "event",
            "attempt",
            "fields",
            "passed",
        }:
            raise ValueError("verification evidence has an unexpected top-level shape")
        if record["event"] != "VERIFICATION_ATTEMPT":
            raise ValueError("verification evidence has an unexpected event type")
        attempt = record["attempt"]
        passed = record["passed"]
        fields = record["fields"]
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            raise ValueError("verification evidence attempt must be an integer")
        if not isinstance(passed, bool) or not isinstance(fields, list):
            raise ValueError("verification evidence result has an invalid type")

        checks: list[FieldCheck] = []
        for field in fields:
            if not isinstance(field, dict) or set(field) != {"field", "passed"}:
                raise ValueError("verification field evidence has an unexpected shape")
            field_name = field["field"]
            field_passed = field["passed"]
            if not isinstance(field_name, str) or not isinstance(field_passed, bool):
                raise ValueError("verification field evidence has an invalid type")
            try:
                verification_field = VerificationField(field_name)
            except ValueError as error:
                raise ValueError("verification field evidence has an unknown field") from error
            checks.append(FieldCheck(field=verification_field, passed=field_passed))
        return cls(attempt=attempt, checks=tuple(checks), passed=passed)


@dataclass(frozen=True, slots=True)
class VerificationSession:
    """Immutable attempt state, created fresh for every call/challenge."""

    attempts: int = 0
    status: VerificationStatus = VerificationStatus.PENDING

    def __post_init__(self) -> None:
        if not 0 <= self.attempts <= MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("verification attempts are outside the configured limit")
        if self.status is VerificationStatus.CONFIRMED and self.attempts < 1:
            raise ValueError("confirmed verification must contain a successful attempt")
        if self.status is VerificationStatus.PENDING and self.attempts == MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("pending verification cannot exhaust the attempt limit")
        if self.status is VerificationStatus.FAILED and self.attempts != MAX_VERIFICATION_ATTEMPTS:
            raise ValueError("failed verification must exhaust the attempt limit")


@dataclass(frozen=True, slots=True)
class PendingVerificationAttempt:
    """Value-free field results collected before one complete attempt."""

    birth_day_month_passed: bool | None = None
    reference_last4_passed: bool | None = None

    def __post_init__(self) -> None:
        for result in (self.birth_day_month_passed, self.reference_last4_passed):
            if result is not None and not isinstance(result, bool):
                raise TypeError("pending verification results must be booleans or None")

    @property
    def complete(self) -> bool:
        """Return whether both fields have been supplied and compared."""

        return self.birth_day_month_passed is not None and self.reference_last4_passed is not None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """One code-owned verification outcome for the controller to apply."""

    session: VerificationSession
    identity_state: IdentityState
    evidence: VerificationAttemptEvidence
    disposition: Disposition | None = None
    response_template: TemplateId | None = None
    model_payloads: tuple[()] = VERIFICATION_MODEL_PAYLOADS

    def __post_init__(self) -> None:
        terminal_failure = self.session.status is VerificationStatus.FAILED
        if terminal_failure != (self.disposition is Disposition.VERIFICATION_FAILED):
            raise ValueError("only terminal verification failure sets VERIFICATION_FAILED")
        if terminal_failure != (self.response_template is TemplateId.VERIFY_FAILED_CLOSE):
            raise ValueError("only terminal verification failure selects the fixed close template")
        if self.model_payloads:
            raise ValueError("verification must not construct model payloads")


def reconstruct_verification_session(
    attempts: Iterable[VerificationAttemptEvidence],
) -> VerificationSession:
    """Rebuild attempt state from durable, redacted evidence only.

    Restart recovery must never infer an attempt from a tool decision or a
    caller value. Only a contiguous sequence of persisted attempt records may
    consume the two-attempt budget.
    """

    evidence = tuple(attempts)
    if len(evidence) > MAX_VERIFICATION_ATTEMPTS:
        raise ValueError("verification evidence exceeds the configured attempt limit")
    expected_numbers = tuple(range(1, len(evidence) + 1))
    if tuple(item.attempt for item in evidence) != expected_numbers:
        raise ValueError("verification evidence attempts must be contiguous and ordered")
    if any(item.passed for item in evidence[:-1]):
        raise ValueError("verification evidence cannot continue after a successful attempt")
    if not evidence:
        return VerificationSession()

    latest = evidence[-1]
    if latest.passed:
        status = VerificationStatus.CONFIRMED
    elif latest.attempt == MAX_VERIFICATION_ATTEMPTS:
        status = VerificationStatus.FAILED
    else:
        status = VerificationStatus.PENDING
    return VerificationSession(attempts=latest.attempt, status=status)


def _normalized_tokens(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).translate(_DEVANAGARI_DIGITS).casefold()
    tokenized = "".join(
        character if character.isalnum() or unicodedata.category(character).startswith("M") else " "
        for character in normalized
    )
    return tuple(tokenized.split())


_ENGLISH_DAYS = {
    1: ("one", "first"),
    2: ("two", "second"),
    3: ("three", "third"),
    4: ("four", "fourth"),
    5: ("five", "fifth"),
    6: ("six", "sixth"),
    7: ("seven", "seventh"),
    8: ("eight", "eighth"),
    9: ("nine", "ninth"),
    10: ("ten", "tenth"),
    11: ("eleven", "eleventh"),
    12: ("twelve", "twelfth"),
    13: ("thirteen", "thirteenth"),
    14: ("fourteen", "fourteenth"),
    15: ("fifteen", "fifteenth"),
    16: ("sixteen", "sixteenth"),
    17: ("seventeen", "seventeenth"),
    18: ("eighteen", "eighteenth"),
    19: ("nineteen", "nineteenth"),
    20: ("twenty", "twentieth"),
    21: ("twentyone", "twentyfirst"),
    22: ("twentytwo", "twentysecond"),
    23: ("twentythree", "twentythird"),
    24: ("twentyfour", "twentyfourth"),
    25: ("twentyfive", "twentyfifth"),
    26: ("twentysix", "twentysixth"),
    27: ("twentyseven", "twentyseventh"),
    28: ("twentyeight", "twentyeighth"),
    29: ("twentynine", "twentyninth"),
    30: ("thirty", "thirtieth"),
    31: ("thirtyone", "thirtyfirst"),
}

_HINDI_DAYS = {
    1: ("ek", "एक"),
    2: ("do", "दो"),
    3: ("teen", "तीन"),
    4: ("chaar", "char", "चार"),
    5: ("paanch", "panch", "पांच", "पाँच"),
    6: ("chhah", "chhe", "cheh", "छह"),
    7: ("saat", "sat", "सात"),
    8: ("aath", "ath", "आठ"),
    9: ("nau", "नौ"),
    10: ("das", "दस"),
    11: ("gyarah", "gyaarah", "ग्यारह"),
    12: ("barah", "baarah", "बारह"),
    13: ("terah", "तेरह"),
    14: ("chaudah", "चौदह"),
    15: ("pandrah", "pandra", "पंद्रह", "पन्द्रह"),
    16: ("solah", "सोलह"),
    17: ("satrah", "सत्रह"),
    18: ("atharah", "attharah", "अठारह"),
    19: ("unnis", "उन्नीस"),
    20: ("bees", "बीस"),
    21: ("ikkis", "इक्कीस"),
    22: ("bais", "baais", "बाईस"),
    23: ("teis", "teyis", "तेईस"),
    24: ("chaubis", "चौबीस"),
    25: ("pachis", "pachchees", "पच्चीस"),
    26: ("chhabbis", "छब्बीस"),
    27: ("sattais", "sattaees", "सत्ताईस"),
    28: ("atthais", "atthaees", "अट्ठाईस"),
    29: ("untis", "उनतीस"),
    30: ("tees", "तीस"),
    31: ("ikattis", "इकतीस"),
}


def _alias_map(source: dict[int, tuple[str, ...]]) -> dict[str, int]:
    return {
        "".join(_normalized_tokens(alias)): number
        for number, aliases in source.items()
        for alias in aliases
    }


_DAY_ALIASES = MappingProxyType(_alias_map(_ENGLISH_DAYS) | _alias_map(_HINDI_DAYS))

_MONTHS = {
    1: ("january", "jan", "janwari", "जनवरी"),
    2: ("february", "feb", "farvari", "फरवरी"),
    3: ("march", "mar", "मार्च"),
    4: ("april", "apr", "अप्रैल"),
    5: ("may", "मई"),
    6: ("june", "jun", "जून"),
    7: ("july", "jul", "julai", "जुलाई"),
    8: ("august", "aug", "agast", "अगस्त"),
    9: (
        "september",
        "sep",
        "sept",
        "sitambar",
        "sitamber",
        "सितंबर",
        "सितम्बर",
    ),
    10: ("october", "oct", "aktubar", "अक्टूबर"),
    11: ("november", "nov", "navambar", "नवंबर", "नवम्बर"),
    12: ("december", "dec", "disambar", "दिसंबर", "दिसम्बर"),
}
_MONTH_ALIASES = MappingProxyType(_alias_map(_MONTHS))

_SINGLE_DIGITS = {
    0: ("zero", "shunya", "sifar", "शून्य", "सिफर"),
    1: ("one", "ek", "एक"),
    2: ("two", "do", "दो"),
    3: ("three", "teen", "तीन"),
    4: ("four", "chaar", "char", "चार"),
    5: ("five", "paanch", "panch", "पांच", "पाँच"),
    6: ("six", "chhah", "chhe", "cheh", "छह"),
    7: ("seven", "saat", "sat", "सात"),
    8: ("eight", "aath", "ath", "आठ"),
    9: ("nine", "nau", "नौ"),
}
_DIGIT_ALIASES = MappingProxyType(_alias_map(_SINGLE_DIGITS))


def _parse_day_alias(tokens: tuple[str, ...], excluded_index: int | None = None) -> int | None:
    for index, (current, following) in enumerate(zip(tokens, tokens[1:], strict=False)):
        if excluded_index in {index, index + 1}:
            continue
        combined = current + following
        if current in _DAY_ALIASES and following in _DAY_ALIASES and combined not in _DAY_ALIASES:
            return None

    for index, token in enumerate(tokens):
        if index == excluded_index:
            continue
        if token.isdigit() and 1 <= int(token) <= 31:
            return int(token)
        for width in (2, 1):
            if index + width > len(tokens):
                continue
            compact = "".join(tokens[index : index + width])
            if compact in _DAY_ALIASES:
                return _DAY_ALIASES[compact]
    return None


def normalize_birth_day_month(value: str) -> tuple[int, int] | None:
    """Normalize Hindi/English/code-mixed day+month into numeric form."""

    normalized = unicodedata.normalize("NFKC", value).translate(_DEVANAGARI_DIGITS).casefold()
    numeric_match = _NUMERIC_DATE_PATTERN.search(normalized)
    if numeric_match is not None:
        day = int(numeric_match.group("day"))
        month = int(numeric_match.group("month"))
        return (day, month) if 1 <= day <= 31 and 1 <= month <= 12 else None

    tokens = _normalized_tokens(value)
    for month_index, token in enumerate(tokens):
        month = _MONTH_ALIASES.get(token)
        if month is None:
            continue
        day = _parse_day_alias(tokens, excluded_index=month_index)
        if day is not None:
            return day, month

    numeric_tokens = [(index, int(token)) for index, token in enumerate(tokens) if token.isdigit()]
    for day_index, day in numeric_tokens:
        for month_index, month in numeric_tokens:
            if day_index != month_index and 1 <= day <= 31 and 1 <= month <= 12:
                return day, month
    return None


def normalize_reference_last4(value: str) -> str | None:
    """Normalize four spoken/typed reference characters without logging them."""

    tokens = _normalized_tokens(value)
    compact = "".join(tokens).upper()
    if len(compact) == 4 and compact.isascii() and compact.isalnum():
        return compact
    embedded = [
        token.upper() for token in tokens if len(token) == 4 and token.isascii() and token.isalnum()
    ]
    if len(embedded) == 1:
        return embedded[0]

    spoken_digits = [_DIGIT_ALIASES[token] for token in tokens if token in _DIGIT_ALIASES]
    if len(spoken_digits) == 4:
        return "".join(str(digit) for digit in spoken_digits)

    individual = [
        token.upper() for token in tokens if len(token) == 1 and token.isascii() and token.isalnum()
    ]
    return "".join(individual) if len(individual) == 4 else None


def _normalized_expected_reference(expected: ExpectedVerification) -> str:
    normalized = normalize_reference_last4(expected.reference_last4)
    assert normalized is not None
    return normalized


def _ensure_verification_open(session: VerificationSession) -> None:
    if session.status is not VerificationStatus.PENDING:
        raise VerificationClosedError("verification challenge is already closed")
    if session.attempts >= MAX_VERIFICATION_ATTEMPTS:
        raise VerificationClosedError("verification attempt limit is exhausted")


def verification_input_marker(submission: VerificationSubmission) -> str:
    """Return a value-free model/history marker for one caller submission."""

    complete = (
        normalize_birth_day_month(submission.birth_day_month) is not None
        and normalize_reference_last4(submission.reference_last4) is not None
    )
    return COMPLETE_VERIFICATION_INPUT_MARKER if complete else INCOMPLETE_VERIFICATION_INPUT_MARKER


def collect_verification_attempt(
    session: VerificationSession,
    pending: PendingVerificationAttempt,
    submission: VerificationSubmission,
    expected: ExpectedVerification,
) -> PendingVerificationAttempt | VerificationResult:
    """Collect value-free checks and finalize only after both fields arrive."""

    _ensure_verification_open(session)
    normalized_birth = normalize_birth_day_month(submission.birth_day_month)
    normalized_reference = normalize_reference_last4(submission.reference_last4)
    collected = PendingVerificationAttempt(
        birth_day_month_passed=(
            pending.birth_day_month_passed
            if pending.birth_day_month_passed is not None
            else (
                None
                if normalized_birth is None
                else normalized_birth == (expected.birth_day, expected.birth_month)
            )
        ),
        reference_last4_passed=(
            pending.reference_last4_passed
            if pending.reference_last4_passed is not None
            else (
                None
                if normalized_reference is None
                else normalized_reference == _normalized_expected_reference(expected)
            )
        ),
    )
    if not collected.complete:
        return collected

    assert collected.birth_day_month_passed is not None
    assert collected.reference_last4_passed is not None
    return _complete_verification_attempt(
        session,
        birth_passed=collected.birth_day_month_passed,
        reference_passed=collected.reference_last4_passed,
    )


def _complete_verification_attempt(
    session: VerificationSession,
    *,
    birth_passed: bool,
    reference_passed: bool,
) -> VerificationResult:
    """Build one complete attempt from value-free comparison results."""

    _ensure_verification_open(session)
    attempt = session.attempts + 1
    passed = birth_passed and reference_passed
    evidence = VerificationAttemptEvidence(
        attempt=attempt,
        checks=(
            FieldCheck(VerificationField.BIRTH_DAY_MONTH, birth_passed),
            FieldCheck(VerificationField.REFERENCE_LAST4, reference_passed),
        ),
        passed=passed,
    )

    if passed:
        return VerificationResult(
            session=VerificationSession(attempt, VerificationStatus.CONFIRMED),
            identity_state=IdentityState.CONFIRMED,
            evidence=evidence,
        )

    if attempt == MAX_VERIFICATION_ATTEMPTS:
        return VerificationResult(
            session=VerificationSession(attempt, VerificationStatus.FAILED),
            identity_state=IdentityState.VERIFYING,
            evidence=evidence,
            disposition=Disposition.VERIFICATION_FAILED,
            response_template=TemplateId.VERIFY_FAILED_CLOSE,
        )

    return VerificationResult(
        session=VerificationSession(attempt, VerificationStatus.PENDING),
        identity_state=IdentityState.VERIFYING,
        evidence=evidence,
    )


def submit_verification(
    session: VerificationSession,
    submission: VerificationSubmission,
    expected: ExpectedVerification,
) -> VerificationResult:
    """Compare one complete attempt locally and return a redacted outcome."""

    result = collect_verification_attempt(
        session,
        PendingVerificationAttempt(),
        submission,
        expected,
    )
    if isinstance(result, PendingVerificationAttempt):
        raise IncompleteVerificationSubmission(
            "verification attempt requires both supported fields"
        )
    return result
