"""Production FastAPI application with deterministic external boundaries for browser E2E."""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
import struct
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

import app.voice as voice_module
from app.audio_spike import SAMPLE_RATE
from app.db import EvidenceLedger, migrate_schema
from app.main import (
    _discard_call_session,
    _end_normal_call,
    _production_voice_binding,
    _reconcile_registry_orphans,
    app,
)
from app.sarvam_client import SynthesizedSpeech
from app.seeds import reset_and_reseed_demo_cases
from app.stt import SttSessionRegistry
from app.takeover import TakeoverRegistry

JsonObject = dict[str, Any]
BROWSER_E2E_PCM = bytes(1_600 * 2)
BROWSER_E2E_WAV = (
    b"RIFF"
    + struct.pack("<I", 36 + len(BROWSER_E2E_PCM))
    + b"WAVEfmt "
    + struct.pack("<IHHIIHH", 16, 1, 1, 16_000, 32_000, 2, 16)
    + b"data"
    + struct.pack("<I", len(BROWSER_E2E_PCM))
    + BROWSER_E2E_PCM
)
SCRIPTED_TRANSCRIPTS = (
    "Rakesh bol raha hoon",
    "चौदह सितंबर, reference 4729",
    "pandrah sau next week",
)
SCRIPTED_ACTIONS = (
    {"intent": "borrower_present"},
    {"intent": "verification_response"},
    {
        "intent": "offer_promise",
        "amount_minor": 150_000,
        "date_phrase": "next week",
    },
)


class ScriptedDialogueClient:
    """Replace only the remote chat/TTS boundary while retaining the production controller."""

    def __init__(self, _api_key: str) -> None:
        self.last_llm_ms = 0.0
        self.last_tts_ms = 0.0
        self._action_index = 0

    async def transcribe(self, audio: bytes, **kwargs: object) -> JsonObject:
        raise AssertionError("production voice calls must use streaming STT")

    async def chat_completion(
        self,
        messages: Sequence[Mapping[str, object]],
        **kwargs: object,
    ) -> JsonObject:
        assert messages
        try:
            action = SCRIPTED_ACTIONS[self._action_index]
        except IndexError as error:
            raise AssertionError("browser E2E exhausted its dialogue script") from error
        self._action_index += 1
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(action, ensure_ascii=False),
                    }
                }
            ]
        }

    async def synthesize(self, text: str, **kwargs: object) -> JsonObject:
        assert text.strip()
        return {
            "audio_base64": base64.b64encode(BROWSER_E2E_WAV).decode("ascii"),
            "content_type": "audio/wav",
            "request_id": "browser-e2e-tts",
        }


class ScriptedStreamingSocket:
    """Emit finalized transcripts through the real streaming-STT adapter."""

    def __init__(self) -> None:
        self._index = 0

    async def transcribe(
        self,
        audio: str,
        encoding: str = "audio/wav",
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        assert audio
        assert encoding == "audio/wav"
        assert sample_rate == SAMPLE_RATE

    async def flush(self) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        return self

    async def __anext__(self) -> dict[str, object]:
        if self._index >= len(SCRIPTED_TRANSCRIPTS):
            await asyncio.Future()
            raise AssertionError("unreachable")
        await asyncio.sleep(0.05)
        transcript = SCRIPTED_TRANSCRIPTS[self._index]
        self._index += 1
        return {
            "type": "data",
            "data": {
                "transcript": transcript,
            },
        }


class FixedAudioCheck:
    """Return deterministic WAV bytes for the reviewed headphone-check route."""

    async def synthesize(self, approved_text: str) -> SynthesizedSpeech:
        assert approved_text.strip()
        return SynthesizedSpeech(
            audio=BROWSER_E2E_WAV,
            request_id="browser-e2e-audio-check",
        )


@asynccontextmanager
async def scripted_stream(_api_key: str) -> AsyncIterator[ScriptedStreamingSocket]:
    yield ScriptedStreamingSocket()


def _isolated_ledger() -> EvidenceLedger:
    connection = sqlite3.connect(
        ":memory:",
        check_same_thread=False,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    return EvidenceLedger(connection)


@asynccontextmanager
async def production_e2e_lifespan(application: Any) -> AsyncIterator[None]:
    """Initialize the production application with isolated, deterministic dependencies."""

    ledger = _isolated_ledger()
    reset_and_reseed_demo_cases(ledger)
    application.state.sarvam_api_key = "browser-e2e-backend-only-key"
    application.state.evidence_ledger = ledger
    application.state.stt_sessions = SttSessionRegistry()
    application.state.takeover_sessions = TakeoverRegistry()
    application.state.voice_calls = None
    application.state.tts_synthesizer = FixedAudioCheck()
    application.state.sarvam_stream_factory = scripted_stream
    application.state.orphan_call_reconciler = lambda call_id=None: _reconcile_registry_orphans(
        application,
        call_id,
    )
    application.state.stt_call_binding_factory = lambda call_id: _production_voice_binding(
        application,
        call_id,
    )
    application.state.call_session_registrar = lambda call_id: _production_voice_binding(
        application,
        call_id,
    )
    application.state.call_session_discard = lambda call_id: _discard_call_session(
        application,
        call_id,
    )
    application.state.normal_call_ender = lambda call_id, reason: _end_normal_call(
        application,
        call_id,
        reason,
    )
    try:
        yield
    finally:
        application.state.stt_sessions.cancel_all()
        application.state.voice_calls = None
        application.state.takeover_sessions = None
        application.state.stt_sessions = None
        application.state.tts_synthesizer = None
        application.state.sarvam_stream_factory = None
        application.state.orphan_call_reconciler = None
        application.state.stt_call_binding_factory = None
        application.state.call_session_registrar = None
        application.state.call_session_discard = None
        application.state.normal_call_ender = None
        ledger.close()
        application.state.evidence_ledger = None
        application.state.sarvam_api_key = None


voice_module.ProductionDialogueClient = ScriptedDialogueClient  # type: ignore[misc]
app.router.lifespan_context = production_e2e_lifespan
