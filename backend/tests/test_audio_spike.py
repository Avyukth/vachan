"""Tests for the isolated PCM16 streaming relay."""

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.audio_spike import (
    AUDIO_SPIKE_ENV,
    MAX_PCM_CHUNK_BYTES,
    SAMPLE_RATE,
    SPIKE_PATH,
    audio_spike_enabled,
    encode_pcm_chunk,
    router,
)


def test_pcm_chunk_encoding_is_lossless() -> None:
    chunk = b"\x00\x00\xff\x7f\x00\x80"
    assert base64.b64decode(encode_pcm_chunk(chunk)) == chunk


@pytest.mark.parametrize("chunk", [b"", b"\x00", b"\x00\x00" * 32_769])
def test_invalid_pcm_chunks_are_rejected(chunk: bytes) -> None:
    with pytest.raises(ValueError):
        encode_pcm_chunk(chunk)


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, False),
        ({AUDIO_SPIKE_ENV: ""}, False),
        ({AUDIO_SPIKE_ENV: "true"}, False),
        ({AUDIO_SPIKE_ENV: "1"}, True),
    ],
)
def test_audio_spike_requires_exact_development_opt_in(
    environment: dict[str, str],
    expected: bool,
) -> None:
    assert audio_spike_enabled(environment) is expected


class FakeResponse:
    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return {
            "type": "data",
            "data": {
                "transcript": "नमस्ते",
                "metrics": {"audio_duration": 0.1, "processing_latency": 0.04},
            },
        }


class FakeSarvamStream:
    def __init__(self) -> None:
        self.audio: list[bytes] = []
        self.flush_count = 0
        self.responses: asyncio.Queue[FakeResponse] = asyncio.Queue()

    async def transcribe(
        self,
        audio: str,
        encoding: str = "audio/wav",
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        assert encoding == "audio/wav"
        assert sample_rate == SAMPLE_RATE
        self.audio.append(base64.b64decode(audio))
        await self.responses.put(FakeResponse())

    async def flush(self) -> None:
        self.flush_count += 1

    async def __aiter__(self) -> AsyncIterator[FakeResponse]:
        while True:
            yield await self.responses.get()


def test_websocket_is_closed_by_default_without_opening_sarvam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(AUDIO_SPIKE_ENV, raising=False)
    stream_factory_called = False

    @asynccontextmanager
    async def forbidden_factory(api_key: str) -> AsyncIterator[FakeSarvamStream]:
        nonlocal stream_factory_called
        stream_factory_called = True
        yield FakeSarvamStream()

    app = FastAPI()
    app.state.sarvam_api_key = "test-key"
    app.state.sarvam_stream_factory = forbidden_factory
    app.include_router(router)

    with (
        TestClient(app).websocket_connect(SPIKE_PATH) as websocket,
        pytest.raises(WebSocketDisconnect) as disconnect,
    ):
        websocket.receive_json()

    assert disconnect.value.code == 1008
    assert stream_factory_called is False


def test_explicitly_enabled_websocket_relays_binary_pcm_and_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(AUDIO_SPIKE_ENV, "1")
    fake_stream = FakeSarvamStream()

    @asynccontextmanager
    async def fake_factory(api_key: str) -> AsyncIterator[FakeSarvamStream]:
        assert api_key == "test-key"
        yield fake_stream

    app = FastAPI()
    app.state.sarvam_api_key = "test-key"
    app.state.sarvam_stream_factory = fake_factory
    app.include_router(router)

    pcm = b"\x01\x00\xff\xff" * 100
    with TestClient(app).websocket_connect(SPIKE_PATH) as websocket:
        assert websocket.receive_json() == {
            "type": "ready",
            "sample_rate": SAMPLE_RATE,
            "encoding": "pcm_s16le",
        }
        websocket.send_bytes(pcm)
        assert websocket.receive_json() == {
            "type": "sarvam_stream",
            "payload": {
                "type": "data",
                "data": {
                    "transcript": "नमस्ते",
                    "metrics": {
                        "audio_duration": 0.1,
                        "processing_latency": 0.04,
                    },
                },
            },
        }
        websocket.send_text('{"type":"flush"}')

    assert fake_stream.audio == [pcm]
    assert len(pcm) < MAX_PCM_CHUNK_BYTES
    assert fake_stream.flush_count == 1
