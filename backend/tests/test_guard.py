"""Adversarial tests for the final pre-TTS disclosure boundary."""

from dataclasses import asdict
from datetime import date

import pytest

from app.contracts import LedgerEventType
from app.guard import (
    SAFE_OUTPUT_LINE,
    GuardCategory,
    OutputBlockedEvent,
    OutputGuardContext,
    classify_block,
    guard_for_tts,
)
from app.seeds import DEMO_CASES, RAKESH_CASE, MockCaseSeed
from app.states import IdentityState, PromiseState
from app.templates import BANK_MEMBERS, is_bank_member


def context(
    identity_state: IdentityState,
    *,
    promise_state: PromiseState = PromiseState.NONE,
    promise_dates: tuple[date | str, ...] = (),
) -> OutputGuardContext:
    return OutputGuardContext.from_case(
        RAKESH_CASE,
        identity_state=identity_state,
        promise_state=promise_state,
        normalized_promise_dates=promise_dates,
    )


@pytest.mark.parametrize(
    ("draft", "expected"),
    [
        ("aapka balance pandrah sau hai", GuardCategory.DEBT_DISCLOSURE),
        ("आपकी EMI बाकी है", GuardCategory.DEBT_DISCLOSURE),
        ("1500 rupaye due hain", GuardCategory.DEBT_DISCLOSURE),
        ("aapki chaar kisht baaki hain", GuardCategory.DEBT_DISCLOSURE),
        ("आपका कर्ज़ अभी बकाया है", GuardCategory.DEBT_DISCLOSURE),
        ("₹1,500 dene hain", GuardCategory.AMOUNT_DISCLOSURE),
        ("do lakh rupees jama kar dijiye", GuardCategory.AMOUNT_DISCLOSURE),
        ("Two thousand rupees jama kar dijiye", GuardCategory.AMOUNT_DISCLOSURE),
    ],
)
def test_multilingual_disclosure_vectors_are_blocked_before_confirmation(
    draft: str,
    expected: GuardCategory,
) -> None:
    assert classify_block(draft, context(IdentityState.UNVERIFIED)) is expected


@pytest.mark.parametrize("case", DEMO_CASES)
def test_seeded_lender_name_is_loaded_from_each_actual_case(case: MockCaseSeed) -> None:
    case_context = OutputGuardContext.from_case(
        case,
        identity_state=IdentityState.VERIFYING,
        promise_state=PromiseState.NONE,
    )
    lender_name = case.account.lender_name

    assert (
        classify_block(
            f"This is a call from {lender_name}.",
            case_context,
        )
        is GuardCategory.SEEDED_ACCOUNT_VALUE
    )


def test_seeded_account_amount_is_loaded_without_hardcoding() -> None:
    amount_rupees = RAKESH_CASE.account.outstanding_minor // 100

    assert (
        classify_block(
            f"Your private reference shows {amount_rupees}.",
            context(IdentityState.THIRD_PARTY),
        )
        is GuardCategory.SEEDED_ACCOUNT_VALUE
    )


def test_normalized_promise_date_is_blocked_only_with_collection_language() -> None:
    promise_date = date(2026, 7, 31)
    unverified = context(IdentityState.UNVERIFIED, promise_dates=(promise_date,))

    assert (
        classify_block("31 July 2026 tak jama kar dijiye", unverified)
        is GuardCategory.PROMISE_DATE_DISCLOSURE
    )
    assert classify_block("The calendar says 31 July 2026.", unverified) is None


@pytest.mark.parametrize("safe_template", sorted(BANK_MEMBERS))
def test_every_reviewed_preconfirmation_template_passes(safe_template: str) -> None:
    assert classify_block(safe_template, context(IdentityState.UNVERIFIED)) is None


def test_read_back_amount_passes_after_confirmation_but_not_before() -> None:
    read_back = "Pandrah sau rupaye — 1-5-0-0 — shukravaar, 31 July 2026. Sahi hai?"
    promise_date = date(2026, 7, 31)

    assert (
        classify_block(
            read_back,
            context(
                IdentityState.CONFIRMED,
                promise_state=PromiseState.READ_BACK,
                promise_dates=(promise_date,),
            ),
        )
        is None
    )
    assert (
        classify_block(
            read_back,
            context(
                IdentityState.UNVERIFIED,
                promise_state=PromiseState.READ_BACK,
                promise_dates=(promise_date,),
            ),
        )
        is GuardCategory.AMOUNT_DISCLOSURE
    )


@pytest.mark.parametrize(
    "draft",
    (
        "hum RBI-registered hain, license 4471",
        "main government se bol raha hoon",
        "हम सरकारी पंजीकृत एजेंट हैं",
    ),
)
@pytest.mark.parametrize(
    "identity_state",
    (
        IdentityState.UNVERIFIED,
        IdentityState.VERIFYING,
        IdentityState.CONFIRMED,
        IdentityState.THIRD_PARTY,
    ),
)
def test_fabricated_credentials_are_blocked_in_every_identity_state(
    draft: str,
    identity_state: IdentityState,
) -> None:
    assert classify_block(draft, context(identity_state)) is GuardCategory.FABRICATED_CREDENTIAL


def test_block_discards_entire_draft_and_records_only_redacted_evidence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocked_draft = "PRIVATE-MARKER aapka balance pandrah sau hai"
    recorded: list[OutputBlockedEvent] = []

    result = guard_for_tts(
        blocked_draft,
        context(
            IdentityState.THIRD_PARTY,
            promise_state=PromiseState.CANDIDATE,
        ),
        record_block=recorded.append,
    )

    assert result.allowed is False
    assert result.speech_text == SAFE_OUTPUT_LINE
    assert is_bank_member(result.speech_text)
    assert blocked_draft not in result.speech_text
    assert recorded == [result.blocked_event]

    event = recorded[0]
    assert event.event_type is LedgerEventType.OUTPUT_BLOCKED
    assert event.category is GuardCategory.DEBT_DISCLOSURE
    assert event.identity_state == IdentityState.THIRD_PARTY.value
    assert event.promise_state == PromiseState.CANDIDATE.value

    serialized_evidence = repr(asdict(event)) + repr(event.as_ledger_payload())
    assert blocked_draft not in serialized_evidence
    assert "draft" not in event.as_ledger_payload()
    assert blocked_draft not in caplog.text


def test_allowed_text_is_unchanged_and_writes_no_guard_event() -> None:
    draft = "धन्यवाद, कृपया एक क्षण रुकिए।"
    recorded: list[OutputBlockedEvent] = []

    result = guard_for_tts(
        draft,
        context(IdentityState.CONFIRMED),
        record_block=recorded.append,
    )

    assert result.allowed is True
    assert result.speech_text == draft
    assert result.blocked_event is None
    assert recorded == []
