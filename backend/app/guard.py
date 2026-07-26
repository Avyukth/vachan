"""Fail-closed, state-aware guard applied immediately before TTS.

Context isolation, tool isolation, and fixed pre-confirmation templates are
Vachan's primary privacy boundaries. This module is deliberately the fourth
layer: it rejects enumerable disclosure patterns and fabricated credentials
without pretending that a regex can replace those stronger controls.

Blocked draft bodies never appear in the returned result, evidence event, or
recorder call. The caller must pass the returned ``speech_text`` to TTS rather
than retaining or partially redacting the rejected draft.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, StrEnum

from app.contracts import LedgerEventType
from app.seeds import MockCaseSeed
from app.states import IdentityState, PromiseState
from app.templates import TemplateId, render_template
from app.verification import (
    ExpectedVerification,
    contains_expected_verification_value,
)

SAFE_OUTPUT_LINE = render_template(TemplateId.OUTPUT_GUARD_FALLBACK)


class GuardCategory(StrEnum):
    """Stable, redacted reasons for suppressing a response."""

    FABRICATED_CREDENTIAL = "fabricated_credential"
    SEEDED_VERIFICATION_VALUE = "seeded_verification_value"
    SEEDED_ACCOUNT_VALUE = "seeded_account_value"
    AMOUNT_DISCLOSURE = "amount_disclosure"
    DEBT_DISCLOSURE = "debt_disclosure"
    PROMISE_DATE_DISCLOSURE = "promise_date_disclosure"


@dataclass(frozen=True, slots=True, repr=False)
class OutputGuardContext:
    """Authorization state and backend-only values used by the guard."""

    identity_state: IdentityState | str
    promise_state: PromiseState | str
    protected_account_terms: tuple[str, ...] = ()
    normalized_promise_dates: tuple[date | str, ...] = ()
    expected_verification: ExpectedVerification | None = field(default=None, repr=False)

    @classmethod
    def from_case(
        cls,
        case: MockCaseSeed,
        *,
        identity_state: IdentityState | str,
        promise_state: PromiseState | str,
        normalized_promise_dates: Iterable[date | str] = (),
    ) -> OutputGuardContext:
        """Build dynamic protected terms from the actual backend case.

        The values are used for comparison only. They are not copied into
        evidence or error strings.
        """

        account = case.account
        protected_terms = [
            account.lender_name,
            str(account.outstanding_minor),
            str(account.outstanding_minor // 100),
        ]
        for installment in account.emi_schedule:
            protected_terms.extend(
                (
                    str(installment.amount_minor),
                    str(installment.amount_minor // 100),
                    installment.due_date.isoformat(),
                )
            )
        return cls(
            identity_state=identity_state,
            promise_state=promise_state,
            protected_account_terms=tuple(protected_terms),
            normalized_promise_dates=tuple(normalized_promise_dates),
            expected_verification=ExpectedVerification.from_case(case),
        )


@dataclass(frozen=True, slots=True)
class OutputBlockedEvent:
    """Redacted append-ready evidence for one discarded response."""

    event_type: LedgerEventType
    category: GuardCategory
    identity_state: str
    promise_state: str
    redacted_reason: str

    def as_ledger_payload(self) -> dict[str, str]:
        """Serialize evidence without creating a field for the blocked draft."""

        return {
            "event_type": self.event_type.value,
            "category": self.category.value,
            "identity_state": self.identity_state,
            "promise_state": self.promise_state,
            "redacted_reason": self.redacted_reason,
        }


@dataclass(frozen=True, slots=True)
class GuardedSpeech:
    """The only value a caller may forward to TTS."""

    speech_text: str
    allowed: bool
    blocked_event: OutputBlockedEvent | None = None


type BlockRecorder = Callable[[OutputBlockedEvent], None]


_FABRICATED_CREDENTIAL_PATTERN = re.compile(
    r"""
    \b(?:rbi|reserve\s+bank|government|regulator(?:y)?|regulation|
    licen[cs](?:e|ed|ing)?|register(?:ed|ation)?)\b
    |सरकार|सरकारी|आरबीआई|रिजर्व\s*बैंक|लाइस[ेें]स|पंजीकृत|नियामक
    """,
    re.IGNORECASE | re.VERBOSE,
)

_DEBT_PATTERN = re.compile(
    r"""
    \b(?:emi|loan|debt|due|overdue|balance|recovery|instalments?|installments?|
    lender|karz|karza|bakaya|kisht|kisten|udhaar|udhar)\b
    |ईएमआई|ऋण|कर्ज़?|कर्ज़|बकाया|किश्त|उधार|वसूली|शेष\s*राशि
    """,
    re.IGNORECASE | re.VERBOSE,
)

_MONEY_TERM_PATTERN = re.compile(
    r"""
    ₹|\brs\.?\b|\binr\b|\brupees?\b|\brupaye?\b|\brupaiye\b|
    रुपये|रुपए|रुपये|पैसे|राशि|amount
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NUMBER_PATTERN = re.compile(
    r"""
    \d(?:[\d,\s.-]*\d)?
    |\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|
    thirteen|fourteen|fifteen|twenty|thirty|forty|fifty|hundred|thousand|
    lakh|crore|ek|do|teen|char|chaar|paanch|cheh|saat|aath|nau|dus|
    gyarah|barah|pandrah|bees|sau|hazaar)\b
    |शून्य|एक|दो|तीन|चार|पाँच|पांच|छह|सात|आठ|नौ|दस|ग्यारह|बारह|
    पंद्रह|बीस|सौ|हज़ार|हजार|लाख|करोड़
    """,
    re.IGNORECASE | re.VERBOSE,
)

_COLLECTION_ACTION_PATTERN = re.compile(
    r"""
    \b(?:pay|payment|deposit|collect|collection|recover|recovery|jama|
    bharna|bhugtan)\b
    |जमा|भुगतान|वसूली|भर(?:ना|ें)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _state_value(state: IdentityState | PromiseState | str) -> str:
    value = state.value if isinstance(state, Enum) else state
    return str(value).upper()


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _searchable_text(value: str) -> str:
    """Normalize punctuation so dynamic lender names compare consistently."""

    return re.sub(r"[^\w\u0900-\u097f]+", " ", _normalized_text(value)).strip()


def _contains_protected_term(text: str, protected_terms: Iterable[str]) -> bool:
    searchable = _searchable_text(text)
    for term in protected_terms:
        candidate = _searchable_text(term)
        if candidate and candidate in searchable:
            return True
    return False


def _date_forms(value: date | str) -> frozenset[str]:
    if isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            normalized = _searchable_text(value)
            return frozenset({normalized}) if normalized else frozenset()

    return frozenset(
        {
            _searchable_text(parsed.isoformat()),
            _searchable_text(parsed.strftime("%d-%m-%Y")),
            _searchable_text(parsed.strftime("%d/%m/%Y")),
            _searchable_text(parsed.strftime("%d %B %Y")),
            _searchable_text(parsed.strftime("%B %d %Y")),
        }
    )


def _contains_protected_date(text: str, dates: Iterable[date | str]) -> bool:
    searchable = _searchable_text(text)
    return any(
        form and form in searchable
        for protected_date in dates
        for form in _date_forms(protected_date)
    )


def classify_block(
    draft: str,
    context: OutputGuardContext,
) -> GuardCategory | None:
    """Return the first applicable redacted block category."""

    normalized = _normalized_text(draft)

    # Fabricated authority is unsafe even after the borrower is confirmed.
    if _FABRICATED_CREDENTIAL_PATTERN.search(normalized):
        return GuardCategory.FABRICATED_CREDENTIAL

    expected = context.expected_verification
    if expected is not None and contains_expected_verification_value(draft, expected):
        return GuardCategory.SEEDED_VERIFICATION_VALUE

    if _state_value(context.identity_state) == IdentityState.CONFIRMED.value:
        return None

    if _contains_protected_term(normalized, context.protected_account_terms):
        return GuardCategory.SEEDED_ACCOUNT_VALUE

    if _DEBT_PATTERN.search(normalized):
        return GuardCategory.DEBT_DISCLOSURE

    if _MONEY_TERM_PATTERN.search(normalized) and _NUMBER_PATTERN.search(normalized):
        return GuardCategory.AMOUNT_DISCLOSURE

    if _COLLECTION_ACTION_PATTERN.search(normalized) and _contains_protected_date(
        normalized, context.normalized_promise_dates
    ):
        return GuardCategory.PROMISE_DATE_DISCLOSURE

    return None


def guard_for_tts(
    draft: str,
    context: OutputGuardContext,
    *,
    record_block: BlockRecorder,
) -> GuardedSpeech:
    """Return speakable text and synchronously record any blocked response.

    The recorder receives evidence before the safe line is returned. Its
    payload is intentionally incapable of containing the blocked draft.
    """

    category = classify_block(draft, context)
    if category is None:
        return GuardedSpeech(speech_text=draft, allowed=True)

    identity_state = _state_value(context.identity_state)
    promise_state = _state_value(context.promise_state)
    event = OutputBlockedEvent(
        event_type=LedgerEventType.OUTPUT_BLOCKED,
        category=category,
        identity_state=identity_state,
        promise_state=promise_state,
        redacted_reason=f"output_guard:{category.value}",
    )
    record_block(event)
    return GuardedSpeech(
        speech_text=SAFE_OUTPUT_LINE,
        allowed=False,
        blocked_event=event,
    )
