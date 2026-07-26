"""Time-boxed browser PCM16 to Saaras streaming WebSocket relay."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any, Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sarvamai import AsyncSarvamAI

SAMPLE_RATE = 16_000
MAX_PCM_CHUNK_BYTES = 64 * 1024
SPIKE_PATH = "/ws/spike/stt"
AUDIO_SPIKE_ENV = "VACHAN_ENABLE_AUDIO_SPIKE"

router = APIRouter(tags=["audio-spike"])


class SarvamStreamingSocket(Protocol):
    """Subset of the official SDK socket used by the relay."""

    async def transcribe(
        self,
        audio: str,
        encoding: str = "audio/wav",
        sample_rate: int = SAMPLE_RATE,
    ) -> None: ...

    async def flush(self) -> None: ...

    def __aiter__(self) -> AsyncIterator[Any]: ...


StreamFactory = Callable[[str], Any]


def audio_spike_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether the development-only relay was explicitly enabled."""
    source = os.environ if environment is None else environment
    return source.get(AUDIO_SPIKE_ENV) == "1"


@asynccontextmanager
async def open_sarvam_stream(api_key: str) -> AsyncIterator[SarvamStreamingSocket]:
    """Open the tested Saaras v3 raw-PCM streaming configuration."""
    client = AsyncSarvamAI(api_subscription_key=api_key)
    async with client.speech_to_text_streaming.connect(
        language_code="hi-IN",
        model="saaras:v3",
        mode="transcribe",
        sample_rate=str(SAMPLE_RATE),
        input_audio_codec="pcm_s16le",
        high_vad_sensitivity=True,
        vad_signals=True,
        flush_signal=True,
    ) as stream:
        yield stream


def encode_pcm_chunk(chunk: bytes) -> str:
    """Validate one mono PCM16 chunk and return its base64 wire value."""
    if not chunk:
        raise ValueError("PCM chunk must not be empty")
    if len(chunk) > MAX_PCM_CHUNK_BYTES:
        raise ValueError("PCM chunk exceeds the relay limit")
    if len(chunk) % 2:
        raise ValueError("PCM16 chunk must contain complete signed 16-bit samples")
    return base64.b64encode(chunk).decode("ascii")


def response_payload(message: Any) -> dict[str, Any]:
    """Serialize an official SDK response without leaking credentials."""
    if hasattr(message, "model_dump"):
        payload = message.model_dump(mode="json")
    elif hasattr(message, "dict"):
        payload = message.dict()
    else:
        raise TypeError("Unsupported Saaras response type")
    if not isinstance(payload, dict):
        raise TypeError("Saaras response must serialize to an object")
    return payload


async def _browser_to_sarvam(
    browser: WebSocket,
    sarvam: SarvamStreamingSocket,
) -> None:
    while True:
        message = await browser.receive()
        if message["type"] == "websocket.disconnect":
            return

        chunk = message.get("bytes")
        if chunk is not None:
            try:
                encoded = encode_pcm_chunk(chunk)
            except ValueError as error:
                await browser.send_json({"type": "error", "detail": str(error)})
                continue
            await sarvam.transcribe(
                audio=encoded,
                encoding="audio/wav",
                sample_rate=SAMPLE_RATE,
            )
            continue

        text = message.get("text")
        if text is None:
            continue
        try:
            control = json.loads(text)
        except json.JSONDecodeError:
            await browser.send_json({"type": "error", "detail": "Invalid control message"})
            continue
        if control == {"type": "flush"}:
            await sarvam.flush()
        else:
            await browser.send_json({"type": "error", "detail": "Unsupported control message"})


async def _sarvam_to_browser(
    sarvam: SarvamStreamingSocket,
    browser: WebSocket,
) -> None:
    async for message in sarvam:
        await browser.send_json(
            {
                "type": "sarvam_stream",
                "payload": response_payload(message),
            }
        )


async def relay_audio_stream(
    browser: WebSocket,
    sarvam: SarvamStreamingSocket,
) -> None:
    """Relay until either side disconnects, then cancel the stale peer task."""
    browser_task = asyncio.create_task(_browser_to_sarvam(browser, sarvam))
    sarvam_task = asyncio.create_task(_sarvam_to_browser(sarvam, browser))
    done, pending = await asyncio.wait(
        {browser_task, sarvam_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        if not task.cancelled():
            task.result()


@router.websocket(SPIKE_PATH)
async def audio_spike_websocket(websocket: WebSocket) -> None:
    """Accept browser PCM16 only when the development relay is explicitly enabled."""
    await websocket.accept()
    if not audio_spike_enabled():
        await websocket.close(code=1008, reason="Development audio spike is disabled")
        return

    api_key = getattr(websocket.app.state, "sarvam_api_key", None)
    if not api_key:
        await websocket.send_json(
            {"type": "error", "detail": "Backend speech dependency is unavailable"}
        )
        await websocket.close(code=1011)
        return

    stream_factory: StreamFactory = getattr(
        websocket.app.state,
        "sarvam_stream_factory",
        open_sarvam_stream,
    )
    try:
        async with stream_factory(api_key) as stream:
            await websocket.send_json(
                {
                    "type": "ready",
                    "sample_rate": SAMPLE_RATE,
                    "encoding": "pcm_s16le",
                }
            )
            await relay_audio_stream(websocket, stream)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
