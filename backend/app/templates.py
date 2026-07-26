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
    OUTPUT_GUARD_FALLBACK = "OUTPUT_GUARD_FALLBACK"
    STT_RECOVERY = "STT_RECOVERY"


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
        TemplateId.VERIFY_FAILED_CLOSE: ("मैं आपको दोबारा कॉल करके पुष्टि कर लूँगी। धन्यवाद।",),
        TemplateId.THIRD_PARTY_CALLBACK: (
            "यह Rakesh जी की personal call है। कृपया उनसे कह दीजिए कि Vachan assistant "
            "का फ़ोन आया था। बस इतना ही।",
            "क्या आप Rakesh जी से कह देंगे कि Vachan assistant का फ़ोन आया था? मैं संदेश में और कुछ नहीं छोड़ूँगी।",
            "धन्यवाद। कृपया Rakesh जी को सिर्फ़ इतना बता दीजिए कि Vachan assistant का फ़ोन आया था।",
        ),
        TemplateId.TECH_DIFFICULTY_CLOSE: (
            "तकनीकी दिक्कत के कारण मैं सुरक्षित रूप से आगे नहीं बढ़ सकती। मैं अभी कॉल समाप्त कर रही हूँ।",
        ),
        TemplateId.OUTPUT_GUARD_FALLBACK: (
            "माफ़ कीजिए, मैं वह बात सुरक्षित रूप से नहीं कह सकती। कृपया एक क्षण रुकिए।",
        ),
        TemplateId.STT_RECOVERY: ("line kharab hai, dobara boliye",),
    }
)

DEFAULT_TEMPLATE_CASE_ID = "case-rakesh-001"
BORROWER_TEMPLATE_IDS = frozenset(
    {
        TemplateId.ASK_FOR_BORROWER,
        TemplateId.THIRD_PARTY_CALLBACK,
    }
)
CASE_TEMPLATE_BANK = MappingProxyType(
    {
        DEFAULT_TEMPLATE_CASE_ID: MappingProxyType(
            {template_id: TEMPLATE_BANK[template_id] for template_id in BORROWER_TEMPLATE_IDS}
        ),
        "case-capped-001": MappingProxyType(
            {
                TemplateId.ASK_FOR_BORROWER: ("क्या मैं Meera जी से बात कर सकती हूँ?",),
                TemplateId.THIRD_PARTY_CALLBACK: (
                    "यह Meera जी की personal call है। कृपया उनसे कह दीजिए कि Vachan assistant "
                    "का फ़ोन आया था। बस इतना ही।",
                    "क्या आप Meera जी से कह देंगे कि Vachan assistant का फ़ोन आया था? "
                    "मैं संदेश में और कुछ नहीं छोड़ूँगी।",
                    "धन्यवाद। कृपया Meera जी को सिर्फ़ इतना बता दीजिए कि Vachan assistant "
                    "का फ़ोन आया था।",
                ),
            }
        ),
        "case-capped-002": MappingProxyType(
            {
                TemplateId.ASK_FOR_BORROWER: ("क्या मैं Farida जी से बात कर सकती हूँ?",),
                TemplateId.THIRD_PARTY_CALLBACK: (
                    "यह Farida जी की personal call है। कृपया उनसे कह दीजिए कि Vachan assistant "
                    "का फ़ोन आया था। बस इतना ही।",
                    "क्या आप Farida जी से कह देंगे कि Vachan assistant का फ़ोन आया था? "
                    "मैं संदेश में और कुछ नहीं छोड़ूँगी।",
                    "धन्यवाद। कृपया Farida जी को सिर्फ़ इतना बता दीजिए कि Vachan assistant "
                    "का फ़ोन आया था।",
                ),
            }
        ),
    }
)

BANK_MEMBERS = frozenset(
    text
    for template_variants in (
        *TEMPLATE_BANK.values(),
        *(variants for case_bank in CASE_TEMPLATE_BANK.values() for variants in case_bank.values()),
    )
    for text in template_variants
)
TEMPLATE_IDS_BY_TEXT = MappingProxyType(
    {
        text: template_id
        for template_id, template_variants in (
            *TEMPLATE_BANK.items(),
            *(item for case_bank in CASE_TEMPLATE_BANK.values() for item in case_bank.items()),
        )
        for text in template_variants
    }
)


@dataclass(frozen=True, slots=True)
class TemplateSelection:
    """A classifier decision resolved to speech copied directly from the bank."""

    template_id: TemplateId
    text: str
    classification_accepted: bool


class TemplateVariantError(ValueError):
    """Raised when code requests a non-existent reviewed phrasing."""


class UnreviewedSpeechError(ValueError):
    """Raised when operational speech is not an immutable registry member."""


RawClassification = str | bytes | Mapping[str, Any] | PreConfirmationClassification


def render_template(
    template_id: TemplateId,
    *,
    variant: int = 0,
    case_id: str | None = None,
) -> str:
    """Return reviewed copy selected by typed ID and governed case ID."""
    if not isinstance(template_id, TemplateId):
        raise UnreviewedSpeechError("operational speech requires a typed TemplateId")
    if template_id in BORROWER_TEMPLATE_IDS:
        governed_case_id = case_id or DEFAULT_TEMPLATE_CASE_ID
        try:
            variants = CASE_TEMPLATE_BANK[governed_case_id][template_id]
        except KeyError as error:
            raise UnreviewedSpeechError(
                "borrower-specific speech requires a governed case ID"
            ) from error
    else:
        variants = TEMPLATE_BANK[template_id]
    if variant < 0 or variant >= len(variants):
        raise TemplateVariantError(
            f"{template_id.value} has {len(variants)} reviewed variant(s), not variant {variant}"
        )
    return variants[variant]


def template_id_for_reviewed_text(response: str) -> TemplateId:
    """Resolve exact reviewed copy to its typed identifier or fail closed."""
    try:
        return TEMPLATE_IDS_BY_TEXT[response]
    except KeyError as error:
        raise UnreviewedSpeechError("operational speech is not reviewed registry copy") from error


def select_preconfirmation_response(
    raw_classification: RawClassification,
    *,
    callback_variant: int = 0,
    case_id: str | None = None,
) -> TemplateSelection:
    """Validate an LLM classification and deterministically choose fixed speech."""
    validation = validate_preconfirmation_classification(raw_classification)
    template_id = TemplateId(validation.template.value)
    variant = callback_variant if template_id is TemplateId.THIRD_PARTY_CALLBACK else 0
    return TemplateSelection(
        template_id=template_id,
        text=render_template(template_id, variant=variant, case_id=case_id),
        classification_accepted=validation.accepted,
    )


def is_bank_member(response: str) -> bool:
    """Return whether speech is byte-for-byte reviewed pre-confirmation copy."""
    return response in BANK_MEMBERS
