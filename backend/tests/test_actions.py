"""Tests for the typed, state-aware LLM action boundary."""

from app.actions import (
    CLARIFICATION_TEMPLATE,
    Intent,
    validate_llm_action,
)


def test_valid_post_confirmed_offer_preserves_typed_fields_and_drops_unknowns() -> None:
    result = validate_llm_action(
        {
            "intent": "offer_promise",
            "amount_minor": 150_000,
            "date_phrase": "Friday",
            "response_draft": "I can record that offer.",
            "invented_tool": "commit_now",
        },
        identity_state="CONFIRMED",
        promise_state="NONE",
        call_state="ACTIVE",
    )

    assert result.accepted is True
    assert result.action.intent is Intent.OFFER_PROMISE
    assert result.action.amount_minor == 150_000
    assert result.action.date_phrase == "Friday"
    assert "invented_tool" not in result.action.model_dump()


def test_private_fields_and_model_prose_are_rejected_while_unverified() -> None:
    result = validate_llm_action(
        {
            "intent": "offer_promise",
            "amount_minor": 150_000,
            "date_phrase": "Friday",
            "response_draft": "Your balance is due.",
        },
        identity_state="UNVERIFIED",
        promise_state="NONE",
        call_state="ACTIVE",
    )

    assert result.accepted is False
    assert result.action.amount_minor is None
    assert result.action.date_phrase is None
    assert result.action.response_draft == ""
    assert result.rejected_fields == (
        "intent",
        "amount_minor",
        "date_phrase",
        "response_draft",
    )


def test_write_capable_intent_is_not_accepted_before_confirmation() -> None:
    result = validate_llm_action(
        {"intent": "confirm"},
        identity_state="UNVERIFIED",
        promise_state="READ_BACK",
        call_state="ACTIVE",
    )

    assert result.accepted is False
    assert result.action.intent is Intent.CONFIRM
    assert result.rejected_fields == ("intent",)


def test_malformed_json_fails_safe_to_other_and_clarification_template() -> None:
    result = validate_llm_action(
        '{"intent": "offer_promise",',
        identity_state="CONFIRMED",
        promise_state="NONE",
        call_state="ACTIVE",
    )

    assert result.accepted is False
    assert result.action.intent is Intent.OTHER
    assert result.action.response_draft == ""
    assert result.rejected_fields == ("payload",)
    assert result.response_template == CLARIFICATION_TEMPLATE


def test_handover_in_active_call_emits_demotion_signal_and_discards_prose() -> None:
    result = validate_llm_action(
        {
            "intent": "handover",
            "response_draft": "I will tell the next speaker what we discussed.",
        },
        identity_state="CONFIRMED",
        promise_state="READ_BACK",
        call_state="ACTIVE",
    )

    assert result.accepted is True
    assert result.action.intent is Intent.HANDOVER
    assert result.action.response_draft == ""
    assert result.handover_requested is True


def test_handover_is_rejected_outside_an_active_call() -> None:
    result = validate_llm_action(
        {"intent": "handover", "response_draft": "handover"},
        identity_state="CONFIRMED",
        promise_state="NONE",
        call_state="ENDED",
    )

    assert result.accepted is False
    assert result.action.intent is Intent.OTHER
    assert result.handover_requested is False


def test_confirm_is_only_meaningful_during_read_back() -> None:
    result = validate_llm_action(
        {"intent": "confirm", "response_draft": "Confirmed."},
        identity_state="CONFIRMED",
        promise_state="CANDIDATE",
        call_state="ACTIVE",
    )

    assert result.accepted is False
    assert result.action.intent is Intent.OTHER
    assert result.rejected_fields == ("intent",)
    assert result.response_template == CLARIFICATION_TEMPLATE
