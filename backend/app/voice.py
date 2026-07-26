"""Production voice-call binding across streaming STT, policy, LLM, and TTS."""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.controller import ControllerTurn, DialogueController
from app.db import EvidenceLedger
from app.llm import (
    MAX_RESPONSE_TOKENS,
    LLMIntegrationError,
    SarvamChatClient,
)
from app.protocol import TransportMode
from app.sarvam_client import SarvamTextToSpeechClient, SarvamTextToSpeechError
from app.seeds import DEMO_CASES
from app.states import CallState
from app.stt import SttSessionRegistry
from app.takeover import BreakGlassTakeover, TakeoverRegistry, TakeoverResult

JsonObject = dict[str, Any]
_CASES_BY_ID = {case.case_id: case for case in DEMO_CASES}
PRODUCTION_VOICE_LLM_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class NormalOperatorEnd:
    call_id: str
    disposition_seq: int
    ts: datetime


class ProductionDialogueClient:
    """Network adapter with safe envelopes and per-stage latency measurements."""

    def __init__(self, api_key: str) -> None:
        self._chat = SarvamChatClient(api_key)
        self._tts = SarvamTextToSpeechClient(api_key)
        self.last_llm_ms = 0.0
        self.last_tts_ms = 0.0

    async def transcribe(self, audio: bytes, **kwargs: object) -> JsonObject:
        """Reject accidental second STT; streaming transcripts enter directly."""

        raise RuntimeError("production voice calls use streaming STT transcripts")

    async def chat_completion(
        self,
        messages: Sequence[Mapping[str, object]],
        **kwargs: object,
    ) -> JsonObject:
        safe_messages: list[dict[str, str]] = []
        for message in messages:
            role = message.get("role")
            content = message.get("content")
            if not isinstance(role, str) or not isinstance(content, str):
                raise ValueError("LLM messages require string role and content")
            safe_messages.append({"role": role, "content": content})

        started_at = time.perf_counter()
        content = await self._chat.complete(
            safe_messages,
            timeout_seconds=PRODUCTION_VOICE_LLM_TIMEOUT_SECONDS,
            max_tokens=MAX_RESPONSE_TOKENS,
        )
        self.last_llm_ms = (time.perf_counter() - started_at) * 1000
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": content,
                    }
                }
            ]
        }

    async def synthesize(self, text: str, **kwargs: object) -> JsonObject:
        started_at = time.perf_counter()
        speech = await self._tts.synthesize(text)
        self.last_tts_ms = (time.perf_counter() - started_at) * 1000
        return {
            "audio_base64": base64.b64encode(speech.audio).decode("ascii"),
            "content_type": speech.content_type,
            "request_id": speech.request_id,
        }


class VoiceCallBinding:
    """Call-scoped STT callbacks and browser event queue."""

    def __init__(
        self,
        *,
        controller: DialogueController,
        dialogue_client: ProductionDialogueClient,
    ) -> None:
        self.call_id = controller.call_id
        self.controller = controller
        self._dialogue_client = dialogue_client
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=8)
        self._turn_lock = asyncio.Lock()
        self._connected = False
        self._agent_enabled = True
        self._stt_ms = 0.0

    def is_call_active(self) -> bool:
        row = self.controller.ledger.connection.execute(
            "SELECT disposition FROM calls WHERE id = ?",
            (self.call_id,),
        ).fetchone()
        return (
            self._agent_enabled
            and row is not None
            and row["disposition"] is None
            and self.controller.disposition is None
        )

    def revoke_agent(self) -> None:
        """Synchronously block every future model, tool, and audio callback."""

        self._agent_enabled = False

    def stop_generated_speech(self) -> None:
        """Synchronously discard any queued audio that has not reached the browser."""

        while not self._events.empty():
            self._events.get_nowait()

    async def prepare_takeover(self) -> None:
        """Revoke first and legally activate a call that has not opened its WebSocket."""

        self.revoke_agent()
        async with self._turn_lock:
            if self.controller.snapshot.call is CallState.IDLE:
                await self.controller.activate_existing_call()
                self._connected = True

    async def on_connected(self) -> None:
        async with self._turn_lock:
            if self._connected:
                return
            await self.controller.activate_existing_call()
            started_at = time.perf_counter()
            try:
                opening = await self.controller.opening_turn()
            except SarvamTextToSpeechError:
                await self._end_technical_locked("tts_unavailable")
                self._connected = True
                return
            except Exception:
                await self._end_technical_locked("backend_failure")
                self._connected = True
                return
            tts_ms = self._dialogue_client.last_tts_ms
            total_ms = max((time.perf_counter() - started_at) * 1000, tts_ms)
            await self._events.put(
                self._browser_turn(
                    opening,
                    kind="opening",
                    stt_ms=0.0,
                    llm_ms=0.0,
                    tts_ms=tts_ms,
                    total_ms=total_ms,
                )
            )
            self._connected = True

    async def on_stt_timing(self, call_id: str, elapsed_ms: float) -> None:
        if call_id == self.call_id:
            self._stt_ms = max(0.0, elapsed_ms)

    async def on_final_transcript(self, call_id: str, transcript: str) -> None:
        if call_id != self.call_id or not self.is_call_active():
            return
        async with self._turn_lock:
            if not self.is_call_active():
                return
            started_at = time.perf_counter()
            try:
                turn = await self.controller.run_transcript(transcript)
            except LLMIntegrationError:
                await self._end_technical_locked("llm_unavailable")
                return
            except SarvamTextToSpeechError:
                await self._end_technical_locked("tts_unavailable")
                return
            except Exception:
                await self._end_technical_locked("backend_failure")
                return
            controller_ms = (time.perf_counter() - started_at) * 1000
            llm_ms = self._dialogue_client.last_llm_ms
            tts_ms = self._dialogue_client.last_tts_ms
            total_ms = max(
                self._stt_ms + controller_ms,
                self._stt_ms + llm_ms + tts_ms,
            )
            await self._record_timing(
                stt_ms=self._stt_ms,
                llm_ms=llm_ms,
                tts_ms=tts_ms,
                total_ms=total_ms,
            )
            event = self._browser_turn(
                turn,
                kind="turn",
                stt_ms=self._stt_ms,
                llm_ms=llm_ms,
                tts_ms=tts_ms,
                total_ms=total_ms,
            )
            await self._events.put(event)
            self._stt_ms = 0.0

    async def on_recovery_prompt(self, call_id: str, line: str) -> None:
        if call_id != self.call_id or not self.is_call_active():
            return
        async with self._turn_lock:
            if not self.is_call_active():
                return
            started_at = time.perf_counter()
            try:
                turn = await self.controller.speak_reviewed(line)
            except SarvamTextToSpeechError:
                await self._end_technical_locked("tts_unavailable")
                return
            except Exception:
                await self._end_technical_locked("backend_failure")
                return
            tts_ms = self._dialogue_client.last_tts_ms
            total_ms = max((time.perf_counter() - started_at) * 1000, tts_ms)
            await self._events.put(
                self._browser_turn(
                    turn,
                    kind="recovery",
                    stt_ms=0.0,
                    llm_ms=0.0,
                    tts_ms=tts_ms,
                    total_ms=total_ms,
                )
            )

    async def on_degraded(self, call_id: str, reason_code: str) -> None:
        if call_id != self.call_id or not self.is_call_active():
            return
        async with self._turn_lock:
            if not self.is_call_active():
                return
            await self._end_technical_locked(reason_code)

    async def next_client_event(self) -> dict[str, object]:
        return await self._events.get()

    async def end_by_operator(self, reason: str) -> NormalOperatorEnd:
        """Stop a non-takeover rehearsal with one terminal disposition."""

        async with self._turn_lock:
            seq, timestamp = await self.controller.end_by_operator(reason)
            return NormalOperatorEnd(
                call_id=self.call_id,
                disposition_seq=seq,
                ts=timestamp,
            )

    async def _end_technical_locked(self, reason_code: str) -> None:
        """Persist one component-typed technical ending while holding the turn lock."""

        if not self._connected:
            await self.controller.activate_existing_call()
            self._connected = True
        await self.controller.technical_failure(reason_code)
        await self._events.put(
            {
                "type": "call_degraded",
                "call_id": self.call_id,
                "reason": reason_code,
            }
        )

    async def _record_timing(
        self,
        *,
        stt_ms: float,
        llm_ms: float,
        tts_ms: float,
        total_ms: float,
    ) -> None:
        snapshot = self.controller.snapshot
        reason = (
            f"turn_timing:stt_ms={round(stt_ms)};"
            f"llm_ms={round(llm_ms)};"
            f"tts_ms={round(tts_ms)};"
            f"total_ms={round(total_ms)}"
        )
        await self.controller.ledger.append_event(
            call_id=self.call_id,
            ts=datetime.now(UTC),
            event_type="TURN_TIMING",
            state_before=snapshot,
            state_after=snapshot,
            redacted_reason=reason,
        )

    def _browser_turn(
        self,
        turn: ControllerTurn,
        *,
        kind: str,
        stt_ms: float,
        llm_ms: float,
        tts_ms: float,
        total_ms: float,
    ) -> dict[str, object]:
        encoded_audio = turn.audio_response.get("audio_base64")
        content_type = turn.audio_response.get("content_type", "audio/wav")
        if not isinstance(encoded_audio, str) or not encoded_audio:
            raise ValueError("controller TTS response is missing encoded audio")
        if not isinstance(content_type, str) or content_type != "audio/wav":
            raise ValueError("controller TTS response must be WAV audio")
        total_ms = max(total_ms, stt_ms + llm_ms + tts_ms)
        return {
            "type": "agent_audio",
            "kind": kind,
            "call_id": self.call_id,
            "transcript": turn.transcript,
            "speech_text": turn.speech_text,
            "audio_base64": encoded_audio,
            "content_type": content_type,
            "disposition": None if turn.disposition is None else turn.disposition.value,
            "timings": {
                "stt_ms": round(stt_ms),
                "llm_ms": round(llm_ms),
                "tts_ms": round(tts_ms),
                "total_ms": round(total_ms),
            },
        }


class ProductionBreakGlassTakeover(BreakGlassTakeover):
    """Share the voice controller while supporting takeover before microphone connect."""

    def attach_binding(self, binding: VoiceCallBinding) -> None:
        """Attach the binding before publishing this boundary in the registry."""

        self._binding = binding

    async def takeover(self) -> TakeoverResult:
        if self._binding.controller.snapshot.call is CallState.IDLE:
            await self._binding.prepare_takeover()
        return await super().takeover()


class ProductionVoiceRegistry:
    """Lazily create one production binding for each preflight-created call."""

    def __init__(
        self,
        *,
        ledger: EvidenceLedger,
        api_key: str,
        takeover_sessions: TakeoverRegistry,
        stt_sessions: SttSessionRegistry,
    ) -> None:
        self._ledger = ledger
        self._api_key = api_key
        self._takeover_sessions = takeover_sessions
        self._stt_sessions = stt_sessions
        self._calls: dict[str, VoiceCallBinding] = {}

    def binding_for(self, call_id: str) -> VoiceCallBinding:
        existing = self._calls.get(call_id)
        if existing is not None:
            return existing
        row = self._ledger.connection.execute(
            "SELECT case_id FROM calls WHERE id = ? AND disposition IS NULL",
            (call_id,),
        ).fetchone()
        if row is None:
            raise LookupError("active call does not exist")
        case = _CASES_BY_ID.get(str(row["case_id"]))
        if case is None:
            raise LookupError("call is not backed by a governed demo case")
        dialogue_client = ProductionDialogueClient(self._api_key)
        controller = DialogueController(
            call_id=call_id,
            case=case,
            ledger=self._ledger,
            sarvam=dialogue_client,
            clock=lambda: datetime.now(UTC),
            transport=TransportMode.STREAMING_PCM16_WS.value,
        )
        binding = VoiceCallBinding(
            controller=controller,
            dialogue_client=dialogue_client,
        )
        takeover = ProductionBreakGlassTakeover(
            state=controller.coordinator,
            event_writer=self._ledger,
            end_writer=self._ledger,
            revoke_tools=binding.revoke_agent,
            cancel_pending_work=lambda: ("stt",) if self._stt_sessions.cancel_call(call_id) else (),
            stop_generated_speech=binding.stop_generated_speech,
        )
        takeover.attach_binding(binding)
        self._calls[call_id] = binding
        self._takeover_sessions.register(takeover)
        return binding

    def discard(self, call_id: str) -> None:
        binding = self._calls.pop(call_id, None)
        if binding is not None:
            binding.revoke_agent()
            binding.stop_generated_speech()
        self._stt_sessions.cancel_call(call_id)
        self._takeover_sessions.discard(call_id)

    async def end_by_operator(self, call_id: str, reason: str) -> NormalOperatorEnd:
        binding = self._calls.get(call_id)
        if binding is None:
            raise LookupError("active voice call does not exist")
        return await binding.end_by_operator(reason)
