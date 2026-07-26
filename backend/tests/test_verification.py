"""Deterministic, value-redacted demo verification tests."""

import json

import pytest

from app.contracts import Disposition
from app.guard import OutputGuardContext, guard_for_tts
from app.seeds import RAKESH_CASE
from app.states import CallState, IdentityState, PromiseState
from app.templates import TemplateId, render_template
from app.tools import PermissionContext, ToolName, evaluate_tool_permission
from app.verification import (
    DEMO_VERIFICATION_LABEL,
    INCOMPLETE_VERIFICATION_INPUT_MARKER,
    MAX_VERIFICATION_ATTEMPTS,
    VERIFICATION_MODEL_PAYLOADS,
    ExpectedVerification,
    FieldCheck,
    IncompleteVerificationSubmission,
    PendingVerificationAttempt,
    VerificationAttemptEvidence,
    VerificationClosedError,
    VerificationField,
    VerificationSession,
    VerificationStatus,
    VerificationSubmission,
    collect_verification_attempt,
    normalize_birth_day_month,
    normalize_reference_last4,
    submit_verification,
    verification_input_marker,
)

EXPECTED = ExpectedVerification.from_case(RAKESH_CASE)
CORRECT = VerificationSubmission("चौदह सितंबर", "चार सात दो नौ")
WRONG = VerificationSubmission("पंद्रह मार्च", "0000")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pandrah march", (15, 3)),
        ("पंद्रह मार्च", (15, 3)),
        ("१५/०३", (15, 3)),
        ("my date is fourteen September", (14, 9)),
        ("दिन चौदह, महीना सितम्बर", (14, 9)),
        ("chaudah sitambar", (14, 9)),
        ("3 farvari", (3, 2)),
        ("03-02", (3, 2)),
        ("twenty first July", (21, 7)),
    ],
)
def test_birth_day_month_normalization(
    raw: str,
    expected: tuple[int, int],
) -> None:
    assert normalize_birth_day_month(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "4729",
        "४७२९",
        "4-7-2-9",
        "four seven two nine",
        "चार सात दो नौ",
        "अंतिम चार अंक ४७२९ हैं",
    ],
)
def test_reference_last4_normalization(raw: str) -> None:
    assert normalize_reference_last4(raw) == "4729"


@pytest.mark.parametrize("raw", ["4-7-2-9", "4 7 2 9", "४-७-२-९"])
def test_segmented_reference_is_not_cross_parsed_as_birth(raw: str) -> None:
    assert normalize_birth_day_month(raw) is None
    assert normalize_reference_last4(raw) == "4729"


@pytest.mark.parametrize(
    "raw",
    ["14/09", "१४/०९", "14-09", "14.09", "14 09", "१४ ०९", "14,09", "14;09"],
)
def test_numeric_birth_date_is_not_cross_parsed_as_reference(raw: str) -> None:
    assert normalize_birth_day_month(raw) == (14, 9)
    assert normalize_reference_last4(raw) is None


@pytest.mark.parametrize(
    "raw",
    ["", "32 January", "thirty second January", "31/13", "not a date"],
)
def test_invalid_birth_day_month_fails_closed(raw: str) -> None:
    assert normalize_birth_day_month(raw) is None


def _account_read_allowed(identity: IdentityState) -> bool:
    return evaluate_tool_permission(
        ToolName.READ_MOCK_ACCOUNT,
        PermissionContext(
            identity_state=identity,
            call_state=CallState.ACTIVE,
            promise_state=PromiseState.NONE,
        ),
    ).allowed


def test_correct_pair_confirms_and_unlocks_account_tool() -> None:
    result = submit_verification(VerificationSession(), CORRECT, EXPECTED)

    assert result.session == VerificationSession(1, VerificationStatus.CONFIRMED)
    assert result.identity_state is IdentityState.CONFIRMED
    assert result.evidence.passed is True
    assert result.disposition is None
    assert result.response_template is None
    assert _account_read_allowed(result.identity_state) is True


def test_one_wrong_then_right_stays_locked_until_attempt_two() -> None:
    first = submit_verification(VerificationSession(), WRONG, EXPECTED)

    assert first.session == VerificationSession(1, VerificationStatus.PENDING)
    assert first.identity_state is IdentityState.VERIFYING
    assert _account_read_allowed(first.identity_state) is False

    second = submit_verification(first.session, CORRECT, EXPECTED)

    assert second.session == VerificationSession(2, VerificationStatus.CONFIRMED)
    assert second.identity_state is IdentityState.CONFIRMED
    assert _account_read_allowed(second.identity_state) is True


def test_partial_submission_is_not_a_complete_attempt() -> None:
    partial = VerificationSubmission("चौदह सितंबर", "not provided")

    assert verification_input_marker(partial) == INCOMPLETE_VERIFICATION_INPUT_MARKER
    with pytest.raises(IncompleteVerificationSubmission):
        submit_verification(VerificationSession(), partial, EXPECTED)

    assert VerificationSession().attempts == 0
    assert PendingVerificationAttempt().complete is False


def test_repeated_partial_cannot_overwrite_first_field_result() -> None:
    session = VerificationSession()
    pending = collect_verification_attempt(
        session,
        PendingVerificationAttempt(),
        VerificationSubmission("पंद्रह मार्च", "not provided"),
        EXPECTED,
    )
    assert pending == PendingVerificationAttempt(birth_day_month_passed=False)

    repeated = collect_verification_attempt(
        session,
        pending,
        VerificationSubmission("चौदह सितंबर", "not provided"),
        EXPECTED,
    )
    assert repeated == pending

    completed = collect_verification_attempt(
        session,
        repeated,
        VerificationSubmission("not provided", "चार सात दो नौ"),
        EXPECTED,
    )
    assert not isinstance(completed, PendingVerificationAttempt)
    assert completed.session == VerificationSession(1, VerificationStatus.PENDING)
    assert completed.evidence == VerificationAttemptEvidence(
        attempt=1,
        checks=(
            FieldCheck(VerificationField.BIRTH_DAY_MONTH, False),
            FieldCheck(VerificationField.REFERENCE_LAST4, True),
        ),
        passed=False,
    )


def test_repeated_reference_guess_cannot_overwrite_first_field_result() -> None:
    session = VerificationSession()
    pending = collect_verification_attempt(
        session,
        PendingVerificationAttempt(),
        VerificationSubmission("not provided", "0000"),
        EXPECTED,
    )
    assert pending == PendingVerificationAttempt(reference_last4_passed=False)

    repeated = collect_verification_attempt(
        session,
        pending,
        VerificationSubmission("not provided", "चार सात दो नौ"),
        EXPECTED,
    )
    assert repeated == pending

    completed = collect_verification_attempt(
        session,
        repeated,
        VerificationSubmission("चौदह सितंबर", "not provided"),
        EXPECTED,
    )
    assert not isinstance(completed, PendingVerificationAttempt)
    assert completed.session == VerificationSession(1, VerificationStatus.PENDING)
    assert completed.evidence == VerificationAttemptEvidence(
        attempt=1,
        checks=(
            FieldCheck(VerificationField.BIRTH_DAY_MONTH, True),
            FieldCheck(VerificationField.REFERENCE_LAST4, False),
        ),
        passed=False,
    )


def test_numeric_birth_partial_waits_for_reference_before_attempt() -> None:
    session = VerificationSession()
    pending = collect_verification_attempt(
        session,
        PendingVerificationAttempt(),
        VerificationSubmission("14/09", "14/09"),
        EXPECTED,
    )

    assert pending == PendingVerificationAttempt(birth_day_month_passed=True)
    completed = collect_verification_attempt(
        session,
        pending,
        VerificationSubmission("4729", "4729"),
        EXPECTED,
    )
    assert not isinstance(completed, PendingVerificationAttempt)
    assert completed.session == VerificationSession(1, VerificationStatus.CONFIRMED)
    assert completed.evidence.passed is True


def test_segmented_reference_partial_waits_for_birth_before_attempt() -> None:
    session = VerificationSession()
    pending = collect_verification_attempt(
        session,
        PendingVerificationAttempt(),
        VerificationSubmission("4-7-2-9", "4-7-2-9"),
        EXPECTED,
    )

    assert pending == PendingVerificationAttempt(reference_last4_passed=True)
    completed = collect_verification_attempt(
        session,
        pending,
        VerificationSubmission("14/09", "14/09"),
        EXPECTED,
    )
    assert not isinstance(completed, PendingVerificationAttempt)
    assert completed.session == VerificationSession(1, VerificationStatus.CONFIRMED)


def test_combined_numeric_birth_and_distinct_reference_remain_complete() -> None:
    result = submit_verification(
        VerificationSession(),
        VerificationSubmission("14 09 reference 4729", "14 09 reference 4729"),
        EXPECTED,
    )

    assert result.session == VerificationSession(1, VerificationStatus.CONFIRMED)


def test_two_wrong_attempts_fail_with_fixed_content_free_close() -> None:
    first = submit_verification(VerificationSession(), WRONG, EXPECTED)
    second = submit_verification(first.session, WRONG, EXPECTED)

    assert second.session == VerificationSession(
        MAX_VERIFICATION_ATTEMPTS,
        VerificationStatus.FAILED,
    )
    assert second.identity_state is IdentityState.VERIFYING
    assert second.disposition is Disposition.VERIFICATION_FAILED
    assert second.response_template is TemplateId.VERIFY_FAILED_CLOSE
    assert "₹" not in render_template(second.response_template)
    assert _account_read_allowed(second.identity_state) is False


def test_failure_matrix_path_never_reads_account_or_leaks_in_close() -> None:
    account_reads: list[str] = []
    evidence: list[dict[str, object]] = []
    session = VerificationSession()

    for _ in range(MAX_VERIFICATION_ATTEMPTS):
        result = submit_verification(session, WRONG, EXPECTED)
        session = result.session
        evidence.append(result.evidence.as_log_record())
        if _account_read_allowed(result.identity_state):
            account_reads.append("read_mock_account")

    assert result.disposition is Disposition.VERIFICATION_FAILED
    assert account_reads == []
    assert evidence == [
        {
            "event": "VERIFICATION_ATTEMPT",
            "attempt": attempt,
            "fields": [
                {"field": "birth_day_month", "passed": False},
                {"field": "reference_last4", "passed": False},
            ],
            "passed": False,
        }
        for attempt in (1, 2)
    ]

    close = render_template(result.response_template)
    guarded = guard_for_tts(
        close,
        OutputGuardContext.from_case(
            RAKESH_CASE,
            identity_state=result.identity_state,
            promise_state=PromiseState.NONE,
        ),
        record_block=lambda event: pytest.fail(f"generic close was blocked: {event.category}"),
    )
    forbidden = {
        "पहचान",
        "सत्यापन",
        "verification",
        "loan",
        "debt",
        "balance",
        "amount",
        "₹",
        RAKESH_CASE.account.lender_name,
        str(RAKESH_CASE.account.outstanding_minor),
    }
    assert guarded.allowed is True
    assert guarded.speech_text == close
    assert all(marker.casefold() not in close.casefold() for marker in forbidden)


def test_closed_challenge_rejects_more_attempts_without_values_in_error() -> None:
    confirmed = submit_verification(VerificationSession(), CORRECT, EXPECTED)

    with pytest.raises(VerificationClosedError) as captured:
        submit_verification(confirmed.session, WRONG, EXPECTED)

    message = str(captured.value)
    assert "4729" not in message
    assert "0000" not in message
    assert "सितंबर" not in message


def test_attempt_evidence_and_representations_never_contain_values() -> None:
    result = submit_verification(VerificationSession(), WRONG, EXPECTED)
    serialized = json.dumps(result.evidence.as_log_record(), sort_keys=True)

    assert json.loads(serialized) == {
        "attempt": 1,
        "event": "VERIFICATION_ATTEMPT",
        "fields": [
            {"field": "birth_day_month", "passed": False},
            {"field": "reference_last4", "passed": False},
        ],
        "passed": False,
    }
    for private_marker in ("4729", "0000", "14", "सितंबर", "पंद्रह", "मार्च"):
        assert private_marker not in serialized
    assert repr(EXPECTED) == "ExpectedVerification(<redacted>)"
    assert repr(CORRECT) == "VerificationSubmission(<redacted>)"


def test_verification_constructs_no_llm_payloads() -> None:
    result = submit_verification(VerificationSession(), CORRECT, EXPECTED)

    assert VERIFICATION_MODEL_PAYLOADS == ()
    assert result.model_payloads == ()
    assert DEMO_VERIFICATION_LABEL == "DEMO VERIFICATION — NOT PRODUCTION AUTHENTICATION"
