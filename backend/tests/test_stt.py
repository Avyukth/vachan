"""Production STT timeout, degradation, and stale-callback tests."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.audio_spike import SAMPLE_RATE
from app.protocol import AgentAudioFrame, MediaFrameKind
from app.stt import (
    STT_RECOVERY_LINE,
    STT_WEBSOCKET_PATH,
    StreamingSttSession,
    SttOutcome,
    SttSessionRegistry,
    router,
)
from app.templates import TemplateId, is_bank_member, render_template


class FakeStream:
    def __init__(self) -> None:
        self.audio: list[bytes] = []
        self.flush_count = 0
        self.responses: asyncio.Queue[dict[str, Any] | Exception] = asyncio.Queue()
        self.fail_send = False
        self.fail_flush = False
        self.flushed = asyncio.Event()

    async def transcribe(
        self,
        audio: str,
        encoding: str = "audio/wav",
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        if self.fail_send:
            raise OSError("network unavailable")
        assert encoding == "audio/wav"
        assert sample_rate == SAMPLE_RATE
        self.audio.append(base64.b64decode(audio))

    async def flush(self) -> None:
        if self.fail_flush:
            raise OSError("network unavailable")
        self.flush_count += 1
        self.flushed.set()

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self

    async def __anext__(self) -> dict[str, Any]:
        item = await self.responses.get()
        if isinstance(item, Exception):
            raise item
        return item


class HangingStream(FakeStream):
    def __init__(self, operation: str) -> None:
        super().__init__()
        self.operation = operation
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def _hang(self) -> None:
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def transcribe(
        self,
        audio: str,
        encoding: str = "audio/wav",
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        if self.operation == "send":
            await self._hang()
            return
        await super().transcribe(audio, encoding, sample_rate)

    async def flush(self) -> None:
        if self.operation == "flush":
            await self._hang()
            return
        await super().flush()

    async def __anext__(self) -> dict[str, Any]:
        if self.operation == "receive" and self.responses.empty():
            await self._hang()
        return await super().__anext__()


@dataclass
class RecordingCallbacks:
    transcripts: list[tuple[str, str]] = field(default_factory=list)
    recovery_prompts: list[tuple[str, str]] = field(default_factory=list)
    degradations: list[tuple[str, str]] = field(default_factory=list)
    timings: list[tuple[str, float]] = field(default_factory=list)

    async def on_final_transcript(self, call_id: str, transcript: str) -> None:
        self.transcripts.append((call_id, transcript))

    async def on_recovery_prompt(self, call_id: str, line: str) -> None:
        self.recovery_prompts.append((call_id, line))

    async def on_degraded(self, call_id: str, reason_code: str) -> None:
        self.degradations.append((call_id, reason_code))

    async def on_stt_timing(self, call_id: str, elapsed_ms: float) -> None:
        self.timings.append((call_id, elapsed_ms))


@dataclass
class ActiveCall:
    value: bool = True

    def __call__(self) -> bool:
        return self.value


@dataclass
class RecordingBinding(RecordingCallbacks):
    active_call: ActiveCall = field(default_factory=ActiveCall)

    def is_call_active(self) -> bool:
        return self.active_call()


@dataclass
class BrowserEventBinding(RecordingBinding):
    events: asyncio.Queue[dict[str, object]] = field(default_factory=asyncio.Queue)
    media_seq: int = 0

    def frame(self, kind: MediaFrameKind) -> dict[str, object]:
        self.media_seq += 1
        return AgentAudioFrame(
            call_id="call-stt-001",
            media_seq=self.media_seq,
            ts=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
            kind=kind,
            audio_base64="UklGRg==",
            speech_text="सुरक्षित उत्तर।",
        ).model_dump(mode="json")

    async def on_connected(self) -> None:
        await self.events.put(self.frame(MediaFrameKind.OPENING))

    async def on_final_transcript(self, call_id: str, transcript: str) -> None:
        await super().on_final_transcript(call_id, transcript)
        await self.events.put(self.frame(MediaFrameKind.TURN))

    async def next_client_event(self) -> dict[str, object]:
        return await self.events.get()


@dataclass
class WrongCallBrowserEventBinding(BrowserEventBinding):
    async def on_connected(self) -> None:
        await self.events.put(
            AgentAudioFrame(
                call_id="call-other",
                media_seq=1,
                ts=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
                kind=MediaFrameKind.OPENING,
                audio_base64="UklGRg==",
                speech_text="यह गलत कॉल का फ़्रेम है।",
            ).model_dump(mode="json")
        )


def final_message(transcript: str) -> dict[str, Any]:
    return {
        "type": "data",
        "data": {
            "transcript": transcript,
            "metrics": {"processing_latency": 0.1},
        },
    }


def make_session(
    *,
    stream: FakeStream | None = None,
    callbacks: RecordingCallbacks | None = None,
    active_call: ActiveCall | None = None,
    timeout_seconds: float = 0.02,
) -> tuple[StreamingSttSession, FakeStream, RecordingCallbacks, ActiveCall]:
    stream = stream or FakeStream()
    callbacks = callbacks or RecordingCallbacks()
    active_call = active_call or ActiveCall()
    return (
        StreamingSttSession(
            call_id="call-stt-001",
            stream=stream,
            callbacks=callbacks,
            is_call_active=active_call,
            timeout_seconds=timeout_seconds,
        ),
        stream,
        callbacks,
        active_call,
    )


def test_pcm_is_sent_and_finalized_transcript_drives_controller() -> None:
    async def exercise() -> None:
        session, stream, callbacks, _ = make_session()
        pcm = b"\x01\x00\xff\xff" * 80

        assert (await session.send_pcm(pcm)).outcome is SttOutcome.SENT
        await stream.responses.put({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        await stream.responses.put(final_message("  नमस्ते जी  "))

        result = await session.finish_utterance()

        assert stream.audio == [pcm]
        assert stream.flush_count == 1
        assert result.outcome is SttOutcome.FINAL
        assert result.transcript == "नमस्ते जी"
        assert callbacks.transcripts == [("call-stt-001", "नमस्ते जी")]
        assert callbacks.recovery_prompts == []
        assert callbacks.degradations == []

    asyncio.run(exercise())


def test_first_timeout_speaks_once_and_second_consecutive_timeout_degrades() -> None:
    async def exercise() -> None:
        session, _, callbacks, _ = make_session(timeout_seconds=0.005)

        first = await session.finish_utterance()
        second = await session.finish_utterance()

        assert first.outcome is SttOutcome.RECOVERY
        assert second.outcome is SttOutcome.DEGRADED
        assert callbacks.recovery_prompts == [("call-stt-001", STT_RECOVERY_LINE)]
        assert callbacks.degradations == [("call-stt-001", "stt_timeout_consecutive")]
        assert not session.active

    asyncio.run(exercise())


def test_timeout_recovery_copy_comes_from_reviewed_registry() -> None:
    assert render_template(TemplateId.STT_RECOVERY) == STT_RECOVERY_LINE
    assert is_bank_member(STT_RECOVERY_LINE)


def test_success_resets_consecutive_timeout_recovery() -> None:
    async def exercise() -> None:
        session, stream, callbacks, _ = make_session(timeout_seconds=0.005)
        assert (await session.finish_utterance()).outcome is SttOutcome.RECOVERY

        await stream.responses.put(final_message("अब सुनाई दे रहा है"))
        assert (await session.finish_utterance()).outcome is SttOutcome.FINAL
        assert session.consecutive_timeouts == 0

        assert (await session.finish_utterance()).outcome is SttOutcome.RECOVERY
        assert callbacks.recovery_prompts == [
            ("call-stt-001", STT_RECOVERY_LINE),
            ("call-stt-001", STT_RECOVERY_LINE),
        ]
        assert callbacks.degradations == []

    asyncio.run(exercise())


def test_takeover_cancels_pending_result_and_drops_stale_callback() -> None:
    async def exercise() -> None:
        session, stream, callbacks, active_call = make_session(timeout_seconds=1)
        pending = asyncio.create_task(session.finish_utterance())
        await stream.flushed.wait()

        active_call.value = False
        session.cancel()
        await stream.responses.put(final_message("यह देर से आया परिणाम है"))

        result = await pending
        assert result.outcome is SttOutcome.DROPPED
        assert callbacks.transcripts == []
        assert callbacks.recovery_prompts == []
        assert callbacks.degradations == []

    asyncio.run(exercise())


def test_network_failure_degrades_without_reconnect_or_zombie_callback() -> None:
    async def exercise() -> None:
        session, stream, callbacks, _ = make_session()
        stream.fail_flush = True

        result = await session.finish_utterance()

        assert result.outcome is SttOutcome.DEGRADED
        assert callbacks.degradations == [("call-stt-001", "stt_network_failure")]
        assert callbacks.transcripts == []
        assert stream.flush_count == 0
        assert not session.active

    asyncio.run(exercise())


def test_network_failure_while_sending_degrades_and_rejects_later_audio() -> None:
    async def exercise() -> None:
        session, stream, callbacks, _ = make_session()
        stream.fail_send = True

        first = await session.send_pcm(b"\x00\x00")
        later = await session.send_pcm(b"\x00\x00")

        assert first.outcome is SttOutcome.DEGRADED
        assert later.outcome is SttOutcome.DROPPED
        assert callbacks.degradations == [("call-stt-001", "stt_network_failure")]

    asyncio.run(exercise())


@pytest.mark.parametrize("operation", ("send", "flush"))
def test_hanging_socket_request_is_bounded_and_degrades(operation: str) -> None:
    async def exercise() -> None:
        stream = HangingStream(operation)
        session, _, callbacks, _ = make_session(
            stream=stream,
            timeout_seconds=0.005,
        )

        if operation == "send":
            result = await session.send_pcm(b"\x00\x00")
        else:
            result = await session.flush_utterance()

        assert result.outcome is SttOutcome.DEGRADED
        assert result.reason == "stt_request_timeout"
        assert stream.cancelled.is_set()
        assert callbacks.degradations == [("call-stt-001", "stt_request_timeout")]
        assert callbacks.transcripts == []
        assert not session.active

    asyncio.run(exercise())


def test_takeover_interrupts_hanging_socket_request_without_callback() -> None:
    async def exercise() -> None:
        stream = HangingStream("send")
        session, _, callbacks, active_call = make_session(
            stream=stream,
            timeout_seconds=1,
        )
        pending = asyncio.create_task(session.send_pcm(b"\x00\x00"))
        await stream.started.wait()

        active_call.value = False
        session.cancel()

        result = await pending
        assert result.outcome is SttOutcome.DROPPED
        assert result.reason == "call_cancelled"
        assert stream.cancelled.is_set()
        assert callbacks.transcripts == []
        assert callbacks.recovery_prompts == []
        assert callbacks.degradations == []

    asyncio.run(exercise())


def test_continuous_vad_reader_drives_final_without_manual_flush() -> None:
    async def exercise() -> None:
        session, stream, callbacks, _ = make_session()
        reader = asyncio.create_task(session.run_finalized_results())

        await stream.responses.put({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        await stream.responses.put({"type": "events", "data": {"signal_type": "END_SPEECH"}})
        await stream.responses.put(final_message("सर्वर ने वाक्य पूरा किया"))
        for _ in range(10):
            if callbacks.transcripts:
                break
            await asyncio.sleep(0)

        assert callbacks.transcripts == [("call-stt-001", "सर्वर ने वाक्य पूरा किया")]
        assert callbacks.recovery_prompts == []
        session.cancel()
        assert (await reader).outcome is SttOutcome.DROPPED

    asyncio.run(exercise())


def test_continuous_reader_drops_late_final_then_degrades_on_second_timeout() -> None:
    async def exercise() -> None:
        session, stream, callbacks, _ = make_session(timeout_seconds=0.005)
        reader = asyncio.create_task(session.run_finalized_results())

        await stream.responses.put({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        await stream.responses.put({"type": "events", "data": {"signal_type": "END_SPEECH"}})
        await asyncio.sleep(0.01)
        assert callbacks.recovery_prompts == [("call-stt-001", STT_RECOVERY_LINE)]

        await stream.responses.put(final_message("देर से आया पहला परिणाम"))
        await asyncio.sleep(0)
        assert callbacks.transcripts == []

        await stream.responses.put({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        await stream.responses.put({"type": "events", "data": {"signal_type": "END_SPEECH"}})
        await asyncio.sleep(0.01)

        assert callbacks.degradations == [("call-stt-001", "stt_timeout_consecutive")]
        assert not session.active
        assert (await reader).outcome is SttOutcome.DROPPED
        assert callbacks.transcripts == []

    asyncio.run(exercise())


def test_continuous_reader_drops_result_after_takeover() -> None:
    async def exercise() -> None:
        session, stream, callbacks, active_call = make_session()
        reader = asyncio.create_task(session.run_finalized_results())
        await stream.responses.put({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        await asyncio.sleep(0)

        active_call.value = False
        session.cancel()
        await stream.responses.put(final_message("टेकओवर के बाद का परिणाम"))

        assert (await reader).outcome is SttOutcome.DROPPED
        assert callbacks.transcripts == []
        assert callbacks.recovery_prompts == []
        assert callbacks.degradations == []

    asyncio.run(exercise())


def test_continuous_reader_network_loss_degrades_without_reconnect() -> None:
    async def exercise() -> None:
        session, stream, callbacks, _ = make_session()
        reader = asyncio.create_task(session.run_finalized_results())

        await stream.responses.put(OSError("socket closed"))

        assert (await reader).outcome is SttOutcome.DEGRADED
        assert callbacks.degradations == [("call-stt-001", "stt_network_failure")]
        assert callbacks.transcripts == []
        assert not session.active

    asyncio.run(exercise())


def test_continuous_reader_receive_stall_is_bounded_and_degrades_once() -> None:
    async def exercise() -> None:
        stream = HangingStream("receive")
        session, _, callbacks, _ = make_session(
            stream=stream,
            timeout_seconds=0.005,
        )
        await stream.responses.put({"type": "events", "data": {"signal_type": "START_SPEECH"}})

        result = await session.run_finalized_results()

        assert result.outcome is SttOutcome.DEGRADED
        assert result.reason == "stt_receive_timeout"
        assert stream.started.is_set()
        assert stream.cancelled.is_set()
        assert callbacks.degradations == [("call-stt-001", "stt_receive_timeout")]
        assert callbacks.transcripts == []
        assert callbacks.recovery_prompts == []
        assert not session.active

    asyncio.run(exercise())


def test_pcm_arms_receive_stall_deadline_before_server_vad() -> None:
    async def exercise() -> None:
        stream = HangingStream("receive")
        session, _, callbacks, _ = make_session(
            stream=stream,
            timeout_seconds=0.005,
        )
        reader = asyncio.create_task(session.run_finalized_results())
        await stream.started.wait()

        sent = await session.send_pcm(b"\x00\x00")
        result = await reader

        assert sent.outcome is SttOutcome.SENT
        assert result.outcome is SttOutcome.DROPPED
        assert result.reason == "call_cancelled"
        assert stream.cancelled.is_set()
        assert callbacks.degradations == [("call-stt-001", "stt_receive_timeout")]
        assert callbacks.transcripts == []
        assert callbacks.recovery_prompts == []
        assert not session.active

    asyncio.run(exercise())


def test_continuous_reader_does_not_timeout_an_idle_borrower() -> None:
    async def exercise() -> None:
        session, _, callbacks, _ = make_session(timeout_seconds=0.005)
        reader = asyncio.create_task(session.run_finalized_results())

        await asyncio.sleep(0.01)

        assert session.active
        assert callbacks.degradations == []
        session.cancel()
        assert (await reader).outcome is SttOutcome.DROPPED

    asyncio.run(exercise())


def test_takeover_interrupts_pre_vad_receive_stall_without_callback() -> None:
    async def exercise() -> None:
        stream = HangingStream("receive")
        session, _, callbacks, active_call = make_session(
            stream=stream,
            timeout_seconds=1,
        )
        reader = asyncio.create_task(session.run_finalized_results())
        await stream.started.wait()
        assert (await session.send_pcm(b"\x00\x00")).outcome is SttOutcome.SENT

        active_call.value = False
        session.cancel()

        result = await reader
        assert result.outcome is SttOutcome.DROPPED
        assert result.reason == "call_cancelled"
        assert stream.cancelled.is_set()
        assert callbacks.transcripts == []
        assert callbacks.recovery_prompts == []
        assert callbacks.degradations == []

    asyncio.run(exercise())


def test_takeover_interrupts_receive_stall_without_late_callback() -> None:
    async def exercise() -> None:
        stream = HangingStream("receive")
        session, _, callbacks, active_call = make_session(
            stream=stream,
            timeout_seconds=1,
        )
        await stream.responses.put({"type": "events", "data": {"signal_type": "START_SPEECH"}})
        reader = asyncio.create_task(session.run_finalized_results())
        await stream.started.wait()

        active_call.value = False
        session.cancel()

        result = await reader
        assert result.outcome is SttOutcome.DROPPED
        assert result.reason == "call_cancelled"
        assert stream.cancelled.is_set()
        assert callbacks.transcripts == []
        assert callbacks.recovery_prompts == []
        assert callbacks.degradations == []

    asyncio.run(exercise())


def test_registry_replacement_and_call_cancellation_are_immediate() -> None:
    async def exercise() -> None:
        first, _, _, _ = make_session()
        second, _, _, _ = make_session()
        registry = SttSessionRegistry()

        registry.register(first)
        registry.register(second)

        assert not first.active
        assert second.active
        assert registry.cancel_call("call-stt-001")
        assert not second.active
        assert not registry.cancel_call("call-stt-001")

    asyncio.run(exercise())


def test_production_websocket_routes_only_final_text_to_call_binding() -> None:
    stream = FakeStream()
    binding = RecordingBinding()
    stream.responses.put_nowait(final_message("मेरी आवाज आ रही है"))

    @asynccontextmanager
    async def stream_factory(api_key: str) -> AsyncIterator[FakeStream]:
        assert api_key == "backend-only-key"
        yield stream

    app = FastAPI()
    app.state.sarvam_api_key = "backend-only-key"
    app.state.sarvam_stream_factory = stream_factory
    app.state.stt_call_binding_factory = lambda call_id: binding
    app.state.stt_sessions = SttSessionRegistry()
    app.include_router(router)

    path = STT_WEBSOCKET_PATH.format(call_id="call-stt-001")
    with TestClient(app).websocket_connect(path) as websocket:
        assert websocket.receive_json() == {
            "api_version": "v0",
            "type": "ready",
            "call_id": "call-stt-001",
            "sample_rate": SAMPLE_RATE,
            "encoding": "pcm_s16le",
        }
        websocket.send_bytes(b"\x00")
        assert websocket.receive_json() == {
            "api_version": "v0",
            "type": "transport_error",
            "call_id": "call-stt-001",
            "detail": "PCM16 chunk must contain complete signed 16-bit samples",
        }
        websocket.send_bytes(b"\x01\x00")
        websocket.send_text('{"type":"flush"}')

    assert stream.audio == [b"\x01\x00"]
    assert binding.transcripts == [("call-stt-001", "मेरी आवाज आ रही है")]
    assert binding.degradations == []
    assert not app.state.stt_sessions.cancel_call("call-stt-001")


def test_production_websocket_sends_opening_and_controller_turn_to_browser() -> None:
    stream = FakeStream()
    binding = BrowserEventBinding()
    stream.responses.put_nowait({"type": "events", "data": {"signal_type": "START_SPEECH"}})
    stream.responses.put_nowait({"type": "events", "data": {"signal_type": "END_SPEECH"}})
    stream.responses.put_nowait(final_message("Rakesh bol raha hoon"))

    @asynccontextmanager
    async def stream_factory(api_key: str) -> AsyncIterator[FakeStream]:
        yield stream

    app = FastAPI()
    app.state.sarvam_api_key = "backend-only-key"
    app.state.sarvam_stream_factory = stream_factory
    app.state.stt_call_binding_factory = lambda call_id: binding
    app.state.stt_sessions = SttSessionRegistry()
    app.include_router(router)

    path = STT_WEBSOCKET_PATH.format(call_id="call-stt-001")
    with TestClient(app).websocket_connect(path) as websocket:
        assert websocket.receive_json() == {
            "api_version": "v0",
            "type": "ready",
            "call_id": "call-stt-001",
            "sample_rate": SAMPLE_RATE,
            "encoding": "pcm_s16le",
        }
        opening = websocket.receive_json()
        assert opening["type"] == "agent_audio"
        assert opening["source"] == "transient_media"
        assert opening["call_id"] == "call-stt-001"
        assert opening["media_seq"] == 1
        assert opening["kind"] == "opening"
        websocket.send_bytes(b"\x01\x00")
        websocket.send_text('{"type":"flush"}')
        turn = websocket.receive_json()
        assert turn["type"] == "agent_audio"
        assert turn["source"] == "transient_media"
        assert turn["call_id"] == "call-stt-001"
        assert turn["media_seq"] == 2
        assert turn["kind"] == "turn"

    assert binding.transcripts == [("call-stt-001", "Rakesh bol raha hoon")]
    assert binding.timings
    assert binding.timings[0][0] == "call-stt-001"
    assert binding.timings[0][1] >= 0


def test_production_websocket_rejects_cross_call_media_before_send() -> None:
    stream = FakeStream()
    binding = WrongCallBrowserEventBinding()

    @asynccontextmanager
    async def stream_factory(api_key: str) -> AsyncIterator[FakeStream]:
        assert api_key == "backend-only-key"
        yield stream

    app = FastAPI()
    app.state.sarvam_api_key = "backend-only-key"
    app.state.sarvam_stream_factory = stream_factory
    app.state.stt_call_binding_factory = lambda call_id: binding
    app.state.stt_sessions = SttSessionRegistry()
    app.include_router(router)

    path = STT_WEBSOCKET_PATH.format(call_id="call-stt-001")
    with TestClient(app).websocket_connect(path) as websocket:
        assert websocket.receive_json()["type"] == "ready"
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_json()

    assert closed.value.code == 1011
    assert binding.degradations == [("call-stt-001", "stt_network_failure")]


def test_production_websocket_rejects_inactive_call_before_opening_stream() -> None:
    binding = RecordingBinding(active_call=ActiveCall(False))
    app = FastAPI()
    app.state.sarvam_api_key = "backend-only-key"
    app.state.stt_call_binding_factory = lambda call_id: binding
    app.include_router(router)

    path = STT_WEBSOCKET_PATH.format(call_id="ended-call")
    with TestClient(app).websocket_connect(path) as websocket:
        assert websocket.receive_json() == {
            "api_version": "v0",
            "type": "transport_error",
            "call_id": "ended-call",
            "detail": "Call is not active",
        }
