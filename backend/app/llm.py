"""Bounded Sarvam chat integration for Vachan's two model roles."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import httpx

from app.actions import (
    ActionValidationResult,
    PreConfirmationIntent,
    PreConfirmationValidationResult,
    validate_llm_action,
    validate_preconfirmation_classification,
)
from app.context_isolation import LLMContext
from app.states import CallState, IdentityState, PromiseState

SARVAM_CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_CHAT_MODEL = "sarvam-30b"
SARVAM_CHAT_TEMPERATURE = 0.1
PRECONFIRMATION_TIMEOUT_SECONDS = 2.0
POSTCONFIRMATION_TIMEOUT_SECONDS = 4.0
# Sarvam's reasoning tokens count against this limit even though only ``content``
# reaches the controller. Live API validation showed limits through 1536 could
# still truncate before the compact JSON answer for the real isolated prompt.
# 4096 preserves a hard ceiling while allowing the model to stop naturally.
MAX_RESPONSE_TOKENS = 4_096
POSTCONFIRMATION_HOLD_LINE = "एक सेकंड दीजिए।"


class LLMIntegrationError(RuntimeError):
    """Safe base error that never includes prompts, drafts, or credentials."""


class LLMFailureCategory(StrEnum):
    """Allowlisted upstream failure categories safe for logs and evidence."""

    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    REQUEST_REJECTED = "request_rejected"
    UPSTREAM = "upstream"
    INVALID_RESPONSE = "invalid_response"
    EMPTY_CONTENT = "empty_content"


class LLMUnavailable(LLMIntegrationError):
    """The Sarvam chat dependency failed or returned an invalid envelope."""

    def __init__(
        self,
        message: str,
        *,
        category: LLMFailureCategory = LLMFailureCategory.UNAVAILABLE,
    ) -> None:
        super().__init__(message)
        self.category = category

    @property
    def safe_reason_code(self) -> str:
        """Return an allowlisted reason that contains no upstream response data."""

        return f"llm_{self.category.value}"


class LLMBudgetExhausted(LLMIntegrationError):
    """The call-scoped request budget is exhausted."""


class DecisionSource(StrEnum):
    MODEL = "model"
    DETERMINISTIC_FALLBACK = "deterministic_fallback"


class CompletionClient(Protocol):
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        timeout_seconds: float,
        max_tokens: int,
    ) -> str: ...


@dataclass(slots=True)
class CallLLMBudget:
    """A small deterministic request/token allowance owned by one call."""

    request_limit: int = 6
    token_limit: int = 24_576
    requests_used: int = 0
    tokens_reserved: int = 0

    def reserve(self, max_tokens: int) -> None:
        if (
            self.requests_used >= self.request_limit
            or self.tokens_reserved + max_tokens > self.token_limit
        ):
            raise LLMBudgetExhausted("call-scoped LLM budget is exhausted")
        self.requests_used += 1
        self.tokens_reserved += max_tokens


@dataclass(frozen=True, slots=True)
class PreConfirmationDecision:
    validation: PreConfirmationValidationResult
    source: DecisionSource


@dataclass(frozen=True, slots=True)
class PostConfirmationDecision:
    validation: ActionValidationResult
    attempts: int
    hold_spoken: bool
    degraded: bool


HoldSpeaker = Callable[[str], Awaitable[None]]


class SarvamChatClient:
    """OpenAI-compatible Sarvam chat boundary with bounded response parsing."""

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("a non-empty backend Sarvam API key is required")
        self._api_key = api_key
        self._http_client = http_client

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        timeout_seconds: float,
        max_tokens: int,
    ) -> str:
        if timeout_seconds <= 0 or max_tokens <= 0:
            raise ValueError("timeout_seconds and max_tokens must be positive")
        payload = {
            "model": SARVAM_CHAT_MODEL,
            "messages": [dict(message) for message in messages],
            "temperature": SARVAM_CHAT_TEMPERATURE,
            "max_tokens": max_tokens,
        }
        headers = {
            "api-subscription-key": self._api_key,
            "content-type": "application/json",
        }
        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    SARVAM_CHAT_URL,
                    headers=headers,
                    json=payload,
                    timeout=timeout_seconds,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        SARVAM_CHAT_URL,
                        headers=headers,
                        json=payload,
                        timeout=timeout_seconds,
                    )
        except httpx.TimeoutException as error:
            raise LLMUnavailable(
                "Sarvam chat exceeded its bounded deadline",
                category=LLMFailureCategory.TIMEOUT,
            ) from error
        except httpx.TransportError as error:
            raise LLMUnavailable(
                "Sarvam chat transport is unavailable",
                category=LLMFailureCategory.TRANSPORT,
            ) from error
        except httpx.HTTPError as error:
            raise LLMUnavailable(
                "Sarvam chat request failed",
                category=LLMFailureCategory.UNAVAILABLE,
            ) from error

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status in {401, 403}:
                category = LLMFailureCategory.AUTHENTICATION
            elif status == 429:
                category = LLMFailureCategory.RATE_LIMITED
            elif status >= 500:
                category = LLMFailureCategory.UPSTREAM
            else:
                category = LLMFailureCategory.REQUEST_REJECTED
            raise LLMUnavailable(
                "Sarvam chat rejected the request",
                category=category,
            ) from error

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMUnavailable(
                "Sarvam chat returned an invalid response",
                category=LLMFailureCategory.INVALID_RESPONSE,
            ) from error
        if not isinstance(content, str):
            raise LLMUnavailable(
                "Sarvam chat returned an invalid response",
                category=LLMFailureCategory.INVALID_RESPONSE,
            )
        if not content.strip():
            raise LLMUnavailable(
                "Sarvam chat returned empty content",
                category=LLMFailureCategory.EMPTY_CONTENT,
            )
        return content


def _normalized_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[^\w\u0900-\u097f]+", " ", value).split())


def deterministic_preconfirmation_intent(
    utterance: str,
    *,
    borrower_display_name: str,
) -> PreConfirmationIntent:
    """Fail-closed keyword fallback used only when chat is unavailable."""

    text = _normalized_text(utterance)
    if not text:
        return PreConfirmationIntent.CLARIFICATION
    third_party_markers = (
        "wife",
        "patni",
        "unki patni",
        "unki wife",
        "ghar pe nahi",
        "ghar par nahi",
        "पत्नी",
        "वाइफ",
        "घर पे नहीं",
        "घर पर नहीं",
    )
    if any(marker in text for marker in third_party_markers):
        return PreConfirmationIntent.THIRD_PARTY
    if any(marker in text for marker in ("scam", "fraud", "kaun", "स्कैम", "फ्रॉड", "कौन")):
        return PreConfirmationIntent.SCAM_CONCERN

    first_name = _normalized_text(borrower_display_name).split()[0]
    if first_name and re.search(rf"\b{re.escape(first_name)}\b", text):
        return PreConfirmationIntent.BORROWER_PRESENT
    if text in {"haan boliye", "हां बोलिए", "हाँ बोलिए"}:
        return PreConfirmationIntent.BORROWER_PRESENT
    return PreConfirmationIntent.CLARIFICATION


def _last_user_utterance(context: LLMContext) -> str:
    for message in reversed(context.messages):
        if message.role.value == "user":
            return message.content
    raise ValueError("LLM context has no user utterance")


@dataclass(slots=True)
class VachanLLMSession:
    """Call-scoped orchestration for classification and typed proposals."""

    client: CompletionClient
    budget: CallLLMBudget = field(default_factory=CallLLMBudget)

    async def _complete(self, context: LLMContext, *, timeout_seconds: float) -> str:
        self.budget.reserve(MAX_RESPONSE_TOKENS)
        try:
            return await asyncio.wait_for(
                self.client.complete(
                    context.as_api_messages(),
                    timeout_seconds=timeout_seconds,
                    max_tokens=MAX_RESPONSE_TOKENS,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError as error:
            raise LLMUnavailable(
                "Sarvam chat exceeded its bounded deadline",
                category=LLMFailureCategory.TIMEOUT,
            ) from error

    async def classify_preconfirmation(
        self,
        context: LLMContext,
        *,
        borrower_display_name: str,
    ) -> PreConfirmationDecision:
        if context.contains_private_account_context:
            raise ValueError("pre-confirmation classification cannot receive private context")
        utterance = _last_user_utterance(context)
        try:
            raw = await self._complete(
                context,
                timeout_seconds=PRECONFIRMATION_TIMEOUT_SECONDS,
            )
            validation = validate_preconfirmation_classification(raw)
            if validation.accepted:
                return PreConfirmationDecision(validation, DecisionSource.MODEL)
        except (LLMIntegrationError, LLMBudgetExhausted):
            pass

        fallback = deterministic_preconfirmation_intent(
            utterance,
            borrower_display_name=borrower_display_name,
        )
        return PreConfirmationDecision(
            validate_preconfirmation_classification({"intent": fallback.value}),
            DecisionSource.DETERMINISTIC_FALLBACK,
        )

    async def propose_postconfirmation(
        self,
        context: LLMContext,
        *,
        call_state: CallState,
        identity_state: IdentityState,
        promise_state: PromiseState,
        speak_hold: HoldSpeaker,
    ) -> PostConfirmationDecision:
        if (
            identity_state is not IdentityState.CONFIRMED
            or not context.contains_private_account_context
        ):
            raise ValueError("post-confirmation actions require confirmed private context")

        hold_spoken = False
        for attempt in (1, 2):
            try:
                raw = await self._complete(
                    context,
                    timeout_seconds=POSTCONFIRMATION_TIMEOUT_SECONDS,
                )
                return PostConfirmationDecision(
                    validation=validate_llm_action(
                        raw,
                        identity_state=identity_state,
                        promise_state=promise_state,
                        call_state=call_state,
                    ),
                    attempts=attempt,
                    hold_spoken=hold_spoken,
                    degraded=False,
                )
            except (LLMIntegrationError, LLMBudgetExhausted):
                if attempt == 1:
                    await speak_hold(POSTCONFIRMATION_HOLD_LINE)
                    hold_spoken = True

        safe = validate_llm_action(
            json.dumps({"intent": "other"}),
            identity_state=identity_state,
            promise_state=promise_state,
            call_state=call_state,
        )
        return PostConfirmationDecision(
            validation=safe,
            attempts=2,
            hold_spoken=hold_spoken,
            degraded=True,
        )
