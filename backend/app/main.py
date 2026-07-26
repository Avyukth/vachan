"""FastAPI entry point for the Vachan backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.audio_spike import router as audio_spike_router
from app.db import EvidenceLedger
from app.preflight import router as preflight_router
from app.recovery import (
    OrphanRecovery,
    orphan_recovery_for_call,
    reconcile_orphaned_calls,
)
from app.replay import router as replay_router
from app.reset import router as reset_router
from app.sarvam_client import load_sarvam_api_key
from app.seeds import reset_and_reseed_demo_cases
from app.stt import SttSessionRegistry
from app.stt import router as stt_router
from app.takeover import TakeoverRegistry
from app.takeover import router as takeover_router
from app.tts import router as tts_router
from app.voice import ProductionVoiceRegistry


def _production_voice_binding(application: FastAPI, call_id: str) -> object:
    """Resolve the live binding only after preflight has opened the ledger."""

    ledger = getattr(application.state, "evidence_ledger", None)
    api_key = getattr(application.state, "sarvam_api_key", None)
    takeover_sessions = getattr(application.state, "takeover_sessions", None)
    stt_sessions = getattr(application.state, "stt_sessions", None)
    if ledger is None or not isinstance(api_key, str) or not api_key:
        raise LookupError("production voice runtime is unavailable")
    if not isinstance(takeover_sessions, TakeoverRegistry) or not isinstance(
        stt_sessions,
        SttSessionRegistry,
    ):
        raise LookupError("production call lifecycle is unavailable")

    registry = getattr(application.state, "voice_calls", None)
    if not isinstance(registry, ProductionVoiceRegistry):
        registry = ProductionVoiceRegistry(
            ledger=ledger,
            api_key=api_key,
            takeover_sessions=takeover_sessions,
            stt_sessions=stt_sessions,
        )
        application.state.voice_calls = registry
    return registry.binding_for(call_id)


def _discard_call_session(application: FastAPI, call_id: str) -> None:
    """Drop every process-local handle after a failed call-start transaction."""

    voice_calls = getattr(application.state, "voice_calls", None)
    if isinstance(voice_calls, ProductionVoiceRegistry):
        voice_calls.discard(call_id)
    stt_sessions = getattr(application.state, "stt_sessions", None)
    if isinstance(stt_sessions, SttSessionRegistry):
        stt_sessions.cancel_call(call_id)
    takeover_sessions = getattr(application.state, "takeover_sessions", None)
    if isinstance(takeover_sessions, TakeoverRegistry):
        takeover_sessions.discard(call_id)


async def _end_normal_call(application: FastAPI, call_id: str, reason: str) -> object:
    """End one active voice call, then synchronously invalidate its transports."""

    registry = getattr(application.state, "voice_calls", None)
    if isinstance(registry, ProductionVoiceRegistry):
        try:
            result = await registry.end_by_operator(call_id, reason)
        except LookupError:
            pass
        else:
            _discard_call_session(application, call_id)
            return result
    recovered = _reconcile_registry_orphans(application, call_id)
    if recovered:
        return recovered[0]
    raise LookupError("active voice call does not exist")


def _reconcile_registry_orphans(
    application: FastAPI,
    call_id: str | None = None,
) -> tuple[OrphanRecovery, ...]:
    """End durable active rows that have no process-local takeover authority."""

    ledger = getattr(application.state, "evidence_ledger", None)
    takeover_sessions = getattr(application.state, "takeover_sessions", None)
    if not isinstance(ledger, EvidenceLedger) or not isinstance(
        takeover_sessions,
        TakeoverRegistry,
    ):
        return ()
    active_ids = tuple(
        str(row["id"])
        for row in ledger.connection.execute(
            """
            SELECT id
            FROM calls
            WHERE ended IS NULL AND disposition IS NULL
            ORDER BY started, id
            """
        )
        if (call_id is None or str(row["id"]) == call_id)
        and takeover_sessions.get(str(row["id"])) is None
    )
    recovered = reconcile_orphaned_calls(ledger, call_ids=active_ids)
    if recovered or call_id is None:
        return recovered
    existing = orphan_recovery_for_call(ledger, call_id)
    return () if existing is None else (existing,)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Load the backend-only Sarvam credential before accepting traffic."""
    application.state.sarvam_api_key = load_sarvam_api_key()
    ledger = EvidenceLedger.open()
    if ledger.connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0:
        reset_and_reseed_demo_cases(ledger)
    application.state.evidence_ledger = ledger
    application.state.stt_sessions = SttSessionRegistry()
    application.state.takeover_sessions = TakeoverRegistry()
    application.state.voice_calls = None
    application.state.orphan_call_reconciler = lambda call_id=None: _reconcile_registry_orphans(
        application, call_id
    )
    _reconcile_registry_orphans(application)
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
        application.state.takeover_sessions = None
        application.state.stt_sessions.cancel_all()
        application.state.stt_sessions = None
        application.state.stt_call_binding_factory = None
        application.state.call_session_registrar = None
        application.state.call_session_discard = None
        application.state.normal_call_ender = None
        application.state.orphan_call_reconciler = None
        application.state.voice_calls = None
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
