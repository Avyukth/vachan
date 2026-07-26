"""Tests for the Bulbul boundary and fixed audio-check route."""

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.sarvam_client import (
    SARVAM_TTS_MAX_ATTEMPTS,
    SarvamTextToSpeechCancelled,
    SarvamTextToSpeechClient,
    SarvamTextToSpeechInvalidResponse,
    SarvamTextToSpeechUnavailable,
    SynthesizedSpeech,
)
from app.tts import AUDIO_CHECK_LINE, router

WAV_BYTES = b"RIFF\x04\x00\x00\x00WAVE"


def tts_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "request_id": "safe-request-id",
            "audios": [base64.b64encode(WAV_BYTES).decode("ascii")],
        },
    )


def test_bulbul_request_uses_fixed_model_voice_and_backend_key() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return tts_response()

    async def scenario() -> SynthesizedSpeech:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = SarvamTextToSpeechClient("secret-key", http_client=http_client)
            return await client.synthesize("guard approved")

    speech = asyncio.run(scenario())

    assert speech.audio == WAV_BYTES
    assert captured["headers"]["api-subscription-key"] == "secret-key"
    assert captured["body"] == {
        "text": "guard approved",
        "target_language_code": "hi-IN",
        "model": "bulbul:v3",
        "speaker": "priya",
        "pace": 1.0,
        "speech_sample_rate": 24_000,
        "output_audio_codec": "wav",
        "temperature": 0.6,
        "enable_preprocessing": True,
    }


def test_retryable_response_is_bounded_and_never_leaks_text() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(503, text="upstream body must stay private")

    async def no_sleep(_: float) -> None:
        return None

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
            client = SarvamTextToSpeechClient(
                "secret-key",
                http_client=http_client,
                sleep=no_sleep,
            )
            await client.synthesize("private guard-approved account response")

    with pytest.raises(SarvamTextToSpeechUnavailable) as caught:
        asyncio.run(scenario())

    assert requests == SARVAM_TTS_MAX_ATTEMPTS
    assert "private guard-approved" not in str(caught.value)
    assert "upstream body" not in str(caught.value)


def test_stale_speech_is_dropped_after_response() -> None:
    cancellation_checks = 0

    def is_cancelled() -> bool:
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks >= 3

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: tts_response())
        ) as http_client:
            client = SarvamTextToSpeechClient("secret-key", http_client=http_client)
            await client.synthesize("approved", is_cancelled=is_cancelled)

    with pytest.raises(SarvamTextToSpeechCancelled):
        asyncio.run(scenario())


def test_invalid_or_non_wav_audio_fails_closed() -> None:
    response = httpx.Response(
        200,
        json={"audios": [base64.b64encode(b"not wav").decode("ascii")]},
    )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: response)
        ) as http_client:
            client = SarvamTextToSpeechClient("secret-key", http_client=http_client)
            await client.synthesize("approved")

    with pytest.raises(SarvamTextToSpeechInvalidResponse):
        asyncio.run(scenario())


class FakeSynthesizer:
    def __init__(self, result: SynthesizedSpeech | Exception) -> None:
        self.result = result
        self.received_text: str | None = None

    async def synthesize(self, approved_text: str) -> SynthesizedSpeech:
        self.received_text = approved_text
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_audio_check_route_has_no_text_input_and_returns_no_store_wav() -> None:
    application = FastAPI()
    application.include_router(router)
    synthesizer = FakeSynthesizer(SynthesizedSpeech(WAV_BYTES, "request-id"))
    application.state.tts_synthesizer = synthesizer

    response = TestClient(application).post(
        "/api/audio/check",
        json={"text": "browser supplied text must be ignored"},
    )

    assert response.status_code == 200
    assert response.content == WAV_BYTES
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert synthesizer.received_text == AUDIO_CHECK_LINE


def test_audio_check_route_maps_upstream_error_without_exposing_details() -> None:
    application = FastAPI()
    application.include_router(router)
    application.state.tts_synthesizer = FakeSynthesizer(
        SarvamTextToSpeechUnavailable("secret upstream body")
    )

    response = TestClient(application).post("/api/audio/check")

    assert response.status_code == 503
    assert response.json() == {"detail": "Audio output is temporarily unavailable."}
    assert "secret upstream body" not in response.text
