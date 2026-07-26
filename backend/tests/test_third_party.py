"""Third-party privacy-path tests using actual seeded private values."""

from collections.abc import Mapping

import pytest

from app.actions import PreConfirmationIntent
from app.contracts import Disposition
from app.guard import OutputGuardContext, guard_for_tts
from app.seeds import RAKESH_CASE
from app.states import IdentityState, PromiseState
from app.templates import TEMPLATE_BANK, TemplateId
from app.third_party import (
    ContentFreeCallbackPayload,
    SpeakerRouteKind,
    ThirdPartyAlreadyCompleted,
    ThirdPartyResponsesIncomplete,
    ThirdPartySession,
    payload_is_content_free,
    protected_case_values,
    route_speaker_utterance,
)
from app.tools import ToolDecision, ToolName, ToolPermissionDenied


@pytest.mark.parametrize(
    ("utterance", "expected_kind", "expected_target", "expected_template"),
    [
        (
            "haan boliye",
            SpeakerRouteKind.ASK_FOR_BORROWER,
            None,
            TemplateId.ASK_FOR_BORROWER,
        ),
        (
            "main unki wife hoon",
            SpeakerRouteKind.ENTER_THIRD_PARTY,
            IdentityState.THIRD_PARTY,
            TemplateId.THIRD_PARTY_CALLBACK,
        ),
        (
            "wo ghar pe nahi hai",
            SpeakerRouteKind.ENTER_THIRD_PARTY,
            IdentityState.THIRD_PARTY,
            TemplateId.THIRD_PARTY_CALLBACK,
        ),
        (
            "मैं उनकी पत्नी हूँ",
            SpeakerRouteKind.ENTER_THIRD_PARTY,
            IdentityState.THIRD_PARTY,
            TemplateId.THIRD_PARTY_CALLBACK,
        ),
        (
            "He is not home",
            SpeakerRouteKind.ENTER_THIRD_PARTY,
            IdentityState.THIRD_PARTY,
            TemplateId.THIRD_PARTY_CALLBACK,
        ),
        ("bhai bol raha hoon", SpeakerRouteKind.CLARIFY, None, TemplateId.CLARIFY),
        (
            "Rakesh bol raha hoon",
            SpeakerRouteKind.START_VERIFICATION,
            IdentityState.VERIFYING,
            TemplateId.VERIFY_REQUEST,
        ),
        (
            "मैं राकेश बोल रहा हूँ",
            SpeakerRouteKind.START_VERIFICATION,
            IdentityState.VERIFYING,
            TemplateId.VERIFY_REQUEST,
        ),
        ("", SpeakerRouteKind.CLARIFY, None, TemplateId.CLARIFY),
    ],
)
def test_ambiguity_vector_never_grants_confirmation(
    utterance: str,
    expected_kind: SpeakerRouteKind,
    expected_target: IdentityState | None,
    expected_template: TemplateId,
) -> None:
    route = route_speaker_utterance(utterance)

    assert route.kind is expected_kind
    assert route.identity_target is expected_target
    assert route.template_id is expected_template
    assert route.identity_target is not IdentityState.CONFIRMED


def test_kinship_override_beats_untrusted_third_party_classification() -> None:
    route = route_speaker_utterance(
        "bhai bol raha hoon",
        proposed_intent=PreConfirmationIntent.THIRD_PARTY,
    )

    assert route.kind is SpeakerRouteKind.CLARIFY
    assert route.identity_target is None


def test_typed_classification_can_route_non_ambiguous_language_but_not_confirm() -> None:
    route = route_speaker_utterance(
        "I am calling from his family",
        proposed_intent=PreConfirmationIntent.THIRD_PARTY,
    )

    assert route.kind is SpeakerRouteKind.ENTER_THIRD_PARTY
    assert route.identity_target is IdentityState.THIRD_PARTY


def test_three_pushes_use_all_non_identical_reviewed_templates() -> None:
    session = ThirdPartySession()
    replies = [session.next_hold() for _ in range(3)]

    assert [reply.push_number for reply in replies] == [1, 2, 3]
    assert [reply.template_variant for reply in replies] == [0, 1, 2]
    assert tuple(reply.text for reply in replies) == TEMPLATE_BANK[TemplateId.THIRD_PARTY_CALLBACK]
    assert len({reply.text for reply in replies}) == 3
    with pytest.raises(ThirdPartyResponsesIncomplete):
        session.next_hold()


def test_all_three_holds_clear_real_output_guard_without_block_events() -> None:
    session = ThirdPartySession()
    context = OutputGuardContext.from_case(
        RAKESH_CASE,
        identity_state=IdentityState.THIRD_PARTY,
        promise_state=PromiseState.NONE,
    )
    blocked: list[object] = []

    guarded = [
        guard_for_tts(session.next_hold().text, context, record_block=blocked.append)
        for _ in range(3)
    ]

    assert all(result.allowed for result in guarded)
    assert blocked == []


def test_callback_payload_contains_no_actual_seeded_account_value() -> None:
    payload = ContentFreeCallbackPayload().as_tool_payload()
    protected = protected_case_values(RAKESH_CASE)

    assert payload_is_content_free(payload, protected_values=protected)
    rendered = repr(payload).casefold()
    assert all(value not in rendered for value in protected)
    assert set(payload) == {"callback_kind", "message_code"}


@pytest.mark.parametrize(
    "malicious_payload",
    [
        {
            "callback_kind": "borrower_reconnect",
            "message_code": "vachan_reconnect_only",
            "amount_minor": 4_738_200,
        },
        {
            "callback_kind": "borrower_reconnect",
            "message_code": "Sahyog Finance (Mock)",
        },
        {
            "callback_kind": "borrower_reconnect",
            "message_code": "vachan_reconnect_only",
            "case_id": "case-rakesh-001",
        },
    ],
)
def test_payload_inspector_rejects_extra_or_protected_fields(
    malicious_payload: Mapping[str, object],
) -> None:
    assert not payload_is_content_free(
        malicious_payload,
        protected_values=protected_case_values(RAKESH_CASE),
    )


def test_callback_authorization_is_recorded_before_side_effect_and_closes_business_path() -> None:
    session = ThirdPartySession()
    for _ in range(3):
        session.next_hold()

    order: list[str] = []
    decisions: list[ToolDecision] = []
    scheduled: list[Mapping[str, str]] = []

    def record(decision: ToolDecision) -> None:
        order.append("decision")
        decisions.append(decision)

    def schedule(payload: Mapping[str, str]) -> None:
        order.append("schedule")
        scheduled.append(payload)

    outcome = session.complete(
        identity_state=IdentityState.THIRD_PARTY,
        protected_values=protected_case_values(RAKESH_CASE),
        record_decision=record,
        schedule_callback=schedule,
    )

    assert order == ["decision", "schedule"]
    assert len(decisions) == 1
    assert decisions[0].tool is ToolName.SCHEDULE_CONTENT_FREE_CALLBACK
    assert decisions[0].allowed
    assert scheduled == [ContentFreeCallbackPayload().as_tool_payload()]
    assert outcome.disposition is Disposition.CALLBACK_THIRD_PARTY
    assert outcome.response_count == 3
    with pytest.raises(ThirdPartyAlreadyCompleted):
        session.complete(
            identity_state=IdentityState.THIRD_PARTY,
            protected_values=(),
            record_decision=record,
            schedule_callback=schedule,
        )
    assert len(scheduled) == 1


def test_callback_cannot_run_before_third_party_state_or_three_holds() -> None:
    early = ThirdPartySession()
    with pytest.raises(ThirdPartyResponsesIncomplete):
        early.complete(
            identity_state=IdentityState.THIRD_PARTY,
            protected_values=(),
            record_decision=lambda _: None,
            schedule_callback=lambda _: None,
        )

    wrong_identity = ThirdPartySession()
    for _ in range(3):
        wrong_identity.next_hold()
    decisions: list[ToolDecision] = []
    scheduled: list[Mapping[str, str]] = []

    with pytest.raises(ToolPermissionDenied):
        wrong_identity.complete(
            identity_state=IdentityState.UNVERIFIED,
            protected_values=protected_case_values(RAKESH_CASE),
            record_decision=decisions.append,
            schedule_callback=scheduled.append,
        )

    assert len(decisions) == 1
    assert not decisions[0].allowed
    assert scheduled == []
