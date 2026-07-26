"""Deterministic, content-free third-party callback path."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.actions import PreConfirmationIntent
from app.contracts import Disposition
from app.seeds import MockCaseSeed
from app.states import CallState, IdentityState, PromiseState
from app.templates import TemplateId, render_template
from app.tools import (
    PermissionContext,
    ToolDecision,
    ToolName,
    authorize_tool,
)

_SPACE_OR_PUNCTUATION = re.compile(r"[^\w\u0900-\u097f]+", re.UNICODE)
_THIRD_PARTY_PATTERNS: Final = (
    re.compile(r"\b(?:main|mai)\s+unki\s+(?:wife|patni)\s+(?:hoon|hun|hu)\b"),
    re.compile(r"\b(?:wo|woh|vo)\s+ghar\s+pe\s+nahi\b"),
    re.compile(r"\bi\s+am\s+his\s+wife\b"),
    re.compile(r"\b(?:he|she)\s+is\s+not\s+(?:home|here)\b"),
    re.compile(r"मैं\s+उनकी\s+पत्नी\s+हूँ"),
    re.compile(r"वो\s+घर\s+पे\s+नहीं"),
)
_BORROWER_CLAIM_PATTERNS: Final = (
    re.compile(r"\b(?:main|mai)\s+rakesh\b"),
    re.compile(r"\brakesh\s+bol\s+raha\s+(?:hoon|hun|hu)\b"),
    re.compile(r"\bthis\s+is\s+rakesh\b"),
    re.compile(r"\bi\s+am\s+rakesh\b"),
    re.compile(r"मैं\s+राकेश"),
)
_PASSIVE_AMBIGUOUS_PHRASES: Final = frozenset(
    {
        "haan boliye",
        "han boliye",
        "yes speak",
        "boliye",
    }
)
_KINSHIP_TERMS: Final = frozenset({"bhai", "didi", "behen", "sister", "brother"})

CALLBACK_PAYLOAD_KEYS: Final = frozenset({"callback_kind", "message_code"})
CALLBACK_KIND: Final = "borrower_reconnect"
CALLBACK_MESSAGE_CODE: Final = "vachan_reconnect_only"
_FORBIDDEN_CALLBACK_KEY_PARTS: Final = frozenset(
    {
        "account",
        "amount",
        "balance",
        "case",
        "debt",
        "due",
        "emi",
        "lender",
        "loan",
        "phone",
        "reason",
        "reference",
    }
)


class SpeakerRouteKind(StrEnum):
    """Code-owned routing decisions before identity confirmation."""

    ASK_FOR_BORROWER = "ASK_FOR_BORROWER"
    CLARIFY = "CLARIFY"
    START_VERIFICATION = "START_VERIFICATION"
    ENTER_THIRD_PARTY = "ENTER_THIRD_PARTY"


@dataclass(frozen=True, slots=True)
class SpeakerRoute:
    """A safe template and optional identity transition proposed by code."""

    kind: SpeakerRouteKind
    template_id: TemplateId
    identity_target: IdentityState | None
    reason_code: str


def normalize_speaker_utterance(utterance: str) -> str:
    """Normalize only enough to apply conservative safety overrides."""
    normalized = unicodedata.normalize("NFKC", utterance).casefold()
    return " ".join(_SPACE_OR_PUNCTUATION.sub(" ", normalized).split())


def route_speaker_utterance(
    utterance: str,
    *,
    proposed_intent: PreConfirmationIntent = PreConfirmationIntent.OTHER,
) -> SpeakerRoute:
    """Resolve speaker language without ever granting confirmed identity.

    Exact ambiguity/kinship overrides win over the model's classification.
    The model may route a non-ambiguous utterance into verification or the
    third-party path, but only the verification comparator can later grant
    ``CONFIRMED``.
    """
    normalized = normalize_speaker_utterance(utterance)
    if not normalized:
        return SpeakerRoute(
            kind=SpeakerRouteKind.CLARIFY,
            template_id=TemplateId.CLARIFY,
            identity_target=None,
            reason_code="speaker_silence_or_garble",
        )
    if normalized in _PASSIVE_AMBIGUOUS_PHRASES:
        return SpeakerRoute(
            kind=SpeakerRouteKind.ASK_FOR_BORROWER,
            template_id=TemplateId.ASK_FOR_BORROWER,
            identity_target=None,
            reason_code="passive_answer_is_not_identity",
        )
    if _KINSHIP_TERMS.intersection(normalized.split()):
        return SpeakerRoute(
            kind=SpeakerRouteKind.CLARIFY,
            template_id=TemplateId.CLARIFY,
            identity_target=None,
            reason_code="kinship_term_is_ambiguous",
        )
    if any(pattern.search(normalized) for pattern in _THIRD_PARTY_PATTERNS):
        return SpeakerRoute(
            kind=SpeakerRouteKind.ENTER_THIRD_PARTY,
            template_id=TemplateId.THIRD_PARTY_CALLBACK,
            identity_target=IdentityState.THIRD_PARTY,
            reason_code="explicit_third_party_self_identification",
        )
    if any(pattern.search(normalized) for pattern in _BORROWER_CLAIM_PATTERNS):
        return SpeakerRoute(
            kind=SpeakerRouteKind.START_VERIFICATION,
            template_id=TemplateId.VERIFY_REQUEST,
            identity_target=IdentityState.VERIFYING,
            reason_code="borrower_claim_requires_fresh_verification",
        )
    if proposed_intent is PreConfirmationIntent.THIRD_PARTY:
        return SpeakerRoute(
            kind=SpeakerRouteKind.ENTER_THIRD_PARTY,
            template_id=TemplateId.THIRD_PARTY_CALLBACK,
            identity_target=IdentityState.THIRD_PARTY,
            reason_code="typed_third_party_classification",
        )
    if proposed_intent is PreConfirmationIntent.BORROWER_PRESENT:
        return SpeakerRoute(
            kind=SpeakerRouteKind.START_VERIFICATION,
            template_id=TemplateId.VERIFY_REQUEST,
            identity_target=IdentityState.VERIFYING,
            reason_code="typed_borrower_claim_requires_verification",
        )
    return SpeakerRoute(
        kind=SpeakerRouteKind.CLARIFY,
        template_id=TemplateId.CLARIFY,
        identity_target=None,
        reason_code="speaker_identity_unresolved",
    )


@dataclass(frozen=True, slots=True)
class ContentFreeCallbackPayload:
    """The complete tool payload; it has no channel for account data."""

    callback_kind: str = CALLBACK_KIND
    message_code: str = CALLBACK_MESSAGE_CODE

    def as_tool_payload(self) -> dict[str, str]:
        return {
            "callback_kind": self.callback_kind,
            "message_code": self.message_code,
        }


def protected_case_values(case: MockCaseSeed) -> tuple[str, ...]:
    """Return actual seeded values used only by payload-inspection tests/gates."""
    account = case.account
    verification = case.verification
    values: list[str] = [
        case.case_id,
        case.borrower_display_name,
        account.lender_name,
        str(account.outstanding_minor),
        str(verification.birth_day),
        str(verification.birth_month),
        verification.reference_last4,
    ]
    for installment in account.emi_schedule:
        values.extend(
            (
                installment.due_date.isoformat(),
                str(installment.amount_minor),
                installment.status,
            )
        )
    return tuple(value.casefold() for value in values if value)


def payload_is_content_free(
    payload: Mapping[str, object],
    *,
    protected_values: Iterable[str] = (),
) -> bool:
    """Inspect the actual callback payload, rather than trusting a caller flag."""
    if set(payload) != CALLBACK_PAYLOAD_KEYS:
        return False
    if payload != ContentFreeCallbackPayload().as_tool_payload():
        return False

    for key in payload:
        normalized_key = key.casefold()
        if any(fragment in normalized_key for fragment in _FORBIDDEN_CALLBACK_KEY_PARTS):
            return False

    rendered = repr(dict(payload)).casefold()
    return not any(value.casefold() in rendered for value in protected_values if value)


@dataclass(frozen=True, slots=True)
class ThirdPartyReply:
    """One reviewed hold line selected without model-authored prose."""

    push_number: int
    template_variant: int
    text: str


@dataclass(frozen=True, slots=True)
class ThirdPartyOutcome:
    """Controller-ready terminal facts after the callback side effect succeeds."""

    disposition: Disposition
    callback_payload: ContentFreeCallbackPayload
    tool_decision: ToolDecision
    response_count: int


class ThirdPartyPathError(RuntimeError):
    """Base class for deterministic path-lifecycle failures."""


class ThirdPartyResponsesIncomplete(ThirdPartyPathError):
    """Raised if code tries to schedule before all reviewed holds were used."""


class ThirdPartyAlreadyCompleted(ThirdPartyPathError):
    """Raised if a duplicate event tries to schedule the callback twice."""


DecisionRecorder = Callable[[ToolDecision], None]
CallbackScheduler = Callable[[Mapping[str, str]], None]


class ThirdPartySession:
    """Three safe holds followed by one authorized, content-free callback."""

    def __init__(self) -> None:
        self._response_count = 0
        self._completed = False

    @property
    def response_count(self) -> int:
        return self._response_count

    def next_hold(self) -> ThirdPartyReply:
        """Return each reviewed variant once; never generate a fourth response."""
        if self._completed:
            raise ThirdPartyAlreadyCompleted("Third-party callback path is already complete.")
        variant_count = 3
        if self._response_count >= variant_count:
            raise ThirdPartyResponsesIncomplete(
                "All safe holds were used; schedule the callback and close the call."
            )
        variant = self._response_count
        self._response_count += 1
        return ThirdPartyReply(
            push_number=self._response_count,
            template_variant=variant,
            text=render_template(TemplateId.THIRD_PARTY_CALLBACK, variant=variant),
        )

    def complete(
        self,
        *,
        identity_state: IdentityState,
        protected_values: Iterable[str],
        record_decision: DecisionRecorder,
        schedule_callback: CallbackScheduler,
    ) -> ThirdPartyOutcome:
        """Authorize, schedule once, then return the only valid disposition."""
        if self._completed:
            raise ThirdPartyAlreadyCompleted("Third-party callback path is already complete.")
        if self._response_count != 3:
            raise ThirdPartyResponsesIncomplete(
                "Three safe callback holds must precede scheduling."
            )

        payload = ContentFreeCallbackPayload()
        tool_payload = payload.as_tool_payload()
        decision = authorize_tool(
            ToolName.SCHEDULE_CONTENT_FREE_CALLBACK,
            PermissionContext(
                identity_state=identity_state,
                call_state=CallState.ACTIVE,
                promise_state=PromiseState.NONE,
                callback_payload_is_content_free=payload_is_content_free(
                    tool_payload,
                    protected_values=protected_values,
                ),
            ),
            record_decision,
        )
        schedule_callback(tool_payload)
        self._completed = True
        return ThirdPartyOutcome(
            disposition=Disposition.CALLBACK_THIRD_PARTY,
            callback_payload=payload,
            tool_decision=decision,
            response_count=self._response_count,
        )
