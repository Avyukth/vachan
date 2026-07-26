"""Bulbul speech routes that never expose arbitrary pre-guard text."""

from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.sarvam_client import (
    SarvamTextToSpeechCancelled,
    SarvamTextToSpeechClient,
    SarvamTextToSpeechError,
    SarvamTextToSpeechInvalidResponse,
    SarvamTextToSpeechTimeout,
    SynthesizedSpeech,
)

AUDIO_CHECK_LINE = "नमस्ते। यह वचन की आवाज़ जाँच है। कृपया कोई ओटीपी, पिन या पासवर्ड साझा न करें।"

router = APIRouter()


class SpeechSynthesizer(Protocol):
    """Internal contract shared by the production client and offline tests."""

    async def synthesize(self, approved_text: str) -> SynthesizedSpeech: ...


def _synthesizer(request: Request) -> SpeechSynthesizer:
    injected = getattr(request.app.state, "tts_synthesizer", None)
    if injected is not None:
        return injected

    api_key = getattr(request.app.state, "sarvam_api_key", None)
    if not isinstance(api_key, str) or not api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio output is unavailable because Sarvam is not configured.",
        )
    return SarvamTextToSpeechClient(api_key)


@router.post(
    "/api/audio/check",
    response_class=Response,
    responses={
        200: {"content": {"audio/wav": {}}, "description": "Fixed reviewed headphone-check line."},
        502: {"description": "Bulbul returned invalid audio."},
        503: {"description": "Bulbul or its backend credential is unavailable."},
        504: {"description": "Bulbul exceeded the bounded request deadline."},
    },
    tags=["audio"],
)
async def audio_check(request: Request) -> Response:
    """Synthesize one fixed safe line for headphone/autoplay preflight.

    The browser cannot supply text to this route. Dynamic agent responses must
    come through the controller after the pre-TTS output guard approves them.
    """
    try:
        speech = await _synthesizer(request).synthesize(AUDIO_CHECK_LINE)
    except SarvamTextToSpeechTimeout as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Audio output timed out. Check the network and retry preflight.",
        ) from error
    except SarvamTextToSpeechInvalidResponse as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Audio output returned an invalid response.",
        ) from error
    except SarvamTextToSpeechCancelled as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio output was cancelled before playback.",
        ) from error
    except SarvamTextToSpeechError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio output is temporarily unavailable.",
        ) from error

    return Response(
        content=speech.audio,
        media_type=speech.content_type,
        headers={
            "Cache-Control": "no-store",
            "X-Vachan-Audio-Source": "bulbul-v3-fixed-check",
        },
    )
