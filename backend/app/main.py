"""FastAPI entry point for the Vachan backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.audio_spike import router as audio_spike_router
from app.replay import router as replay_router
from app.sarvam_client import load_sarvam_api_key
from app.tts import router as tts_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load the backend-only Sarvam credential before accepting traffic."""
    application.state.sarvam_api_key = load_sarvam_api_key()
    try:
        yield
    finally:
        application.state.sarvam_api_key = None


app = FastAPI(
    title="Vachan API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(audio_spike_router)
app.include_router(replay_router)
app.include_router(tts_router)


@app.get("/healthz", tags=["system"])
async def healthz() -> dict[str, str]:
    """Return process liveness after startup dependencies have passed."""
    return {"status": "ok"}
