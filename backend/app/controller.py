"""Deterministic dialogue orchestration across Vachan's policy boundaries.

The controller is intentionally transport-agnostic.  A Sarvam-compatible
client supplies transcripts, typed action proposals, and synthesized audio;
code-owned state machines, verification, tools, promise handling, and the
output guard remain authoritative.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

from app.actions import (
    Intent,
    PreConfirmationIntent,
    PreConfirmationValidationResult,
    validate_llm_action,
    validate_preconfirmation_classification,
)
from app.context_isolation import PromptMessage, PromptRole, build_llm_context
from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import EvidenceLedger, TerminalDispositionConflict
from app.gated_tools import GatedToolExecutor, ToolFacts
from app.guard import OutputBlockedEvent, OutputGuardContext, classify_block, guard_for_tts
from app.handover import HandoverBoundary, HandoverOutcome
from app.llm import deterministic_preconfirmation_intent
from app.promise import (
    AmbiguousDateError,
    InvalidAmountError,
    InvalidPromiseDateError,
    PromiseEngine,
    PromiseEvent,
    PromiseEventType,
    PromiseNormalizationError,
    SQLitePromiseRepository,
    amount_in_hindi_words,
    normalize_promise_date,
)
from app.seeds import MockCaseSeed
from app.state_machine import StateMachineCoordinator
from app.states import CallState, IdentityState, PromiseState
from app.templates import TemplateId, render_template
from app.third_party import (
    ContentFreeCallbackPayload,
    ThirdPartySession,
    payload_is_content_free,
    protected_case_values,
    route_speaker_utterance,
)
from app.tools import ToolDecision, ToolName, ToolPermissionDenied
from app.verification import (
    ExpectedVerification,
    PendingVerificationAttempt,
    VerificationSession,
    VerificationStatus,
    VerificationSubmission,
    collect_verification_attempt,
    normalize_birth_day_month,
    normalize_reference_last4,
    verification_input_marker,
)
from app.verification_evidence import VerificationEvidenceRepository

JsonObject = dict[str, Any]
Clock = Callable[[], datetime]
# Three user/assistant exchanges. Enough context for a classifier or a promise
# correction, small enough that turn latency cannot grow without bound.
MAX_PROMPT_HISTORY_MESSAGES = 6


class SarvamDialogueClient(Protocol):
    """Network boundary used by both the real adapter and deterministic fake."""

    async def transcribe(self, audio: bytes, **kwargs: object) -> JsonObject: ...

    async def chat_completion(
        self,
        messages: Sequence[Mapping[str, object]],
        **kwargs: object,
    ) -> JsonObject: ...

    async def synthesize(self, text: str, **kwargs: object) -> JsonObject: ...


@dataclass(frozen=True, slots=True)
class ControllerTurn:
    """Safe result of one complete text-mode controller turn."""

    transcript: str
    speech_text: str
    audio_response: JsonObject
    disposition: Disposition | None


class ControllerClosedError(RuntimeError):
    """A turn arrived after the call acquired a terminal disposition."""


class ControllerToolEffectError(RuntimeError):
    """A tool executor returned without applying its promised domain effect."""


class InvalidModelEnvelope(ValueError):
    """The model response did not contain one typed JSON action."""


class _DuplicateDisposition(RuntimeError):
    """Internal rollback signal for an already-persisted identical outcome."""


_CORRECTABLE_PROMISE_STATES = frozenset(
    {
        PromiseState.CANDIDATE,
        PromiseState.CORRECTED,
        PromiseState.READ_BACK,
    }
)
_MAX_SPEAKER_IDENTITY_CLARIFICATIONS = 2


def _validated_model_amount_minor(amount_minor: int | None) -> int:
    """Accept only supported positive whole-rupee values expressed in paise."""

    if (
        isinstance(amount_minor, bool)
        or not isinstance(amount_minor, int)
        or amount_minor <= 0
        or amount_minor % 100
    ):
        raise InvalidAmountError("model amount must be positive whole rupees in paise")
    # Read-back is part of the write contract, so reject values that its
    # deterministic renderer cannot safely express before authorization.
    amount_in_hindi_words(amount_minor // 100)
    return amount_minor


def _promise_fact_denial_code(error: PromiseNormalizationError) -> str:
    """Map normalization failures to redacted, stable evidence codes."""

    if isinstance(error, AmbiguousDateError):
        return "ambiguous_date"
    if isinstance(error, InvalidPromiseDateError):
        return "invalid_date"
    return "invalid_amount"


def _action_payload(response: Mapping[str, object]) -> dict[str, object]:
    """Extract one OpenAI-compatible chat payload without trusting its fields."""

    try:
        choices = response["choices"]
        first = choices[0]  # type: ignore[index]
        message = first["message"]  # type: ignore[index]
        content = message["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as error:
        raise InvalidModelEnvelope("chat response is missing typed action content") from error
    if not isinstance(content, str):
        raise InvalidModelEnvelope("chat action content must be a JSON string")
    normalized = content.strip()
    if normalized.startswith("```"):
        first_newline = normalized.find("\n")
        if first_newline != -1:
            normalized = normalized[first_newline + 1 :]
        if normalized.endswith("```"):
            normalized = normalized[:-3].rstrip()
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return {"intent": "other"}
    return payload if isinstance(payload, dict) else {"intent": "other"}


def controller_preconfirmation_template(
    validation: PreConfirmationValidationResult,
) -> TemplateId:
    """Convert the validated model route to the controller's reviewed template enum."""

    return TemplateId(validation.template.value)


class DialogueController:
    """One call's deterministic state, evidence, and network orchestration."""

    def __init__(
        self,
        *,
        call_id: str,
        case: MockCaseSeed,
        ledger: EvidenceLedger,
        sarvam: SarvamDialogueClient,
        clock: Clock,
        transport: str = "text_mode_fake",
    ) -> None:
        if not call_id.strip():
            raise ValueError("call_id must not be empty")
        self.call_id = call_id
        self.case = case
        self.ledger = ledger
        self.sarvam = sarvam
        self.clock = clock
        self.transport = transport
        self.disposition: Disposition | None = None
        self._verification_evidence = VerificationEvidenceRepository(ledger)
        self.verification = self._verification_evidence.reconstruct_session(call_id)
        self._pending_verification = PendingVerificationAttempt()
        self.third_party = ThirdPartySession(case_id=case.case_id)
        self.callback_payloads: list[dict[str, str]] = []
        self.history: tuple[PromptMessage, ...] = ()
        self._speaker_identity_clarifications = 0
        self._started = False
        self._disposition_lock = asyncio.Lock()
        self._coordinator = StateMachineCoordinator(
            call_id=call_id,
            event_writer=ledger,
            clock=clock,
        )
        self._tools = GatedToolExecutor(
            call_id=call_id,
            authorization_state=self._coordinator,
            decision_writer=ledger,
            clock=clock,
        )
        self._handover = HandoverBoundary(
            state=self._coordinator,
            case=case,
        )
        self._promise = PromiseEngine(
            call_id=call_id,
            repository=SQLitePromiseRepository(ledger),
            demo_time_anchor=clock(),
            clock=clock,
            record_event=self._record_promise_event,
            atomic_event_applier=self._apply_promise_event,
        )

    @property
    def snapshot(self) -> StateSnapshot:
        return self._coordinator.snapshot

    @property
    def coordinator(self) -> StateMachineCoordinator:
        """Expose the single authoritative state boundary to call-scoped safety adapters."""

        return self._coordinator

    def _reviewed_template(self, template_id: TemplateId, *, variant: int = 0) -> str:
        """Select immutable reviewed copy for this call's governed case."""

        return render_template(
            template_id,
            variant=variant,
            case_id=self.case.case_id,
        )

    async def start(self) -> None:
        """Create one active call and persist the complete startup path."""

        if self._started:
            raise RuntimeError("call is already started")
        self.ledger.connection.execute(
            """
            INSERT INTO calls (id, case_id, started, transport)
            VALUES (?, ?, ?, ?)
            """,
            (self.call_id, self.case.case_id, self.clock().isoformat(), self.transport),
        )
        await self._activate(reason_prefix="text_mode")

    async def activate_existing_call(self) -> None:
        """Attach policy state to a call row created by the preflight route."""

        if self._started:
            raise RuntimeError("call is already started")
        row = self.ledger.connection.execute(
            "SELECT disposition FROM calls WHERE id = ? AND case_id = ?",
            (self.call_id, self.case.case_id),
        ).fetchone()
        if row is None:
            raise RuntimeError("call row must exist before voice activation")
        if row["disposition"] is not None:
            raise ControllerClosedError("terminal call cannot be activated")
        await self._activate(reason_prefix="voice")
        await self._restore_verification_identity()

    async def _activate(self, *, reason_prefix: str) -> None:
        for target, reason in (
            (CallState.PREFLIGHT, f"{reason_prefix}_preflight"),
            (CallState.READY, f"{reason_prefix}_ready"),
            (CallState.CONNECTING, f"{reason_prefix}_connecting"),
            (CallState.ACTIVE, f"{reason_prefix}_active"),
        ):
            await self._coordinator.transition(target, reason_code=reason)
        self._started = True

    async def _restore_verification_identity(self) -> None:
        """Rebuild authorization state from durable attempts for this same call."""

        if self.verification.attempts == 0:
            return
        await self._coordinator.transition(
            IdentityState.VERIFYING,
            reason_code="verification_attempts_restored",
        )
        if self.verification.status is VerificationStatus.CONFIRMED:
            await self._coordinator.transition(
                IdentityState.CONFIRMED,
                reason_code="verification_confirmation_restored",
            )

    async def _record_promise_event(self, event: PromiseEvent) -> None:
        snapshot = self.snapshot
        await self.ledger.append_event(
            call_id=self.call_id,
            ts=self.clock(),
            event_type=event.event_type.value,
            state_before=replace(snapshot, promise=event.state_before),
            state_after=replace(snapshot, promise=event.state_after),
            redacted_reason=event.redacted_reason,
        )

    def _apply_promise_event(
        self,
        event: PromiseEvent,
        mutation: Callable[[], Any],
    ) -> Any:
        """Persist one authorized promise effect and its evidence without yielding."""

        snapshot = self.snapshot
        if event.event_type is PromiseEventType.COMMITTED:
            state_committed = replace(snapshot, promise=event.state_after)
            state_completed = replace(state_committed, call=CallState.COMPLETED)
            try:
                result, _seq = self.ledger.commit_promise_outcome(
                    call_id=self.call_id,
                    ts=self.clock(),
                    state_before=replace(snapshot, promise=event.state_before),
                    state_committed=state_committed,
                    state_completed=state_completed,
                    mutation=mutation,
                )
            except TerminalDispositionConflict as error:
                self.disposition = error.disposition
                raise ControllerClosedError(
                    "call acquired a terminal disposition before promise commit"
                ) from error
            self._coordinator.adopt_persisted_snapshot(state_completed)
            self.disposition = Disposition.PROMISE_CONFIRMED
            return result

        result, _seq = self.ledger.mutate_with_event(
            call_id=self.call_id,
            ts=self.clock(),
            event_type=event.event_type,
            state_before=replace(snapshot, promise=event.state_before),
            state_after=replace(snapshot, promise=event.state_after),
            redacted_reason=event.redacted_reason,
            mutation=mutation,
        )
        return result

    async def _record_guard_block(self, event: OutputBlockedEvent) -> None:
        snapshot = self.snapshot
        await self.ledger.append_event(
            call_id=self.call_id,
            ts=self.clock(),
            event_type=event.event_type,
            state_before=snapshot,
            state_after=snapshot,
            redacted_reason=event.redacted_reason,
        )

    async def _speak(self, draft: str) -> tuple[str, JsonObject]:
        blocked: list[OutputBlockedEvent] = []
        guarded = guard_for_tts(
            draft,
            OutputGuardContext.from_case(
                self.case,
                identity_state=self.snapshot.identity,
                promise_state=self.snapshot.promise,
                normalized_promise_dates=(
                    (self._promise.candidate.date_iso,)
                    if self._promise.candidate is not None
                    else ()
                ),
            ),
            record_block=blocked.append,
        )
        for event in blocked:
            await self._record_guard_block(event)
        audio = await self.sarvam.synthesize(guarded.speech_text)
        self.history = (
            *self.history,
            PromptMessage(PromptRole.ASSISTANT, guarded.speech_text),
        )
        return guarded.speech_text, audio

    async def _set_disposition(
        self,
        disposition: Disposition,
        *,
        reason_code: str,
        evidence_reason: str | None = None,
    ) -> tuple[int, datetime]:
        """Finalize through the call-scoped atomic boundary, not the tool gate.

        Ending first requires awaited state-machine transitions, so it cannot
        be a synchronous ``GatedToolExecutor`` effect. The disposition lock and
        ``mutate_with_event`` instead form the narrower authoritative boundary:
        exactly one terminal call mutation and its evidence row commit together.
        """

        async with self._disposition_lock:
            persisted = self.ledger.connection.execute(
                "SELECT ended, disposition FROM calls WHERE id = ?",
                (self.call_id,),
            ).fetchone()
            if persisted is None:
                raise LookupError("call does not exist")
            if persisted["disposition"] is not None:
                stored = Disposition(str(persisted["disposition"]))
                self.disposition = stored
                if stored is not disposition:
                    raise ControllerClosedError("call already has a different disposition")
                event = self.ledger.connection.execute(
                    """
                    SELECT seq
                    FROM events
                    WHERE call_id = ? AND type = ?
                    ORDER BY seq DESC
                    LIMIT 1
                    """,
                    (self.call_id, LedgerEventType.DISPOSITION_SET.value),
                ).fetchone()
                if event is None or persisted["ended"] is None:
                    raise RuntimeError("terminal call is missing disposition evidence")
                return int(event["seq"]), datetime.fromisoformat(str(persisted["ended"]))

            if self.disposition is not None:
                if self.disposition is disposition:
                    raise RuntimeError("in-memory disposition is missing durable evidence")
                raise ControllerClosedError("call already has a different disposition")

            if self.snapshot.call is CallState.ACTIVE:
                target = (
                    CallState.COMPLETED
                    if disposition
                    in {Disposition.PROMISE_CONFIRMED, Disposition.CALLBACK_THIRD_PARTY}
                    else CallState.ENDED
                )
                await self._coordinator.transition(target, reason_code=reason_code)
            elif self.snapshot.call in {CallState.DEGRADED, CallState.OPERATOR_TAKEOVER}:
                await self._coordinator.transition(CallState.ENDED, reason_code=reason_code)

            timestamp = self.clock()
            snapshot = self.snapshot

            def persist_terminal_call() -> None:
                call = self.ledger.connection.execute(
                    "SELECT disposition FROM calls WHERE id = ?",
                    (self.call_id,),
                ).fetchone()
                if call is None:
                    raise LookupError("call does not exist")
                if call["disposition"] is not None:
                    stored = Disposition(str(call["disposition"]))
                    if stored is disposition:
                        raise _DuplicateDisposition
                    raise ControllerClosedError("call already has a different disposition")
                updated = self.ledger.connection.execute(
                    """
                    UPDATE calls
                    SET ended = ?, disposition = ?, operator_intervened = ?
                    WHERE id = ? AND disposition IS NULL
                    """,
                    (
                        timestamp.isoformat(),
                        disposition.value,
                        int(disposition is Disposition.ENDED_OPERATOR),
                        self.call_id,
                    ),
                )
                if updated.rowcount != 1:
                    raise RuntimeError("terminal disposition lost its active-call race")

            try:
                _, seq = self.ledger.mutate_with_event(
                    call_id=self.call_id,
                    ts=timestamp,
                    event_type=LedgerEventType.DISPOSITION_SET,
                    state_before=snapshot,
                    state_after=snapshot,
                    redacted_reason=evidence_reason or reason_code,
                    mutation=persist_terminal_call,
                )
            except _DuplicateDisposition:
                event = self.ledger.connection.execute(
                    """
                    SELECT seq
                    FROM events
                    WHERE call_id = ? AND type = ?
                    ORDER BY seq DESC
                    LIMIT 1
                    """,
                    (self.call_id, LedgerEventType.DISPOSITION_SET.value),
                ).fetchone()
                ended = self.ledger.connection.execute(
                    "SELECT ended FROM calls WHERE id = ?",
                    (self.call_id,),
                ).fetchone()
                if event is None or ended is None or ended["ended"] is None:
                    raise RuntimeError("terminal call is missing disposition evidence") from None
                self.disposition = disposition
                return int(event["seq"]), datetime.fromisoformat(str(ended["ended"]))
            except ControllerClosedError:
                winner = self.ledger.connection.execute(
                    "SELECT disposition FROM calls WHERE id = ?",
                    (self.call_id,),
                ).fetchone()
                if winner is not None and winner["disposition"] is not None:
                    self.disposition = Disposition(str(winner["disposition"]))
                raise

            self.disposition = disposition
            return seq, timestamp

    async def _submit_verification(self, transcript: str) -> tuple[str, Disposition | None]:
        result = await self._tools.execute(
            ToolName.SUBMIT_VERIFICATION,
            facts=ToolFacts(verification_attempts=self.verification.attempts),
            operation=lambda: collect_verification_attempt(
                self.verification,
                self._pending_verification,
                VerificationSubmission(
                    birth_day_month=transcript,
                    reference_last4=transcript,
                ),
                ExpectedVerification.from_case(self.case),
            ),
        )
        if isinstance(result, PendingVerificationAttempt):
            self._pending_verification = result
            return self._reviewed_template(TemplateId.VERIFY_REQUEST), None
        snapshot = self.snapshot
        await self._verification_evidence.append_attempt(
            call_id=self.call_id,
            ts=self.clock(),
            state=snapshot,
            evidence=result.evidence,
        )
        self._pending_verification = PendingVerificationAttempt()
        self.verification = result.session
        if result.identity_state is IdentityState.CONFIRMED:
            await self._coordinator.transition(
                IdentityState.CONFIRMED,
                reason_code="verification_passed",
            )
            return "धन्यवाद। पहचान की जाँच पूरी हुई।", None
        if result.disposition is Disposition.VERIFICATION_FAILED:
            assert result.response_template is not None
            return self._reviewed_template(result.response_template), result.disposition
        return self._reviewed_template(TemplateId.VERIFY_REQUEST), None

    async def _schedule_third_party_callback(self) -> None:
        payload = ContentFreeCallbackPayload().as_tool_payload()
        await self._tools.execute(
            ToolName.SCHEDULE_CONTENT_FREE_CALLBACK,
            facts=ToolFacts(
                callback_payload_is_content_free=payload_is_content_free(
                    payload,
                    protected_values=protected_case_values(self.case),
                )
            ),
            operation=lambda: self.callback_payloads.append(payload),
        )

    def _bounded_unresolved_speaker_response(
        self,
        template_id: TemplateId,
    ) -> tuple[str, Disposition | None]:
        """Close safely when repeated ambiguity cannot establish who answered."""

        if template_id is not TemplateId.CLARIFY:
            self._resolve_speaker_identity_clarification()
            return self._reviewed_template(template_id), None
        self._speaker_identity_clarifications += 1
        if self._speaker_identity_clarifications < _MAX_SPEAKER_IDENTITY_CLARIFICATIONS:
            return self._reviewed_template(template_id), None
        return (
            self._reviewed_template(TemplateId.VERIFY_FAILED_CLOSE),
            Disposition.VERIFICATION_FAILED,
        )

    def _resolve_speaker_identity_clarification(self) -> None:
        self._speaker_identity_clarifications = 0

    async def _begin_fresh_borrower_return(self, transcript: str) -> bool:
        """Reset the third-party epoch before constructing another model prompt."""

        if self.snapshot.identity is not IdentityState.THIRD_PARTY:
            return False
        route = route_speaker_utterance(
            transcript,
            proposed_intent=PreConfirmationIntent.OTHER,
        )
        if route.identity_target is not IdentityState.VERIFYING:
            return False
        await self._coordinator.transition(
            IdentityState.VERIFYING,
            reason_code="borrower_returned_fresh_verification",
        )
        self.verification = VerificationSession()
        self._pending_verification = PendingVerificationAttempt()
        self.third_party = ThirdPartySession(case_id=self.case.case_id)
        self.history = ()
        return True

    async def _handle_preconfirmed(
        self,
        transcript: str,
        payload: Mapping[str, object],
    ) -> tuple[str, Disposition | None]:
        validation = validate_preconfirmation_classification(payload)
        proposed = validation.classification.intent
        validated_template = controller_preconfirmation_template(validation)

        # The blocked-prose matrix case deliberately exercises the fourth layer.
        untrusted_draft = payload.get("response_draft")
        if isinstance(untrusted_draft, str) and untrusted_draft.strip():
            guard_context = OutputGuardContext.from_case(
                self.case,
                identity_state=self.snapshot.identity,
                promise_state=self.snapshot.promise,
            )
            if classify_block(untrusted_draft, guard_context) is not None:
                return untrusted_draft, None

        if self.snapshot.identity is IdentityState.VERIFYING:
            # The model must not be a gate in FRONT of the comparator. Observed live: a
            # borrower said the reference digits, the classifier failed to label the turn
            # VERIFICATION_RESPONSE, so code never got to compare and identity stayed
            # VERIFYING forever (ledger call-91dead9d, seq 5-11: one submission for two
            # supplied fields, so the split-turn attempt could never complete).
            #
            # Opening the comparator grants nothing on its own: only
            # collect_verification_attempt can return CONFIRMED, the tool matrix still
            # requires VERIFYING + ACTIVE + attempts remaining, and both normalizers are
            # value-free - they return a normalized form and never log the spoken value.
            # This moves the decision from the model to code, which is the whole thesis.
            if (
                proposed is PreConfirmationIntent.VERIFICATION_RESPONSE
                or normalize_birth_day_month(transcript) is not None
                or normalize_reference_last4(transcript) is not None
            ):
                self._resolve_speaker_identity_clarification()
                return await self._submit_verification(transcript)
            route = route_speaker_utterance(transcript, proposed_intent=proposed)
            if route.identity_target is IdentityState.THIRD_PARTY:
                self._resolve_speaker_identity_clarification()
                await self._coordinator.transition(
                    IdentityState.THIRD_PARTY,
                    reason_code=route.reason_code,
                )
                self._pending_verification = PendingVerificationAttempt()
                return self._reviewed_template(route.template_id), None
            if route.identity_target is IdentityState.VERIFYING:
                self._resolve_speaker_identity_clarification()
                return self._reviewed_template(route.template_id), None
            if route.reason_code != "speaker_identity_unresolved":
                self._resolve_speaker_identity_clarification()
                return self._reviewed_template(route.template_id), None
            return self._bounded_unresolved_speaker_response(validated_template)

        if self.snapshot.identity is IdentityState.THIRD_PARTY:
            self._resolve_speaker_identity_clarification()
            # A model label cannot unlock a shared handset. Only the deterministic
            # explicit-borrower matcher may start a fresh verification epoch.
            if await self._begin_fresh_borrower_return(transcript):
                return self._reviewed_template(TemplateId.VERIFY_REQUEST), None
            hold = self.third_party.next_hold()
            if self.third_party.response_count == 3:
                await self._schedule_third_party_callback()
                return hold.text, Disposition.CALLBACK_THIRD_PARTY
            return hold.text, None

        if proposed is PreConfirmationIntent.OTHER:
            # ``other`` is what _action_payload manufactures for ANY unparseable
            # model content, so an UNVERIFIED speaker could never reach VERIFYING
            # when sarvam-30b narrated instead of emitting JSON. Fall back to the
            # deterministic keyword matcher; it proposes only a route, and code
            # still owns every transition and the verification comparator.
            proposed = deterministic_preconfirmation_intent(
                transcript,
                borrower_display_name=self.case.borrower_display_name,
            )
        route = route_speaker_utterance(transcript, proposed_intent=proposed)
        if route.reason_code != "speaker_identity_unresolved":
            self._resolve_speaker_identity_clarification()
        if route.identity_target is not None:
            await self._coordinator.transition(
                route.identity_target,
                reason_code=route.reason_code,
            )
        if route.identity_target is IdentityState.THIRD_PARTY:
            hold = self.third_party.next_hold()
            return hold.text, None
        if route.identity_target is IdentityState.VERIFYING:
            return self._reviewed_template(route.template_id), None
        if route.reason_code != "speaker_identity_unresolved":
            return self._reviewed_template(route.template_id), None
        return self._bounded_unresolved_speaker_response(validated_template)

    async def _invalid_promise_action(
        self,
        tool: ToolName,
        *,
        reason_code: str,
    ) -> ToolPermissionDenied:
        """Persist one redacted typed denial without exposing submitted facts."""

        snapshot = self.snapshot
        decision = ToolDecision(
            tool=tool,
            allowed=False,
            identity_state=snapshot.identity.value,
            call_state=snapshot.call.value,
            promise_state=snapshot.promise.value,
            reason=f"invalid_action_facts={reason_code}",
        )
        await self.ledger.append_tool_decision(
            call_id=self.call_id,
            ts=self.clock(),
            decision=decision,
            state=snapshot,
        )
        return ToolPermissionDenied(decision)

    async def _prepare_promise(
        self,
        transcript: str,
        amount_minor: int | None,
        date_phrase: str | None,
    ) -> str:
        if amount_minor is None:
            raise await self._invalid_promise_action(
                ToolName.CREATE_PROMISE_CANDIDATE,
                reason_code="missing_amount",
            )
        if date_phrase is None:
            raise await self._invalid_promise_action(
                ToolName.CREATE_PROMISE_CANDIDATE,
                reason_code="missing_date",
            )
        try:
            validated_amount = _validated_model_amount_minor(amount_minor)
            normalized_date = normalize_promise_date(
                date_phrase,
                demo_time_anchor=self.clock(),
            )
        except PromiseNormalizationError as error:
            raise await self._invalid_promise_action(
                ToolName.CREATE_PROMISE_CANDIDATE,
                reason_code=_promise_fact_denial_code(error),
            ) from error
        mutation = self._promise.plan_candidate(
            caller_phrase=transcript,
            amount=validated_amount // 100,
            date_phrase=normalized_date.isoformat(),
        )
        event = await self._tools.execute(
            ToolName.CREATE_PROMISE_CANDIDATE,
            facts=ToolFacts(
                amount_minor=validated_amount,
                date_is_allowed=True,
            ),
            operation=lambda: self._promise.apply_candidate(mutation),
        )
        if not isinstance(event, PromiseEvent) or self._promise.state is not PromiseState.CANDIDATE:
            raise ControllerToolEffectError("create promise effect was not applied")
        await self._promise.record_applied_event(event)
        await self._coordinator.transition(
            PromiseState.CANDIDATE,
            reason_code="promise_candidate_created",
        )
        read_back = await self._promise.read_back()
        await self._coordinator.transition(
            PromiseState.READ_BACK,
            reason_code="promise_read_back",
        )
        return read_back

    async def _correct_promise(
        self,
        transcript: str,
        amount_minor: int | None,
        date_phrase: str | None,
    ) -> str:
        if amount_minor is None and date_phrase is None:
            raise await self._invalid_promise_action(
                ToolName.CORRECT_PROMISE_CANDIDATE,
                reason_code="missing_correction",
            )
        try:
            validated_amount = (
                None if amount_minor is None else _validated_model_amount_minor(amount_minor)
            )
            normalized_date = (
                None
                if date_phrase is None
                else normalize_promise_date(
                    date_phrase,
                    demo_time_anchor=self.clock(),
                ).isoformat()
            )
        except PromiseNormalizationError as error:
            raise await self._invalid_promise_action(
                ToolName.CORRECT_PROMISE_CANDIDATE,
                reason_code=_promise_fact_denial_code(error),
            ) from error

        candidate = self._promise.candidate
        candidate_exists = (
            candidate is not None and self._promise.state in _CORRECTABLE_PROMISE_STATES
        )
        candidate_committed = self._promise.state is PromiseState.COMMITTED
        facts = ToolFacts(
            candidate_exists=candidate_exists,
            candidate_committed=candidate_committed,
        )
        if not candidate_exists or candidate_committed:
            result = await self._tools.execute(
                ToolName.CORRECT_PROMISE_CANDIDATE,
                facts=facts,
                operation=lambda: None,
            )
            raise ControllerToolEffectError(
                f"invalid correction unexpectedly authorized with result {result!r}"
            )

        mutation = self._promise.plan_correction(
            caller_phrase=transcript,
            amount=None if validated_amount is None else validated_amount // 100,
            date_phrase=normalized_date,
        )
        event = await self._tools.execute(
            ToolName.CORRECT_PROMISE_CANDIDATE,
            facts=facts,
            operation=lambda: self._promise.apply_candidate(mutation),
        )
        if not isinstance(event, PromiseEvent) or self._promise.state is not PromiseState.CORRECTED:
            raise ControllerToolEffectError("correct promise effect was not applied")
        await self._promise.record_applied_event(event)
        await self._coordinator.transition(
            PromiseState.CORRECTED,
            reason_code="promise_candidate_corrected",
        )
        read_back = await self._promise.read_back()
        await self._coordinator.transition(
            PromiseState.READ_BACK,
            reason_code="promise_read_back_after_correction",
        )
        return read_back

    async def _confirm_promise(self) -> tuple[str, Disposition]:
        await self._promise.record_explicit_affirmative()
        await self._coordinator.transition(
            PromiseState.CONFIRMED,
            reason_code="promise_explicitly_confirmed",
        )
        return "धन्यवाद। आपका वादा दर्ज हो गया है।", Disposition.PROMISE_CONFIRMED

    async def _commit_confirmed_promise(self) -> None:
        """Commit only after confirmation TTS completed successfully."""

        mutation = self._promise.plan_commit()
        result = await self._tools.execute(
            ToolName.COMMIT_PROMISE,
            facts=ToolFacts(
                candidate_exists=True,
                candidate_read_back=True,
                explicit_affirmative=True,
            ),
            operation=lambda: self._promise.apply_commit(mutation),
        )
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[1], PromiseEvent)
            or self._promise.state is not PromiseState.COMMITTED
        ):
            raise ControllerToolEffectError("commit promise effect was not applied")
        _outcome, event = result
        await self._promise.record_applied_event(event)

    async def _handle_confirmed(
        self,
        transcript: str,
        payload: Mapping[str, object],
    ) -> tuple[str, Disposition | None]:
        validation = validate_llm_action(
            payload,
            identity_state=self.snapshot.identity,
            promise_state=self.snapshot.promise,
            call_state=self.snapshot.call,
        )
        action = validation.action
        if validation.handover_requested:
            await self._coordinator.transition(
                IdentityState.UNVERIFIED,
                reason_code="explicit_handover",
            )
            # Nothing from the confirmed portion of the call is summarized or
            # replayed to the new speaker. The next prompt starts from a fixed
            # content-free assistant line only.
            self.history = ()
            return self._reviewed_template(TemplateId.ASK_FOR_BORROWER), None
        if not validation.accepted:
            return self._reviewed_template(TemplateId.CLARIFY), None
        if action.intent is Intent.OFFER_PROMISE:
            try:
                response = await self._prepare_promise(
                    transcript,
                    action.amount_minor,
                    action.date_phrase,
                )
            except ToolPermissionDenied:
                return self._reviewed_template(TemplateId.CLARIFY), None
            return response, None
        if action.intent is Intent.CORRECT_PROMISE:
            try:
                response = await self._correct_promise(
                    transcript,
                    action.amount_minor,
                    action.date_phrase,
                )
            except ToolPermissionDenied:
                return self._reviewed_template(TemplateId.CLARIFY), None
            return response, None
        if action.intent is Intent.CONFIRM:
            return await self._confirm_promise()
        if action.intent is Intent.DENY and self.snapshot.promise is PromiseState.READ_BACK:
            await self._promise.respond_to_read_back(explicit_affirmative=False)
            await self._coordinator.transition(
                PromiseState.ABANDONED,
                reason_code="promise_read_back_rejected",
            )
            return "ठीक है। कोई वादा दर्ज नहीं किया गया।", None
        return self._reviewed_template(TemplateId.CLARIFY), None

    async def run_turn(self, audio: bytes = b"text-mode-audio") -> ControllerTurn:
        """Run STT → isolated prompt → typed action → guard → TTS once."""

        if not self._started:
            raise RuntimeError("call must be started before processing a turn")
        if self.disposition is not None:
            raise ControllerClosedError("terminal call cannot process another turn")
        stt = await self.sarvam.transcribe(audio)
        return await self.run_transcript(str(stt.get("transcript", "")))

    async def run_transcript(self, transcript: str) -> ControllerTurn:
        """Run an already-finalized streaming transcript through policy and speech."""

        if not self._started:
            raise RuntimeError("call must be started before processing a turn")
        if self.disposition is not None:
            raise ControllerClosedError("terminal call cannot process another turn")
        if not transcript.strip():
            raise ValueError("finalized transcript must not be empty")
        handover: HandoverOutcome | None = None
        if self.snapshot.identity is IdentityState.CONFIRMED:
            handover = await self._handover.handle_turn(transcript)
            if handover is not None:
                self.verification = VerificationSession()
                self._pending_verification = PendingVerificationAttempt()
                self.third_party = ThirdPartySession(case_id=self.case.case_id)
                self.history = ()
        await self._begin_fresh_borrower_return(transcript)
        model_utterance = transcript
        if self.snapshot.identity is IdentityState.VERIFYING:
            model_utterance = verification_input_marker(
                VerificationSubmission(
                    birth_day_month=transcript,
                    reference_last4=transcript,
                )
            )
        context = build_llm_context(
            call_state=self.snapshot.call,
            identity_state=self.snapshot.identity,
            promise_state=self.snapshot.promise,
            case=self.case,
            current_utterance=model_utterance,
            # Unbounded history grew the prompt by two messages per turn, and a
            # prompt of repeated identical clarifications lengthened every later
            # turn. The audit trail stays whole in self.history; only the model
            # sees the recent window.
            history=self.history[-MAX_PROMPT_HISTORY_MESSAGES:],
        )
        chat = await self.sarvam.chat_completion(context.as_api_messages())
        payload = _action_payload(chat)
        self.history = (*self.history, PromptMessage(PromptRole.USER, model_utterance))

        if handover is not None:
            draft, disposition = handover.response_text, None
        elif self.snapshot.identity is IdentityState.CONFIRMED:
            draft, disposition = await self._handle_confirmed(transcript, payload)
        else:
            draft, disposition = await self._handle_preconfirmed(transcript, payload)
        speech, audio_response = await self._speak(draft)
        if disposition is Disposition.PROMISE_CONFIRMED:
            if self.disposition is not None:
                raise ControllerClosedError("call ended before confirmation audio completed")
            await self._commit_confirmed_promise()
        elif disposition is not None:
            await self._set_disposition(
                disposition,
                reason_code=f"terminal_{disposition.value.casefold()}",
            )
        return ControllerTurn(
            transcript=transcript,
            speech_text=speech,
            audio_response=audio_response,
            disposition=disposition,
        )

    async def opening_turn(self) -> ControllerTurn:
        """Speak the fixed blind greeting before any caller audio is processed."""

        if not self._started:
            raise RuntimeError("call must be started before the opening turn")
        if self.disposition is not None:
            raise ControllerClosedError("terminal call cannot speak an opening turn")
        speech, audio_response = await self._speak(
            self._reviewed_template(TemplateId.INTRO_ANTISCAM)
        )
        return ControllerTurn(
            transcript="",
            speech_text=speech,
            audio_response=audio_response,
            disposition=None,
        )

    async def speak_reviewed(self, template_id: TemplateId) -> ControllerTurn:
        """Guard and synthesize a fixed operational line without invoking the model."""

        if not self._started:
            raise RuntimeError("call must be started before speaking")
        if self.disposition is not None:
            raise ControllerClosedError("terminal call cannot speak")
        speech, audio_response = await self._speak(self._reviewed_template(template_id))
        return ControllerTurn(
            transcript="",
            speech_text=speech,
            audio_response=audio_response,
            disposition=None,
        )

    async def read_mock_account(self) -> object:
        """Exercise the real structural account-read gate."""

        return await self._tools.execute(
            ToolName.READ_MOCK_ACCOUNT,
            operation=lambda: self.case.account,
        )

    async def end_by_operator(self, reason: str) -> tuple[int, datetime]:
        """End a normal active call with a required operator reason."""

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("operator end reason must not be empty")
        if self.disposition not in {None, Disposition.ENDED_OPERATOR}:
            raise ControllerClosedError("terminal call cannot be ended again")
        if self.disposition is None and self.snapshot.call not in {
            CallState.ACTIVE,
            CallState.DEGRADED,
        }:
            raise ControllerClosedError("call is not active")

        return await self._set_disposition(
            Disposition.ENDED_OPERATOR,
            reason_code="operator_ended_normal_call",
            evidence_reason=f"operator_end:{normalized_reason}",
        )

    async def technical_failure(self, component: str = "stt") -> None:
        """Fail closed without allowing a business outcome."""

        if self.snapshot.promise in {
            PromiseState.CANDIDATE,
            PromiseState.READ_BACK,
            PromiseState.CORRECTED,
            PromiseState.CONFIRMED,
        }:
            await self._promise.abandon()
            await self._coordinator.transition(
                PromiseState.ABANDONED,
                reason_code="technical_failure_abandoned_candidate",
            )
        await self._coordinator.transition(
            CallState.DEGRADED,
            reason_code=f"{component}_technical_failure",
        )
        snapshot = self.snapshot
        await self.ledger.append_event(
            call_id=self.call_id,
            ts=self.clock(),
            event_type=LedgerEventType.TECHNICAL_FAILURE,
            state_before=snapshot,
            state_after=snapshot,
            redacted_reason=f"technical_failure:{component}",
        )
        await self._set_disposition(
            Disposition.ENDED_TECHNICAL,
            reason_code="terminal_ended_technical",
        )

    async def takeover(self, pending_work: asyncio.Task[object] | None = None) -> None:
        """Relock, cancel, silence, record, then end under operator control."""

        if self.snapshot.identity is IdentityState.CONFIRMED:
            await self._coordinator.transition(
                IdentityState.UNVERIFIED,
                reason_code="operator_takeover_relock",
            )
        if pending_work is not None:
            pending_work.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending_work
        await self._coordinator.transition(
            CallState.OPERATOR_TAKEOVER,
            reason_code="operator_takeover",
        )
        snapshot = self.snapshot
        await self.ledger.append_event(
            call_id=self.call_id,
            ts=self.clock(),
            event_type=LedgerEventType.OPERATOR_TAKEOVER,
            state_before=snapshot,
            state_after=snapshot,
            redacted_reason="operator_takeover_order_complete",
        )
        await self._set_disposition(
            Disposition.ENDED_OPERATOR,
            reason_code="terminal_ended_operator",
        )

    def event_types(self) -> tuple[str, ...]:
        """Return ordered event types for concise matrix failure diagnostics."""

        return tuple(
            str(row["type"])
            for row in self.ledger.connection.execute(
                "SELECT type FROM events WHERE call_id = ? ORDER BY seq",
                (self.call_id,),
            )
        )
