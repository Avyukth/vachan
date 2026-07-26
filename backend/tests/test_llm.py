"""Bounded two-role Sarvam LLM integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import httpx
import pytest

from app.actions import Intent, PreConfirmationIntent, PreConfirmationTemplate
from app.context_isolation import build_llm_context
from app.llm import (
    MAX_RESPONSE_TOKENS,
    POSTCONFIRMATION_HOLD_LINE,
    SARVAM_CHAT_MODEL,
    CallLLMBudget,
    DecisionSource,
    LLMBudgetExhausted,
    LLMFailureCategory,
    LLMUnavailable,
    SarvamChatClient,
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


def test_default_budget_bounds_six_live_reasoning_completions() -> None:
    budget = CallLLMBudget()

    for _ in range(6):
        budget.reserve(MAX_RESPONSE_TOKENS)

    assert MAX_RESPONSE_TOKENS == 4_096
    assert budget.requests_used == 6
    assert budget.tokens_reserved == 24_576
    with pytest.raises(LLMBudgetExhausted, match="budget is exhausted"):
        budget.reserve(MAX_RESPONSE_TOKENS)


async def _chat_outcome(
    handler,
) -> str:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        return await SarvamChatClient(
            "credential-must-not-leak",
            http_client=http_client,
        ).complete(
            [{"role": "user", "content": "prompt-must-not-leak"}],
            timeout_seconds=1,
            max_tokens=32,
        )


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, LLMFailureCategory.AUTHENTICATION),
        (403, LLMFailureCategory.AUTHENTICATION),
        (400, LLMFailureCategory.REQUEST_REJECTED),
        (429, LLMFailureCategory.RATE_LIMITED),
        (500, LLMFailureCategory.UPSTREAM),
        (503, LLMFailureCategory.UPSTREAM),
    ],
)
def test_chat_http_failures_expose_only_safe_categories(
    status: int,
    category: LLMFailureCategory,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"secret_response_body": "must-not-leak"},
        )

    with pytest.raises(LLMUnavailable) as captured:
        asyncio.run(_chat_outcome(handler))

    assert captured.value.category is category
    rendered = repr(captured.value)
    assert "credential-must-not-leak" not in rendered
    assert "prompt-must-not-leak" not in rendered
    assert "secret_response_body" not in rendered


@pytest.mark.parametrize(
    ("error_factory", "category"),
    [
        (
            lambda request: httpx.ReadTimeout("private timeout detail", request=request),
            LLMFailureCategory.TIMEOUT,
        ),
        (
            lambda request: httpx.ConnectError("private transport detail", request=request),
            LLMFailureCategory.TRANSPORT,
        ),
    ],
)
def test_chat_network_failures_expose_only_safe_categories(
    error_factory,
    category: LLMFailureCategory,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise error_factory(request)

    with pytest.raises(LLMUnavailable) as captured:
        asyncio.run(_chat_outcome(handler))

    assert captured.value.category is category
    assert "private" not in repr(captured.value)


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (
            httpx.Response(200, content=b"response-body-must-not-leak"),
            LLMFailureCategory.INVALID_RESPONSE,
        ),
        (
            httpx.Response(
                200,
                json={"secret_response_body": "must-not-leak"},
            ),
            LLMFailureCategory.INVALID_RESPONSE,
        ),
        (
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "  "}}]},
            ),
            LLMFailureCategory.EMPTY_CONTENT,
        ),
    ],
)
def test_chat_invalid_responses_expose_only_safe_categories(
    response: httpx.Response,
    category: LLMFailureCategory,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return response

    with pytest.raises(LLMUnavailable) as captured:
        asyncio.run(_chat_outcome(handler))

    assert captured.value.category is category
    rendered = repr(captured.value)
    assert "response-body-must-not-leak" not in rendered
    assert "secret_response_body" not in rendered


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
