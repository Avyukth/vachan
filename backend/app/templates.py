"""Reviewed, fixed speech templates used before identity confirmation."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from app.actions import (
    PreConfirmationClassification,
    validate_preconfirmation_classification,
)


class TemplateId(StrEnum):
    """Code-owned identifiers for every pre-confirmation utterance family."""

    INTRO_ANTISCAM = "INTRO_ANTISCAM"
    ASK_FOR_BORROWER = "ASK_FOR_BORROWER"
    VERIFY_REQUEST = "VERIFY_REQUEST"
    CLARIFY = "CLARIFY"
    VERIFY_FAILED_CLOSE = "VERIFY_FAILED_CLOSE"
    THIRD_PARTY_CALLBACK = "THIRD_PARTY_CALLBACK"
    TECH_DIFFICULTY_CLOSE = "TECH_DIFFICULTY_CLOSE"


TEMPLATE_BANK = MappingProxyType(
    {
        TemplateId.INTRO_ANTISCAM: (
            "नमस्ते, मैं Vachan assistant बोल रही हूँ। मैं आपसे कभी OTP या UPI PIN नहीं "
            "माँगूँगी, और इस कॉल पर कोई payment नहीं होती।",
        ),
        TemplateId.ASK_FOR_BORROWER: ("क्या मैं Rakesh जी से बात कर सकती हूँ?",),
        TemplateId.VERIFY_REQUEST: (
            "आपकी पहचान जाँचने के लिए कृपया जन्म का दिन और महीना, और mock customer "
            "reference के आख़िरी चार अक्षर बताएँ। कृपया कोई OTP या PIN साझा न करें।",
        ),
        TemplateId.CLARIFY: ("माफ़ कीजिए, मैं स्पष्ट रूप से समझ नहीं पाई। कृपया एक बार फिर कहेंगे?",),
        TemplateId.VERIFY_FAILED_CLOSE: (
            "माफ़ कीजिए, मैं इस कॉल पर आपकी पहचान पक्की नहीं कर पाई। मैं अभी कॉल समाप्त कर रही हूँ।",
        ),
        TemplateId.THIRD_PARTY_CALLBACK: (
            "यह Rakesh जी की personal call है। कृपया उनसे कह दीजिए कि Vachan assistant "
            "का फ़ोन आया था। बस इतना ही।",
            "क्या आप Rakesh जी से कह देंगे कि Vachan assistant का फ़ोन आया था? मैं संदेश में और कुछ नहीं छोड़ूँगी।",
            "धन्यवाद। कृपया Rakesh जी को सिर्फ़ इतना बता दीजिए कि Vachan assistant का फ़ोन आया था।",
        ),
        TemplateId.TECH_DIFFICULTY_CLOSE: (
            "तकनीकी दिक्कत के कारण मैं सुरक्षित रूप से आगे नहीं बढ़ सकती। मैं अभी कॉल समाप्त कर रही हूँ।",
        ),
    }
)

BANK_MEMBERS = frozenset(
    text for template_variants in TEMPLATE_BANK.values() for text in template_variants
)


@dataclass(frozen=True, slots=True)
class TemplateSelection:
    """A classifier decision resolved to speech copied directly from the bank."""

    template_id: TemplateId
    text: str
    classification_accepted: bool


class TemplateVariantError(ValueError):
    """Raised when code requests a non-existent reviewed phrasing."""


RawClassification = str | bytes | Mapping[str, Any] | PreConfirmationClassification


def render_template(template_id: TemplateId, *, variant: int = 0) -> str:
    """Return one reviewed utterance; never interpolate model-authored prose."""
    variants = TEMPLATE_BANK[template_id]
    if variant < 0 or variant >= len(variants):
        raise TemplateVariantError(
            f"{template_id.value} has {len(variants)} reviewed variant(s), not variant {variant}"
        )
    return variants[variant]


def select_preconfirmation_response(
    raw_classification: RawClassification,
    *,
    callback_variant: int = 0,
) -> TemplateSelection:
    """Validate an LLM classification and deterministically choose fixed speech."""
    validation = validate_preconfirmation_classification(raw_classification)
    template_id = TemplateId(validation.template.value)
    variant = callback_variant if template_id is TemplateId.THIRD_PARTY_CALLBACK else 0
    return TemplateSelection(
        template_id=template_id,
        text=render_template(template_id, variant=variant),
        classification_accepted=validation.accepted,
    )


def is_bank_member(response: str) -> bool:
    """Return whether speech is byte-for-byte reviewed pre-confirmation copy."""
    return response in BANK_MEMBERS
