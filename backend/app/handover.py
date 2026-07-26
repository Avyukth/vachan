"""Fail-closed mid-call handover and new-speaker boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.context_isolation import LLMContext, build_post_demotion_context
from app.seeds import MockCaseSeed
from app.state_machine import StateMachineCoordinator
from app.states import IdentityState
from app.templates import TemplateId, render_template
from app.third_party import (
    SpeakerRouteKind,
    normalize_speaker_utterance,
    route_speaker_utterance,
)
from app.verification import VerificationSession

_EXPLICIT_HANDOVER_PATTERNS: Final = (
    re.compile(r"\b(?:main|mai)\s+(?:phone\s+)?de\s+raha\s+(?:hoon|hun|hu)\b"),
    re.compile(r"\b(?:main|mai)\s+(?:phone\s+)?pass\s+kar\s+raha\s+(?:hoon|hun|hu)\b"),
    re.compile(r"\blo\s+(?:aap\s+)?baat\s+karo\b"),
    re.compile(r"\bphone\s+(?:unko|use|wife\s+ko|patni\s+ko)\s+de\s+raha\b"),
    re.compile(r"मैं\s+(?:फ़ोन|फोन)\s+दे\s+रहा\s+हूँ"),
    re.compile(r"लो\s+(?:आप\s+)?बात\s+करो"),
)
_NAMED_NEW_SPEAKER_PATTERNS: Final = (
    re.compile(r"\b(?:main|mai)\s+sunita\s+(?:hoon|hun|hu)\b"),
    re.compile(r"\b(?:i\s+am|this\s+is)\s+sunita\b"),
    re.compile(r"मैं\s+सुनीता\s+हूँ"),
)


class HandoverSignal(StrEnum):
    """Redacted code-owned reasons that can invalidate identity."""

    NONE = "NONE"
    EXPLICIT_HANDOVER = "EXPLICIT_HANDOVER"
    TYPED_HANDOVER = "TYPED_HANDOVER"
    NEW_SPEAKER_IDENTIFIED = "NEW_SPEAKER_IDENTIFIED"
    SPEAKER_CHANGE = "SPEAKER_CHANGE"
    IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"


@dataclass(frozen=True, slots=True)
class HandoverDetection:
    """A target identity and safe evidence code; never the caller's words."""

    signal: HandoverSignal
    identity_target: IdentityState | None
    reason_code: str | None

    @property
    def detected(self) -> bool:
        return self.signal is not HandoverSignal.NONE


NO_HANDOVER = HandoverDetection(
    signal=HandoverSignal.NONE,
    identity_target=None,
    reason_code=None,
)


def detect_handover(
    utterance: str,
    *,
    handover_requested: bool = False,
    speaker_changed: bool = False,
    identity_uncertain: bool = False,
) -> HandoverDetection:
    """Conservatively detect facts that require immediate identity demotion."""
    normalized = normalize_speaker_utterance(utterance)
    speaker_route = route_speaker_utterance(utterance)
    if speaker_route.kind is SpeakerRouteKind.ENTER_THIRD_PARTY or any(
        pattern.search(normalized) for pattern in _NAMED_NEW_SPEAKER_PATTERNS
    ):
        return HandoverDetection(
            signal=HandoverSignal.NEW_SPEAKER_IDENTIFIED,
            identity_target=IdentityState.THIRD_PARTY,
            reason_code="new_speaker_identified",
        )
    if any(pattern.search(normalized) for pattern in _EXPLICIT_HANDOVER_PATTERNS):
        return HandoverDetection(
            signal=HandoverSignal.EXPLICIT_HANDOVER,
            identity_target=IdentityState.UNVERIFIED,
            reason_code="explicit_handover",
        )
    if handover_requested:
        return HandoverDetection(
            signal=HandoverSignal.TYPED_HANDOVER,
            identity_target=IdentityState.UNVERIFIED,
            reason_code="typed_handover",
        )
    if speaker_changed:
        return HandoverDetection(
            signal=HandoverSignal.SPEAKER_CHANGE,
            identity_target=IdentityState.UNVERIFIED,
            reason_code="speaker_change_detected",
        )
    if identity_uncertain:
        return HandoverDetection(
            signal=HandoverSignal.IDENTITY_UNCERTAIN,
            identity_target=IdentityState.UNVERIFIED,
            reason_code="identity_uncertain",
        )
    return NO_HANDOVER


@dataclass(frozen=True, slots=True)
class HandoverOutcome:
    """Safe response and exact new-speaker context after the relock is evidenced."""

    detection: HandoverDetection
    identity_state: IdentityState
    response_template: TemplateId
    response_text: str
    context: LLMContext


class HandoverBoundary:
    """Own the no-carryover epoch after a confirmed phone handover."""

    def __init__(
        self,
        *,
        state: StateMachineCoordinator,
        case: MockCaseSeed,
    ) -> None:
        self._state = state
        self._case = case
        self._demoted = False

    @property
    def demoted(self) -> bool:
        return self._demoted

    def build_new_speaker_context(self, current_utterance: str) -> LLMContext:
        """Build from the current turn only; old confirmed history is unreachable."""
        if not self._demoted:
            raise RuntimeError("new-speaker context is unavailable before handover demotion")
        snapshot = self._state.snapshot
        return build_post_demotion_context(
            call_state=snapshot.call,
            identity_state=snapshot.identity,
            promise_state=snapshot.promise,
            case=self._case,
            current_utterance=current_utterance,
        )

    async def handle_turn(
        self,
        utterance: str,
        *,
        handover_requested: bool = False,
        speaker_changed: bool = False,
        identity_uncertain: bool = False,
    ) -> HandoverOutcome | None:
        """Relock first, persist the demotion, then expose only fixed safe speech."""
        detection = detect_handover(
            utterance,
            handover_requested=handover_requested,
            speaker_changed=speaker_changed,
            identity_uncertain=identity_uncertain,
        )
        if not detection.detected:
            return None

        before = self._state.snapshot.identity
        target = detection.identity_target
        assert target is not None
        if before is IdentityState.CONFIRMED:
            await self._state.transition(target, reason_code=detection.reason_code or "handover")
            self._demoted = True
        elif (
            before
            in {
                IdentityState.UNVERIFIED,
                IdentityState.VERIFYING,
            }
            and target is IdentityState.THIRD_PARTY
        ):
            await self._state.transition(
                IdentityState.THIRD_PARTY,
                reason_code=detection.reason_code or "new_speaker_identified",
            )
            self._demoted = True
        elif before is IdentityState.THIRD_PARTY:
            self._demoted = True
        else:
            return None

        identity = self._state.snapshot.identity
        template = (
            TemplateId.THIRD_PARTY_CALLBACK
            if identity is IdentityState.THIRD_PARTY
            else TemplateId.ASK_FOR_BORROWER
        )
        return HandoverOutcome(
            detection=detection,
            identity_state=identity,
            response_template=template,
            response_text=render_template(template, case_id=self._case.case_id),
            context=self.build_new_speaker_context(utterance),
        )

    async def begin_fresh_reverification(self) -> VerificationSession:
        """Require a brand-new two-value challenge when the borrower returns."""
        identity = self._state.snapshot.identity
        if identity not in {IdentityState.UNVERIFIED, IdentityState.THIRD_PARTY}:
            raise RuntimeError("fresh verification requires an unverified or third-party speaker")
        await self._state.transition(
            IdentityState.VERIFYING,
            reason_code="borrower_returned_fresh_verification",
        )
        return VerificationSession()
