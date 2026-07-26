"""Safety and routing tests for fixed pre-confirmation speech."""

import pytest

from app.seeds import DEMO_CASES
from app.templates import (
    BANK_MEMBERS,
    TEMPLATE_BANK,
    TemplateId,
    TemplateVariantError,
    is_bank_member,
    render_template,
    select_preconfirmation_response,
)


@pytest.mark.parametrize(
    ("classifier_intent", "expected_template"),
    [
        ("scam_concern", TemplateId.INTRO_ANTISCAM),
        ("identity_query", TemplateId.INTRO_ANTISCAM),
        ("borrower_present", TemplateId.ASK_FOR_BORROWER),
        ("verification_response", TemplateId.VERIFY_REQUEST),
        ("third_party", TemplateId.THIRD_PARTY_CALLBACK),
        ("clarification", TemplateId.CLARIFY),
        ("technical", TemplateId.TECH_DIFFICULTY_CLOSE),
        ("other", TemplateId.CLARIFY),
    ],
)
def test_typed_classifier_intents_select_only_reviewed_bank_members(
    classifier_intent: str,
    expected_template: TemplateId,
) -> None:
    """The LLM selects an ID; code supplies every spoken character."""
    selection = select_preconfirmation_response({"intent": classifier_intent})

    assert selection.template_id is expected_template
    assert selection.classification_accepted is True
    assert selection.text in TEMPLATE_BANK[expected_template]
    assert is_bank_member(selection.text)


def test_hostile_scam_question_routes_to_anti_scam_copy() -> None:
    """Classifier output for 'scam hai kya?' cannot fall through to generic copy."""
    classifier_output_for_scam_hai_kya = {"intent": "scam_concern"}

    selection = select_preconfirmation_response(classifier_output_for_scam_hai_kya)

    assert selection.template_id is TemplateId.INTRO_ANTISCAM
    assert "OTP" in selection.text
    assert selection.text == render_template(TemplateId.INTRO_ANTISCAM)


def test_ambiguous_haan_boliye_is_not_identity_confirmation() -> None:
    """A generic acknowledgement only asks for the borrower."""
    classifier_output_for_haan_boliye = {"intent": "borrower_present"}

    selection = select_preconfirmation_response(classifier_output_for_haan_boliye)

    assert selection.template_id is TemplateId.ASK_FOR_BORROWER
    assert "Rakesh" in selection.text


def test_malformed_classifier_output_fails_to_fixed_clarification() -> None:
    """Malformed model output has no route to model-authored speech."""
    selection = select_preconfirmation_response('{"intent":')

    assert selection.classification_accepted is False
    assert selection.template_id is TemplateId.CLARIFY
    assert selection.text == render_template(TemplateId.CLARIFY)


def test_extra_private_fields_and_draft_prose_never_reach_speech() -> None:
    """The classification envelope drops all fields except the typed intent."""
    private_draft = "The borrower owes ₹1,500 to a lender."
    selection = select_preconfirmation_response(
        {
            "intent": "third_party",
            "amount_minor": 150_000,
            "response_draft": private_draft,
        }
    )

    assert selection.template_id is TemplateId.THIRD_PARTY_CALLBACK
    assert selection.text != private_draft
    assert "₹" not in selection.text
    assert is_bank_member(selection.text)


def test_three_callback_variants_are_distinct_and_content_free() -> None:
    """Repeated third-party pressure can vary safely without generating prose."""
    variants = tuple(
        select_preconfirmation_response(
            {"intent": "third_party"},
            callback_variant=index,
        ).text
        for index in range(3)
    )

    assert variants == TEMPLATE_BANK[TemplateId.THIRD_PARTY_CALLBACK]
    assert len(set(variants)) == 3
    assert all(is_bank_member(text) for text in variants)


def test_code_can_select_verification_failure_close_without_an_llm_intent() -> None:
    """Attempt-limit code owns the terminal close; the model cannot trigger it."""
    response = render_template(TemplateId.VERIFY_FAILED_CLOSE)

    assert is_bank_member(response)
    assert "पहचान" in response


def test_out_of_range_variant_fails_closed() -> None:
    """No unreviewed fallback is synthesized for a missing phrasing."""
    with pytest.raises(TemplateVariantError):
        render_template(TemplateId.THIRD_PARTY_CALLBACK, variant=3)


def test_bank_contains_no_seeded_lender_or_account_value() -> None:
    """Reviewed pre-confirmation copy is isolated from every private seed."""
    for case in DEMO_CASES:
        assert all(case.account.lender_name not in text for text in BANK_MEMBERS)
        assert all(str(case.account.outstanding_minor) not in text for text in BANK_MEMBERS)


@pytest.mark.parametrize(
    "blocked_marker",
    [
        "loan",
        "debt",
        "due",
        "overdue",
        "balance",
        "recovery",
        "instalment",
        "lender",
        "karza",
        "bakaya",
        "kisht",
        "udhaar",
        "कर्ज़",
        "बकाया",
        "किस्त",
        "उधार",
        "₹",
    ],
)
def test_every_bank_member_avoids_preconfirmation_disclosure_markers(
    blocked_marker: str,
) -> None:
    """Template edits cannot quietly introduce a basic debt or amount marker."""
    assert all(blocked_marker.casefold() not in text.casefold() for text in BANK_MEMBERS)


def test_template_ids_and_bank_are_complete() -> None:
    """Every frozen ID has reviewed copy and no extra family exists."""
    assert set(TEMPLATE_BANK) == set(TemplateId)
    assert len(BANK_MEMBERS) == 9
