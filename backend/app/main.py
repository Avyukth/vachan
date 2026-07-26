"""FastAPI entry point for the Vachan backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.audio_spike import router as audio_spike_router
from app.preflight import router as preflight_router
from app.replay import router as replay_router
from app.reset import router as reset_router
from app.sarvam_client import load_sarvam_api_key
from app.stt import SttSessionRegistry
from app.stt import router as stt_router
from app.takeover import TakeoverRegistry
from app.takeover import router as takeover_router
from app.tts import router as tts_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load the backend-only Sarvam credential before accepting traffic."""
    application.state.sarvam_api_key = load_sarvam_api_key()
    application.state.stt_sessions = SttSessionRegistry()
    application.state.takeover_sessions = TakeoverRegistry()
    try:
        yield
    finally:
        application.state.takeover_sessions = None
        application.state.stt_sessions.cancel_all()
        application.state.stt_sessions = None
        ledger = getattr(application.state, "evidence_ledger", None)
        if ledger is not None:
            ledger.close()
            application.state.evidence_ledger = None
        application.state.sarvam_api_key = None


app = FastAPI(
    title="Vachan API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(audio_spike_router)
app.include_router(preflight_router)
app.include_router(replay_router)
app.include_router(reset_router)
app.include_router(stt_router)
app.include_router(takeover_router)
app.include_router(tts_router)


@app.get("/healthz", tags=["system"])
async def healthz() -> dict[str, str]:
    """Return process liveness after startup dependencies have passed."""
    return {"status": "ok"}
