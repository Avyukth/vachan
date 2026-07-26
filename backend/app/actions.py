"""Typed, state-aware boundary for untrusted LLM action proposals."""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError

CLARIFICATION_TEMPLATE = "clarification"
CONFIRMED_IDENTITY = "CONFIRMED"
READ_BACK_PROMISE = "READ_BACK"
HANDOVER_CALL_STATES = frozenset({"ACTIVE", "DEGRADED"})


class Intent(StrEnum):
    """The only intents the language model may propose."""

    OFFER_PROMISE = "offer_promise"
    CORRECT_PROMISE = "correct_promise"
    CONFIRM = "confirm"
    DENY = "deny"
    HANDOVER = "handover"
    REQUEST_HUMAN = "request_human"
    OTHER = "other"


CONFIRMED_ONLY_INTENTS = frozenset({Intent.OFFER_PROMISE, Intent.CORRECT_PROMISE, Intent.CONFIRM})


class LLMAction(BaseModel):
    """A language-model proposal; never an authorization or database command."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    intent: Intent
    amount_minor: StrictInt | None = None
    date_phrase: str | None = None
    response_draft: str = ""


class ActionValidationResult(BaseModel):
    """The safe result consumed by the deterministic dialogue controller."""

    model_config = ConfigDict(frozen=True)

    action: LLMAction
    accepted: bool
    rejected_fields: tuple[str, ...] = ()
    handover_requested: bool = False
    response_template: str | None = None


def _state_name(state: object) -> str:
    """Normalize a string or Enum-like state without importing state-machine code."""
    value = getattr(state, "value", state)
    return str(value).upper()


def _safe_other(*, rejected_fields: tuple[str, ...]) -> ActionValidationResult:
    return ActionValidationResult(
        action=LLMAction(intent=Intent.OTHER),
        accepted=False,
        rejected_fields=rejected_fields,
        response_template=CLARIFICATION_TEMPLATE,
    )


def _parse_action(raw_action: str | bytes | Mapping[str, Any] | LLMAction) -> LLMAction:
    if isinstance(raw_action, LLMAction):
        return raw_action
    payload = json.loads(raw_action) if isinstance(raw_action, str | bytes) else dict(raw_action)
    if not isinstance(payload, dict):
        raise ValueError("LLM action payload must be a JSON object")
    return LLMAction.model_validate(payload)


def validate_llm_action(
    raw_action: str | bytes | Mapping[str, Any] | LLMAction,
    *,
    identity_state: object,
    promise_state: object,
    call_state: object,
) -> ActionValidationResult:
    """Validate an LLM proposal against authorization-relevant application state.

    Untrusted or malformed model output always becomes ``other`` with the reviewed
    clarification template. Before identity confirmation, private amount/date fields
    and all model-authored response prose are discarded. The controller must still
    select reviewed copy and perform every transition or tool invocation itself.
    """
    try:
        action = _parse_action(raw_action)
    except (json.JSONDecodeError, TypeError, ValueError, ValidationError):
        return _safe_other(rejected_fields=("payload",))

    identity_name = _state_name(identity_state)
    promise_name = _state_name(promise_state)
    call_name = _state_name(call_state)

    if action.intent is Intent.HANDOVER:
        if call_name not in HANDOVER_CALL_STATES:
            return _safe_other(rejected_fields=("intent",))
        return ActionValidationResult(
            action=action.model_copy(
                update={"amount_minor": None, "date_phrase": None, "response_draft": ""}
            ),
            accepted=True,
            rejected_fields=tuple(
                field
                for field, value in (
                    ("amount_minor", action.amount_minor),
                    ("date_phrase", action.date_phrase),
                    ("response_draft", action.response_draft),
                )
                if value is not None and value != ""
            ),
            handover_requested=True,
        )

    rejected_fields: list[str] = []
    updates: dict[str, object] = {}

    if identity_name != CONFIRMED_IDENTITY:
        if action.intent in CONFIRMED_ONLY_INTENTS:
            rejected_fields.append("intent")
        if action.amount_minor is not None:
            rejected_fields.append("amount_minor")
            updates["amount_minor"] = None
        if action.date_phrase is not None:
            rejected_fields.append("date_phrase")
            updates["date_phrase"] = None
        if action.response_draft:
            rejected_fields.append("response_draft")
            updates["response_draft"] = ""

    if action.intent is Intent.CONFIRM and promise_name != READ_BACK_PROMISE:
        rejected_fields.append("intent")
        updates["intent"] = Intent.OTHER

    validated_action = action.model_copy(update=updates) if updates else action
    accepted = not rejected_fields
    return ActionValidationResult(
        action=validated_action,
        accepted=accepted,
        rejected_fields=tuple(rejected_fields),
        response_template=CLARIFICATION_TEMPLATE
        if action.intent is Intent.CONFIRM and promise_name != READ_BACK_PROMISE
        else None,
    )
