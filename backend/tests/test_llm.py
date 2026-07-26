"""Bounded two-role Sarvam LLM integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pytest

from app.actions import Intent, PreConfirmationIntent, PreConfirmationTemplate
from app.context_isolation import build_llm_context
from app.llm import (
    POSTCONFIRMATION_HOLD_LINE,
    SARVAM_CHAT_MODEL,
    CallLLMBudget,
    DecisionSource,
    LLMUnavailable,
    VachanLLMSession,
    deterministic_preconfirmation_intent,
)
from app.seeds import RAKESH_CASE
from app.states import CallState, IdentityState, PromiseState


@dataclass(slots=True)
class ScriptedCompletion:
    outcomes: list[str | Exception]
    requests: list[tuple[dict[str, str], ...]] = field(default_factory=list)

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        timeout_seconds: float,
        max_tokens: int,
    ) -> str:
        self.requests.append(tuple(dict(message) for message in messages))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def context(
    utterance: str,
    *,
    identity: IdentityState,
    promise: PromiseState = PromiseState.NONE,
):
    return build_llm_context(
        call_state=CallState.ACTIVE,
        identity_state=identity,
        promise_state=promise,
        case=RAKESH_CASE,
        current_utterance=utterance,
    )


def test_model_classifies_hostile_scam_question_to_fixed_template() -> None:
    client = ScriptedCompletion(['{"intent":"scam_concern","response_draft":"unsafe"}'])
    session = VachanLLMSession(client)

    decision = asyncio.run(
        session.classify_preconfirmation(
            context("scam hai kya?", identity=IdentityState.UNVERIFIED),
            borrower_display_name=RAKESH_CASE.borrower_display_name,
        )
    )

    assert decision.source is DecisionSource.MODEL
    assert decision.validation.template is PreConfirmationTemplate.INTRO_ANTISCAM
    assert set(decision.validation.classification.model_dump()) == {"intent"}
    assert client.requests[0][-1]["content"] == "scam hai kya?"


def test_timeout_during_spouse_exchange_uses_deterministic_fallback() -> None:
    client = ScriptedCompletion([LLMUnavailable("offline")])
    session = VachanLLMSession(client)

    decision = asyncio.run(
        session.classify_preconfirmation(
            context("main unki wife hoon", identity=IdentityState.UNVERIFIED),
            borrower_display_name=RAKESH_CASE.borrower_display_name,
        )
    )

    assert decision.source is DecisionSource.DETERMINISTIC_FALLBACK
    assert decision.validation.classification.intent is PreConfirmationIntent.THIRD_PARTY
    assert decision.validation.template is PreConfirmationTemplate.THIRD_PARTY_CALLBACK


@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("main unki wife hoon", PreConfirmationIntent.THIRD_PARTY),
        ("wo ghar pe nahi hai", PreConfirmationIntent.THIRD_PARTY),
        ("scam hai kya", PreConfirmationIntent.SCAM_CONCERN),
        ("Rakesh bol raha hoon", PreConfirmationIntent.BORROWER_PRESENT),
        ("haan boliye", PreConfirmationIntent.BORROWER_PRESENT),
        ("bhai bol raha hoon", PreConfirmationIntent.CLARIFICATION),
        ("", PreConfirmationIntent.CLARIFICATION),
    ],
)
def test_fallback_ambiguity_vectors(
    utterance: str,
    expected: PreConfirmationIntent,
) -> None:
    assert (
        deterministic_preconfirmation_intent(
            utterance,
            borrower_display_name=RAKESH_CASE.borrower_display_name,
        )
        is expected
    )


def test_malformed_model_json_falls_back_without_crashing() -> None:
    session = VachanLLMSession(ScriptedCompletion(['{"intent":']))

    decision = asyncio.run(
        session.classify_preconfirmation(
            context("please repeat", identity=IdentityState.UNVERIFIED),
            borrower_display_name=RAKESH_CASE.borrower_display_name,
        )
    )

    assert decision.source is DecisionSource.DETERMINISTIC_FALLBACK
    assert decision.validation.template is PreConfirmationTemplate.CLARIFY


def test_valid_postconfirmation_action_is_state_validated() -> None:
    client = ScriptedCompletion(
        [
            '{"intent":"offer_promise","amount_minor":150000,'
            '"date_phrase":"Friday","response_draft":"draft"}'
        ]
    )
    session = VachanLLMSession(client)
    holds: list[str] = []

    async def exercise():
        return await session.propose_postconfirmation(
            context("pandrah sau Friday", identity=IdentityState.CONFIRMED),
            call_state=CallState.ACTIVE,
            identity_state=IdentityState.CONFIRMED,
            promise_state=PromiseState.NONE,
            speak_hold=lambda line: _capture(holds, line),
        )

    decision = asyncio.run(exercise())

    assert decision.degraded is False
    assert decision.attempts == 1
    assert decision.validation.accepted is True
    assert decision.validation.action.intent is Intent.OFFER_PROMISE
    assert decision.validation.action.amount_minor == 150_000
    assert holds == []
    assert client.requests[0][1]["content"].startswith('{"borrower_display_name"')


async def _capture(items: list[str], value: str) -> None:
    items.append(value)


def test_postconfirmation_failure_speaks_hold_once_then_retry_succeeds() -> None:
    client = ScriptedCompletion([LLMUnavailable("first"), '{"intent":"deny"}'])
    session = VachanLLMSession(client)
    holds: list[str] = []

    decision = asyncio.run(
        session.propose_postconfirmation(
            context("nahi", identity=IdentityState.CONFIRMED),
            call_state=CallState.ACTIVE,
            identity_state=IdentityState.CONFIRMED,
            promise_state=PromiseState.READ_BACK,
            speak_hold=lambda line: _capture(holds, line),
        )
    )

    assert decision.attempts == 2
    assert decision.degraded is False
    assert decision.hold_spoken is True
    assert holds == [POSTCONFIRMATION_HOLD_LINE]
    assert decision.validation.action.intent is Intent.DENY


def test_two_postconfirmation_failures_return_degraded_safe_action() -> None:
    client = ScriptedCompletion([LLMUnavailable("first"), LLMUnavailable("second")])
    session = VachanLLMSession(client)
    holds: list[str] = []

    decision = asyncio.run(
        session.propose_postconfirmation(
            context("offer", identity=IdentityState.CONFIRMED),
            call_state=CallState.ACTIVE,
            identity_state=IdentityState.CONFIRMED,
            promise_state=PromiseState.NONE,
            speak_hold=lambda line: _capture(holds, line),
        )
    )

    assert decision.degraded is True
    assert decision.validation.action.intent is Intent.OTHER
    assert holds == [POSTCONFIRMATION_HOLD_LINE]


def test_budget_exhaustion_fails_preconfirmation_to_keyword_classifier() -> None:
    session = VachanLLMSession(
        ScriptedCompletion(['{"intent":"other"}']),
        budget=CallLLMBudget(request_limit=0),
    )

    decision = asyncio.run(
        session.classify_preconfirmation(
            context("fraud call?", identity=IdentityState.UNVERIFIED),
            borrower_display_name=RAKESH_CASE.borrower_display_name,
        )
    )

    assert decision.source is DecisionSource.DETERMINISTIC_FALLBACK
    assert decision.validation.template is PreConfirmationTemplate.INTRO_ANTISCAM
    assert SARVAM_CHAT_MODEL == "sarvam-30b"


def test_pre_and_post_roles_reject_wrong_context_side() -> None:
    session = VachanLLMSession(ScriptedCompletion([]))
    with pytest.raises(ValueError, match="pre-confirmation"):
        asyncio.run(
            session.classify_preconfirmation(
                context("offer", identity=IdentityState.CONFIRMED),
                borrower_display_name=RAKESH_CASE.borrower_display_name,
            )
        )
    with pytest.raises(ValueError, match="post-confirmation"):
        asyncio.run(
            session.propose_postconfirmation(
                context("offer", identity=IdentityState.UNVERIFIED),
                call_state=CallState.ACTIVE,
                identity_state=IdentityState.UNVERIFIED,
                promise_state=PromiseState.NONE,
                speak_hold=lambda line: _capture([], line),
            )
        )
