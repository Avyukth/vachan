"""Pure prompt construction with identity-gated private account context."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from app.seeds import MockCaseSeed
from app.states import CallState, IdentityState, PromiseState
from app.templates import is_bank_member
from app.tools import TOOL_PERMISSION_MATRIX, ToolName

REDACTION_MARKER = "[protected value omitted]"

PRECONFIRMED_SYSTEM_PROMPT = (
    "You are Vachan's pre-confirmation intent classifier. Return only a typed "
    "pre-confirmation intent. Never draft speech, infer identity, or request OTP, PIN, or payment."
)
PRECONFIRMED_SELECTION_PROMPT = (
    "Code will select a reviewed fixed template. Classify only: scam concern, identity query, "
    "borrower present, verification response, third party, clarification, request human, "
    "handover, technical, or other."
)
CONFIRMED_SYSTEM_PROMPT = (
    "You are Vachan's language layer after deterministic identity confirmation. Propose only "
    "typed actions; application code owns transitions, tool authorization, read-back, and writes."
)


class PromptRole(StrEnum):
    """Roles accepted by the Sarvam chat boundary."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class PromptMessage:
    """One immutable message sent to the language model."""

    role: PromptRole
    content: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("prompt message content must not be empty")


@dataclass(frozen=True, slots=True)
class LLMContext:
    """The complete prompt/tool view available for one model request."""

    messages: tuple[PromptMessage, ...]
    available_tools: tuple[ToolName, ...]
    contains_private_account_context: bool

    def as_api_messages(self) -> list[dict[str, str]]:
        """Return the exact Sarvam-compatible message payload."""
        return [
            {"role": message.role.value, "content": message.content} for message in self.messages
        ]


class ContextIsolationViolation(ValueError):
    """A caller tried to route unreviewed or unredactable data to the model."""


_MONTH_FORMS = {
    1: ("january", "jan", "जनवरी"),
    2: ("february", "feb", "फ़रवरी", "फरवरी"),
    3: ("march", "mar", "मार्च"),
    4: ("april", "apr", "अप्रैल"),
    5: ("may", "मई"),
    6: ("june", "jun", "जून"),
    7: ("july", "jul", "जुलाई"),
    8: ("august", "aug", "अगस्त"),
    9: ("september", "sep", "sept", "सितंबर", "सितम्बर", "sitambar"),
    10: ("october", "oct", "अक्टूबर"),
    11: ("november", "nov", "नवंबर", "नवम्बर"),
    12: ("december", "dec", "दिसंबर", "दिसम्बर"),
}

_DAY_FORMS = {
    3: ("three", "teen", "तीन"),
    14: ("fourteen", "chaudah", "चौदह"),
}


def _amount_forms(amount_minor: int) -> set[str]:
    rupees = amount_minor // 100
    return {
        str(amount_minor),
        f"{amount_minor:,}",
        str(rupees),
        f"{rupees:,}",
        f"₹{rupees}",
        f"₹{rupees:,}",
    }


def _replace_literal(text: str, literal: str) -> str:
    return re.sub(re.escape(literal), REDACTION_MARKER, text, flags=re.IGNORECASE)


def redact_verification_text(text: str, case: MockCaseSeed) -> str:
    """Remove expected verification values in every identity state."""
    redacted = _replace_literal(text, case.verification.reference_last4)
    day = case.verification.birth_day
    month = case.verification.birth_month
    spaced_reference = r"[\s,.\-]*".join(
        re.escape(digit) for digit in case.verification.reference_last4
    )
    redacted = re.sub(
        rf"(?<!\d){spaced_reference}(?!\d)",
        REDACTION_MARKER,
        redacted,
    )
    numeric_date = re.compile(
        rf"\b0?{day}\s*(?:[/.\-\s]+)\s*0?{month}\b",
        flags=re.IGNORECASE,
    )
    redacted = numeric_date.sub(REDACTION_MARKER, redacted)

    day_forms = {str(day), *_DAY_FORMS.get(day, ())}
    month_forms = set(_MONTH_FORMS[month])
    for day_form in day_forms:
        for month_form in month_forms:
            patterns = (
                rf"\b{re.escape(day_form)}\s+{re.escape(month_form)}\b",
                rf"\b{re.escape(month_form)}\s+{re.escape(day_form)}\b",
            )
            for pattern in patterns:
                redacted = re.sub(
                    pattern,
                    REDACTION_MARKER,
                    redacted,
                    flags=re.IGNORECASE,
                )
    # Verification answers may arrive one field at a time. Remove each expected
    # component independently rather than relying on the combined date form.
    component_forms = {
        str(day),
        f"{day:02d}",
        str(month),
        f"{month:02d}",
        *_DAY_FORMS.get(day, ()),
        *_MONTH_FORMS[month],
    }
    for component in sorted(component_forms, key=len, reverse=True):
        redacted = re.sub(
            rf"(?<!\w){re.escape(component)}(?!\w)",
            REDACTION_MARKER,
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


def redact_preconfirmed_text(text: str, case: MockCaseSeed) -> str:
    """Remove actual seeded auth/account values before pre-confirm classification."""
    redacted = text
    private_literals = {case.account.lender_name}
    private_literals.update(_amount_forms(case.account.outstanding_minor))
    for installment in case.account.emi_schedule:
        private_literals.update(_amount_forms(installment.amount_minor))
        private_literals.update(
            {
                installment.due_date.isoformat(),
                installment.due_date.strftime("%d %B %Y"),
                f"{installment.due_date.day} {installment.due_date.strftime('%B %Y')}",
            }
        )

    for literal in sorted(private_literals, key=len, reverse=True):
        redacted = _replace_literal(redacted, literal)
    return redact_verification_text(redacted, case)


def _confirmed_account_json(case: MockCaseSeed) -> str:
    """Render account-only context; verification expected values are never included."""
    return json.dumps(
        {
            "mock_data": True,
            "case_id": case.case_id,
            "borrower_display_name": case.borrower_display_name,
            "lender_name": case.account.lender_name,
            "outstanding_minor": case.account.outstanding_minor,
            "emi_schedule": [
                {
                    "due_date": installment.due_date.isoformat(),
                    "amount_minor": installment.amount_minor,
                    "status": installment.status,
                }
                for installment in case.account.emi_schedule
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _safe_preconfirmed_history(
    history: tuple[PromptMessage, ...],
    case: MockCaseSeed,
) -> tuple[PromptMessage, ...]:
    messages: list[PromptMessage] = []
    for message in history:
        if message.role is PromptRole.SYSTEM:
            raise ContextIsolationViolation("callers cannot add system messages")
        if message.role is PromptRole.ASSISTANT and not is_bank_member(message.content):
            raise ContextIsolationViolation(
                "pre-confirmation assistant history must be reviewed template text"
            )
        content = (
            redact_preconfirmed_text(message.content, case)
            if message.role is PromptRole.USER
            else message.content
        )
        messages.append(PromptMessage(role=message.role, content=content))
    return tuple(messages)


def available_tools_for_state(
    *,
    call_state: CallState,
    identity_state: IdentityState,
    promise_state: PromiseState,
) -> tuple[ToolName, ...]:
    """Derive structural tool visibility from the declarative permission matrix."""
    visible: list[ToolName] = []
    for tool, rule in TOOL_PERMISSION_MATRIX.items():
        if rule.call_states is not None and call_state.value not in rule.call_states:
            continue
        if rule.identity_states is not None and identity_state.value not in rule.identity_states:
            continue
        if rule.promise_states is not None and promise_state.value not in rule.promise_states:
            continue
        visible.append(tool)
    return tuple(visible)


def build_llm_context(
    *,
    call_state: CallState,
    identity_state: IdentityState,
    promise_state: PromiseState,
    case: MockCaseSeed,
    current_utterance: str,
    history: tuple[PromptMessage, ...] = (),
) -> LLMContext:
    """Build the only model context path for both sides of the identity gate."""
    if not current_utterance.strip():
        raise ContextIsolationViolation("current utterance must not be empty")
    if any(message.role is PromptRole.SYSTEM for message in history):
        raise ContextIsolationViolation("callers cannot add system messages")

    if identity_state is not IdentityState.CONFIRMED:
        safe_history = _safe_preconfirmed_history(history, case)
        safe_current = redact_preconfirmed_text(current_utterance, case)
        return LLMContext(
            messages=(
                PromptMessage(PromptRole.SYSTEM, PRECONFIRMED_SYSTEM_PROMPT),
                PromptMessage(PromptRole.SYSTEM, PRECONFIRMED_SELECTION_PROMPT),
                *safe_history,
                PromptMessage(PromptRole.USER, safe_current),
            ),
            available_tools=available_tools_for_state(
                call_state=call_state,
                identity_state=identity_state,
                promise_state=promise_state,
            ),
            contains_private_account_context=False,
        )

    non_system_history = tuple(
        PromptMessage(
            role=message.role,
            content=redact_verification_text(message.content, case),
        )
        for message in history
    )
    return LLMContext(
        messages=(
            PromptMessage(PromptRole.SYSTEM, CONFIRMED_SYSTEM_PROMPT),
            PromptMessage(PromptRole.SYSTEM, _confirmed_account_json(case)),
            *non_system_history,
            PromptMessage(
                PromptRole.USER,
                redact_verification_text(current_utterance, case),
            ),
        ),
        available_tools=available_tools_for_state(
            call_state=call_state,
            identity_state=identity_state,
            promise_state=promise_state,
        ),
        contains_private_account_context=True,
    )


def build_post_demotion_context(
    *,
    call_state: CallState,
    identity_state: IdentityState,
    promise_state: PromiseState,
    case: MockCaseSeed,
    current_utterance: str,
) -> LLMContext:
    """Build a new-speaker prompt with no channel for pre-demotion history."""
    if identity_state is IdentityState.CONFIRMED:
        raise ContextIsolationViolation("post-demotion context requires a locked identity state")
    return build_llm_context(
        call_state=call_state,
        identity_state=identity_state,
        promise_state=promise_state,
        case=case,
        current_utterance=current_utterance,
        history=(),
    )
