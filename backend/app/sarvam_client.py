"""Backend-only Sarvam credential and API integration boundary."""

import asyncio
import base64
import binascii
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

KEYCHAIN_SERVICE = "sarvam-api"
KEYCHAIN_ACCOUNT = "vachan"
KEYCHAIN_TIMEOUT_SECONDS = 15
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_TTS_MODEL = "bulbul:v3"
SARVAM_TTS_SPEAKER = "priya"
SARVAM_TTS_LANGUAGE = "hi-IN"
SARVAM_TTS_SAMPLE_RATE = 24_000
SARVAM_TTS_TIMEOUT_SECONDS = 20.0
SARVAM_TTS_MAX_ATTEMPTS = 2
SARVAM_TTS_RETRYABLE_STATUSES = frozenset({429, 503})


class SarvamCredentialError(RuntimeError):
    """Raised when the backend cannot securely load its Sarvam credential."""


class SarvamTextToSpeechError(RuntimeError):
    """Base class for safe, typed Bulbul failures."""


class SarvamTextToSpeechCancelled(SarvamTextToSpeechError):
    """Raised when the owning call invalidates pending speech."""


class SarvamTextToSpeechTimeout(SarvamTextToSpeechError):
    """Raised after the bounded Bulbul request deadline expires."""


class SarvamTextToSpeechUnavailable(SarvamTextToSpeechError):
    """Raised when Bulbul is unavailable after a bounded retry."""


class SarvamTextToSpeechInvalidResponse(SarvamTextToSpeechError):
    """Raised when Bulbul returns a response that is not a valid WAV."""


@dataclass(frozen=True, slots=True)
class SynthesizedSpeech:
    """Decoded speech bytes safe to return to the browser."""

    audio: bytes
    request_id: str | None
    content_type: str = "audio/wav"


CancellationCheck = Callable[[], bool]
AsyncSleep = Callable[[float], Awaitable[None]]


class SarvamTextToSpeechClient:
    """Small async Bulbul boundary with cancellation and bounded retry.

    Callers must pass only text that has already cleared Vachan's output guard.
    This class deliberately never logs or includes that text in exceptions.
    """

    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_seconds: float = SARVAM_TTS_TIMEOUT_SECONDS,
        sleep: AsyncSleep = asyncio.sleep,
    ) -> None:
        if not api_key.strip():
            raise SarvamCredentialError("A non-empty backend Sarvam API key is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key
        self._http_client = http_client
        self._timeout = httpx.Timeout(timeout_seconds)
        self._sleep = sleep

    async def synthesize(
        self,
        approved_text: str,
        *,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> SynthesizedSpeech:
        """Convert guard-approved text to WAV, dropping stale callbacks."""
        if not approved_text.strip():
            raise ValueError("approved_text must not be empty")
        if is_cancelled():
            raise SarvamTextToSpeechCancelled("Speech was cancelled before synthesis.")

        payload: dict[str, Any] = {
            "text": approved_text,
            "target_language_code": SARVAM_TTS_LANGUAGE,
            "model": SARVAM_TTS_MODEL,
            "speaker": SARVAM_TTS_SPEAKER,
            "pace": 1.0,
            "speech_sample_rate": SARVAM_TTS_SAMPLE_RATE,
            "output_audio_codec": "wav",
            "temperature": 0.6,
            "enable_preprocessing": True,
        }
        headers = {
            "api-subscription-key": self._api_key,
            "content-type": "application/json",
        }

        response: httpx.Response | None = None
        for attempt in range(SARVAM_TTS_MAX_ATTEMPTS):
            if is_cancelled():
                raise SarvamTextToSpeechCancelled("Speech was cancelled before synthesis.")
            try:
                response = await self._post(headers=headers, payload=payload)
            except httpx.TimeoutException as error:
                if attempt + 1 == SARVAM_TTS_MAX_ATTEMPTS:
                    raise SarvamTextToSpeechTimeout(
                        "Bulbul synthesis exceeded the bounded deadline."
                    ) from error
                await self._retry_delay(attempt, is_cancelled)
                continue
            except httpx.TransportError as error:
                if attempt + 1 == SARVAM_TTS_MAX_ATTEMPTS:
                    raise SarvamTextToSpeechUnavailable(
                        "Bulbul synthesis is temporarily unavailable."
                    ) from error
                await self._retry_delay(attempt, is_cancelled)
                continue

            if response.status_code not in SARVAM_TTS_RETRYABLE_STATUSES:
                break
            if attempt + 1 == SARVAM_TTS_MAX_ATTEMPTS:
                raise SarvamTextToSpeechUnavailable("Bulbul synthesis is temporarily unavailable.")
            await self._retry_delay(attempt, is_cancelled)

        assert response is not None
        if is_cancelled():
            raise SarvamTextToSpeechCancelled("Speech was cancelled after synthesis.")
        if response.is_error:
            raise SarvamTextToSpeechUnavailable(
                f"Bulbul rejected the synthesis request (HTTP {response.status_code})."
            )

        return self._decode_response(response, is_cancelled=is_cancelled)

    async def _post(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        if self._http_client is not None:
            return await self._http_client.post(
                SARVAM_TTS_URL,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.post(SARVAM_TTS_URL, headers=headers, json=payload)

    async def _retry_delay(self, attempt: int, is_cancelled: CancellationCheck) -> None:
        await self._sleep(0.25 * (2**attempt))
        if is_cancelled():
            raise SarvamTextToSpeechCancelled("Speech was cancelled during retry.")

    @staticmethod
    def _decode_response(
        response: httpx.Response,
        *,
        is_cancelled: CancellationCheck,
    ) -> SynthesizedSpeech:
        try:
            body = response.json()
            encoded_audio = body["audios"][0]
            if not isinstance(encoded_audio, str) or not encoded_audio:
                raise ValueError("missing encoded audio")
            audio = base64.b64decode(encoded_audio, validate=True)
        except (ValueError, KeyError, IndexError, TypeError, binascii.Error) as error:
            raise SarvamTextToSpeechInvalidResponse(
                "Bulbul returned an invalid audio response."
            ) from error

        if is_cancelled():
            raise SarvamTextToSpeechCancelled("Speech was cancelled before playback.")
        if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise SarvamTextToSpeechInvalidResponse(
                "Bulbul returned audio that was not a WAV file."
            )

        request_id = body.get("request_id")
        return SynthesizedSpeech(
            audio=audio,
            request_id=request_id if isinstance(request_id, str) else None,
        )


def load_sarvam_api_key() -> str:
    """Load the Sarvam API key from macOS Keychain without exposing it."""
    command = (
        "security",
        "find-generic-password",
        "-s",
        KEYCHAIN_SERVICE,
        "-a",
        KEYCHAIN_ACCOUNT,
        "-w",
    )
    try:
        result = subprocess.run(  # noqa: S603
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise SarvamCredentialError(
            "macOS Keychain CLI is unavailable; Vachan cannot load the Sarvam API key."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise SarvamCredentialError(
            "Timed out while loading the Sarvam API key from macOS Keychain."
        ) from error
    except subprocess.CalledProcessError as error:
        raise SarvamCredentialError(
            "Sarvam API key is unavailable in macOS Keychain "
            f"(service={KEYCHAIN_SERVICE}, account={KEYCHAIN_ACCOUNT})."
        ) from error

    api_key = result.stdout.strip()
    if not api_key:
        raise SarvamCredentialError(
            "Sarvam API key entry exists but contains no value; refusing to start."
        )
    return api_key
