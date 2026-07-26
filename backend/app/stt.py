"""Production Saaras streaming lifecycle with fail-closed cancellation."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.audio_spike import (
    SAMPLE_RATE,
    SarvamStreamingSocket,
    encode_pcm_chunk,
    open_sarvam_stream,
    response_payload,
)
from app.protocol import (
    VOICE_SERVER_FRAME_ADAPTER,
    AgentAudioFrame,
    VoiceReadyFrame,
    VoiceServerFrame,
    VoiceTransportErrorFrame,
)
from app.templates import TemplateId, render_template

STT_REQUEST_TIMEOUT_SECONDS = 8.0
STT_RECOVERY_LINE = render_template(TemplateId.STT_RECOVERY)
STT_WEBSOCKET_PATH = "/ws/call/{call_id}"

router = APIRouter(tags=["speech-to-text"])


class SttOutcome(StrEnum):
    """Typed outcomes consumed by the WebSocket/controller integration."""

    SENT = "sent"
    FINAL = "final"
    RECOVERY = "recovery"
    DEGRADED = "degraded"
    DROPPED = "dropped"


@dataclass(frozen=True, slots=True)
class SttResult:
    """One transport result without raw exceptions or private audio."""

    outcome: SttOutcome
    transcript: str | None = None
    reason: str | None = None


class SttCallbacks(Protocol):
    """Controller-owned effects triggered by finalized transport outcomes."""

    async def on_final_transcript(self, call_id: str, transcript: str) -> None:
        """Persist the utterance and drive the deterministic controller."""

    async def on_recovery_prompt(self, call_id: str, line: str) -> None:
        """Speak the reviewed one-time clarification line."""

    async def on_degraded(self, call_id: str, reason_code: str) -> None:
        """Transition the call to DEGRADED and persist technical evidence."""


class SttCallBinding(SttCallbacks, Protocol):
    """Controller callbacks plus the authoritative current-call state check."""

    def is_call_active(self) -> bool:
        """Return whether STT callbacks may still affect this call."""


class SttClientEventSource(Protocol):
    """Optional binding surface for controller audio/events sent to the browser."""

    async def on_connected(self) -> None:
        """Activate the call and enqueue its blind greeting."""

    async def next_client_event(self) -> VoiceServerFrame:
        """Wait for the next safe controller-owned browser event."""


CallIsActive = Callable[[], bool]
CallBindingFactory = Callable[[str], SttCallBinding]
StreamFactory = Callable[
    [str],
    AbstractAsyncContextManager[SarvamStreamingSocket],
]


def _final_transcript(message: Any) -> str | None:
    """Extract only finalized Saaras data messages; ignore VAD/control frames."""
    payload = _message_payload(message)
    if payload.get("type") != "data":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    transcript = data.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    return transcript.strip()


def _message_payload(message: Any) -> dict[str, Any]:
    return message if isinstance(message, dict) else response_payload(message)


def _vad_signal(message: Any) -> str | None:
    payload = _message_payload(message)
    if payload.get("type") != "events":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    signal = data.get("signal_type")
    return signal if isinstance(signal, str) else None


class StreamingSttSession:
    """Own one call's single Saaras stream; never reconnect mid-utterance.

    Takeover/end calls :meth:`cancel`, which flips the active bit synchronously
    before cancelling the pending receive. Every controller callback checks both
    that bit and the authoritative call-state predicate immediately beforehand.
    """

    def __init__(
        self,
        *,
        call_id: str,
        stream: SarvamStreamingSocket,
        callbacks: SttCallbacks,
        is_call_active: CallIsActive,
        timeout_seconds: float = STT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not call_id.strip():
            raise ValueError("call_id must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.call_id = call_id
        self._stream = stream
        self._responses = stream.__aiter__()
        self._callbacks = callbacks
        self._is_call_active = is_call_active
        self._timeout_seconds = timeout_seconds
        self._consecutive_timeouts = 0
        self._active = True
        self._generation = 0
        self._pending_result: asyncio.Task[str] | None = None
        self._reader_task: asyncio.Task[SttResult] | None = None
        self._deadline_task: asyncio.Task[None] | None = None
        self._io_task: asyncio.Task[Any] | None = None
        self._utterance_id = 0
        self._waiting_for_final = False
        self._timed_out_utterance: int | None = None
        self._final_wait_started_at: float | None = None
        self._utterance_lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        """Whether this stream can still produce controller effects."""
        return self._active

    @property
    def consecutive_timeouts(self) -> int:
        """Expose the recovery counter for controller diagnostics."""
        return self._consecutive_timeouts

    def _call_is_active(self) -> bool:
        try:
            return self._is_call_active()
        except Exception:
            # An unreadable call state is not authority to emit a callback.
            return False

    def _is_current(self, generation: int) -> bool:
        return self._active and generation == self._generation and self._call_is_active()

    def cancel(self) -> None:
        """Synchronously suppress every future callback and pending result."""
        if not self._active:
            return
        self._active = False
        self._generation += 1
        self._cancel_background_tasks()

    def _cancel_background_tasks(self) -> None:
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        for task in (
            self._pending_result,
            self._reader_task,
            self._deadline_task,
            self._io_task,
        ):
            if task is not None and task is not current:
                task.cancel()

    async def _bounded_stream_request(
        self,
        generation: int,
        request: Callable[[], Awaitable[None]],
    ) -> SttResult | None:
        """Bound one socket write and make call cancellation interrupt it."""
        current = asyncio.current_task()
        assert current is not None
        self._io_task = current
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await request()
        except TimeoutError:
            return await self._degrade(generation, "stt_request_timeout")
        except asyncio.CancelledError:
            if not self._is_current(generation):
                return SttResult(SttOutcome.DROPPED, reason="call_cancelled")
            raise
        except Exception:
            return await self._degrade(generation, "stt_network_failure")
        finally:
            if self._io_task is current:
                self._io_task = None
        return None

    async def send_pcm(self, chunk: bytes) -> SttResult:
        """Send one validated PCM16/16kHz chunk or degrade on network loss."""
        generation = self._generation
        if not self._is_current(generation):
            self.cancel()
            return SttResult(SttOutcome.DROPPED, reason="call_inactive")

        encoded = encode_pcm_chunk(chunk)
        request_result = await self._bounded_stream_request(
            generation,
            lambda: self._stream.transcribe(
                audio=encoded,
                encoding="audio/wav",
                sample_rate=SAMPLE_RATE,
            ),
        )
        if request_result is not None:
            return request_result

        if not self._is_current(generation):
            self.cancel()
            return SttResult(SttOutcome.DROPPED, reason="call_inactive")
        return SttResult(SttOutcome.SENT)

    async def _receive_final(self, generation: int) -> str:
        while self._is_current(generation):
            try:
                message = await anext(self._responses)
            except StopAsyncIteration as error:
                raise ConnectionError("Saaras stream closed before a final result") from error
            transcript = _final_transcript(message)
            if transcript is not None:
                return transcript
        raise asyncio.CancelledError

    async def _degrade(self, generation: int, reason_code: str) -> SttResult:
        if not self._is_current(generation):
            self.cancel()
            return SttResult(SttOutcome.DROPPED, reason="call_inactive")

        # Close this transport before the callback can await or trigger teardown.
        self._active = False
        self._generation += 1
        self._cancel_background_tasks()
        await self._callbacks.on_degraded(self.call_id, reason_code)
        return SttResult(SttOutcome.DEGRADED, reason=reason_code)

    def _begin_utterance(self) -> int:
        if self._deadline_task is not None:
            self._deadline_task.cancel()
        self._utterance_id += 1
        self._waiting_for_final = True
        self._timed_out_utterance = None
        return self._utterance_id

    def _arm_final_deadline(self, generation: int) -> None:
        if not self._waiting_for_final:
            self._begin_utterance()
        if self._deadline_task is not None:
            self._deadline_task.cancel()
        utterance_id = self._utterance_id
        self._final_wait_started_at = time.perf_counter()
        self._deadline_task = asyncio.create_task(
            self._watch_final_deadline(generation, utterance_id)
        )

    async def _record_stt_timing(self) -> None:
        started_at = self._final_wait_started_at
        self._final_wait_started_at = None
        if started_at is None:
            return
        callback = getattr(self._callbacks, "on_stt_timing", None)
        if callback is not None:
            await callback(self.call_id, (time.perf_counter() - started_at) * 1000)

    async def _watch_final_deadline(self, generation: int, utterance_id: int) -> None:
        await asyncio.sleep(self._timeout_seconds)
        if (
            not self._is_current(generation)
            or not self._waiting_for_final
            or utterance_id != self._utterance_id
        ):
            return

        self._waiting_for_final = False
        self._timed_out_utterance = utterance_id
        self._consecutive_timeouts += 1
        if self._consecutive_timeouts >= 2:
            await self._degrade(generation, "stt_timeout_consecutive")
            return
        if self._is_current(generation):
            await self._callbacks.on_recovery_prompt(self.call_id, STT_RECOVERY_LINE)

    async def flush_utterance(self) -> SttResult:
        """Flush the current continuous stream and arm its final-result deadline."""
        generation = self._generation
        if not self._is_current(generation):
            self.cancel()
            return SttResult(SttOutcome.DROPPED, reason="call_inactive")
        request_result = await self._bounded_stream_request(
            generation,
            self._stream.flush,
        )
        if request_result is not None:
            return request_result
        if not self._is_current(generation):
            self.cancel()
            return SttResult(SttOutcome.DROPPED, reason="call_inactive")
        self._arm_final_deadline(generation)
        return SttResult(SttOutcome.SENT)

    async def run_finalized_results(self) -> SttResult:
        """Continuously consume VAD/final messages for the production call stream."""
        if self._reader_task is not None:
            raise RuntimeError("Saaras result reader is already running")
        generation = self._generation
        current = asyncio.current_task()
        assert current is not None
        self._reader_task = current
        try:
            while self._is_current(generation):
                message = await anext(self._responses)
                signal = _vad_signal(message)
                if signal == "START_SPEECH":
                    self._begin_utterance()
                elif signal == "END_SPEECH":
                    self._arm_final_deadline(generation)

                transcript = _final_transcript(message)
                if transcript is None:
                    continue
                if (
                    self._timed_out_utterance is not None
                    and self._timed_out_utterance == self._utterance_id
                    and not self._waiting_for_final
                ):
                    # A timed-out utterance can never become a later controller turn.
                    continue
                if not self._waiting_for_final:
                    self._begin_utterance()
                self._waiting_for_final = False
                if self._deadline_task is not None:
                    self._deadline_task.cancel()
                    self._deadline_task = None
                if not self._is_current(generation):
                    return SttResult(SttOutcome.DROPPED, reason="stale_result")
                self._consecutive_timeouts = 0
                await self._record_stt_timing()
                await self._callbacks.on_final_transcript(self.call_id, transcript)
            return SttResult(SttOutcome.DROPPED, reason="call_inactive")
        except StopAsyncIteration:
            return await self._degrade(generation, "stt_network_failure")
        except asyncio.CancelledError:
            if not self._is_current(generation):
                return SttResult(SttOutcome.DROPPED, reason="call_cancelled")
            raise
        except Exception:
            return await self._degrade(generation, "stt_network_failure")
        finally:
            self._reader_task = None

    async def finish_utterance(self) -> SttResult:
        """Flush and await one final transcript within the total 8-second budget."""
        async with self._utterance_lock:
            generation = self._generation
            if not self._is_current(generation):
                self.cancel()
                return SttResult(SttOutcome.DROPPED, reason="call_inactive")

            try:
                started_at = time.perf_counter()
                async with asyncio.timeout(self._timeout_seconds):
                    await self._stream.flush()
                    task = asyncio.create_task(self._receive_final(generation))
                    self._pending_result = task
                    transcript = await task
            except TimeoutError:
                self._pending_result = None
                if not self._is_current(generation):
                    self.cancel()
                    return SttResult(SttOutcome.DROPPED, reason="call_inactive")
                self._consecutive_timeouts += 1
                if self._consecutive_timeouts >= 2:
                    return await self._degrade(generation, "stt_timeout_consecutive")
                await self._callbacks.on_recovery_prompt(self.call_id, STT_RECOVERY_LINE)
                return SttResult(SttOutcome.RECOVERY, reason="stt_timeout_first")
            except asyncio.CancelledError:
                self._pending_result = None
                if not self._is_current(generation):
                    return SttResult(SttOutcome.DROPPED, reason="call_cancelled")
                raise
            except Exception:
                self._pending_result = None
                return await self._degrade(generation, "stt_network_failure")
            finally:
                self._pending_result = None

            if not self._is_current(generation):
                self.cancel()
                return SttResult(SttOutcome.DROPPED, reason="stale_result")

            self._consecutive_timeouts = 0
            self._final_wait_started_at = started_at
            await self._record_stt_timing()
            await self._callbacks.on_final_transcript(self.call_id, transcript)
            return SttResult(SttOutcome.FINAL, transcript=transcript)


class SttSessionRegistry:
    """Process-local cancellation index used by call end and takeover."""

    def __init__(self) -> None:
        self._sessions: dict[str, StreamingSttSession] = {}

    def register(self, session: StreamingSttSession) -> None:
        """Install one session per call, cancelling any replaced transport."""
        prior = self._sessions.get(session.call_id)
        if prior is not None and prior is not session:
            prior.cancel()
        self._sessions[session.call_id] = session

    def discard(self, session: StreamingSttSession) -> None:
        """Remove only the exact session that currently owns the call ID."""
        if self._sessions.get(session.call_id) is session:
            del self._sessions[session.call_id]

    def cancel_call(self, call_id: str) -> bool:
        """Cancel and remove a call synchronously; return whether it existed."""
        session = self._sessions.pop(call_id, None)
        if session is None:
            return False
        session.cancel()
        return True

    def cancel_all(self) -> None:
        """Cancel every open stream during process shutdown."""
        sessions = tuple(self._sessions.values())
        self._sessions.clear()
        for session in sessions:
            session.cancel()


def _session_registry(websocket: WebSocket) -> SttSessionRegistry:
    registry = getattr(websocket.app.state, "stt_sessions", None)
    if registry is None:
        registry = SttSessionRegistry()
        websocket.app.state.stt_sessions = registry
    if not isinstance(registry, SttSessionRegistry):
        raise TypeError("app.state.stt_sessions must be a SttSessionRegistry")
    return registry


async def _receive_browser_audio(
    websocket: WebSocket,
    session: StreamingSttSession,
) -> None:
    while session.active:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return

        chunk = message.get("bytes")
        if chunk is not None:
            try:
                result = await session.send_pcm(chunk)
            except ValueError as error:
                await websocket.send_json(
                    VoiceTransportErrorFrame(
                        call_id=session.call_id,
                        detail=str(error),
                    ).model_dump(mode="json")
                )
                continue
            if result.outcome in {SttOutcome.DEGRADED, SttOutcome.DROPPED}:
                return
            continue

        text = message.get("text")
        if text is None:
            continue
        try:
            control = json.loads(text)
        except json.JSONDecodeError:
            await websocket.send_json(
                VoiceTransportErrorFrame(
                    call_id=session.call_id,
                    detail="Invalid control message",
                ).model_dump(mode="json")
            )
            continue
        if control != {"type": "flush"}:
            await websocket.send_json(
                VoiceTransportErrorFrame(
                    call_id=session.call_id,
                    detail="Unsupported control message",
                ).model_dump(mode="json")
            )
            continue

        result = await session.flush_utterance()
        if result.outcome in {SttOutcome.DEGRADED, SttOutcome.DROPPED}:
            return


async def _relay_call_stream(
    websocket: WebSocket,
    session: StreamingSttSession,
    binding: SttCallBinding,
) -> None:
    browser_task = asyncio.create_task(_receive_browser_audio(websocket, session))
    result_task = asyncio.create_task(session.run_finalized_results())
    tasks = {browser_task, result_task}
    next_client_event = getattr(binding, "next_client_event", None)
    if next_client_event is not None:

        async def send_controller_events() -> None:
            last_media_seq = 0
            while session.active:
                raw_frame = await next_client_event()
                frame = VOICE_SERVER_FRAME_ADAPTER.validate_python(raw_frame)
                if frame.call_id != session.call_id:
                    raise ValueError("voice frame call ID does not match the active stream")
                is_final_media = isinstance(frame, AgentAudioFrame) and frame.final_media
                if not session.active or (not binding.is_call_active() and not is_final_media):
                    return
                if isinstance(frame, AgentAudioFrame):
                    if frame.media_seq <= last_media_seq:
                        continue
                    last_media_seq = frame.media_seq
                await websocket.send_json(frame.model_dump(mode="json"))
                if is_final_media:
                    return

        tasks.add(asyncio.create_task(send_controller_events()))
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        if not task.cancelled():
            task.result()


@router.websocket(STT_WEBSOCKET_PATH)
async def stt_websocket(websocket: WebSocket, call_id: str) -> None:
    """Stream browser PCM to Saaras and route only final text to the controller."""
    await websocket.accept()
    api_key = getattr(websocket.app.state, "sarvam_api_key", None)
    binding_factory: CallBindingFactory | None = getattr(
        websocket.app.state,
        "stt_call_binding_factory",
        None,
    )
    if not api_key or binding_factory is None:
        await websocket.send_json(
            VoiceTransportErrorFrame(
                call_id=call_id,
                detail="Speech controller is unavailable",
            ).model_dump(mode="json")
        )
        await websocket.close(code=1011)
        return

    binding = binding_factory(call_id)
    if not binding.is_call_active():
        await websocket.send_json(
            VoiceTransportErrorFrame(
                call_id=call_id,
                detail="Call is not active",
            ).model_dump(mode="json")
        )
        await websocket.close(code=1008)
        return

    stream_factory: StreamFactory = getattr(
        websocket.app.state,
        "sarvam_stream_factory",
        open_sarvam_stream,
    )
    registry = _session_registry(websocket)
    session: StreamingSttSession | None = None
    try:
        async with stream_factory(api_key) as stream:
            session = StreamingSttSession(
                call_id=call_id,
                stream=stream,
                callbacks=binding,
                is_call_active=binding.is_call_active,
            )
            registry.register(session)
            await websocket.send_json(
                VoiceReadyFrame(
                    call_id=call_id,
                    sample_rate=SAMPLE_RATE,
                ).model_dump(mode="json")
            )
            on_connected = getattr(binding, "on_connected", None)
            if on_connected is not None:
                await on_connected()
            await _relay_call_stream(websocket, session, binding)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
    except Exception:
        if binding.is_call_active() and (session is None or session.active):
            await binding.on_degraded(call_id, "stt_network_failure")
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            return
    finally:
        if session is not None:
            session.cancel()
            registry.discard(session)
