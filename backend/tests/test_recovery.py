"""Restart recovery tests for durable calls without process-local authority."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import EvidenceLedger, migrate_schema
from app.main import _end_normal_call, _reconcile_registry_orphans
from app.preflight import AUDIO_OUTPUT_HEADER, MICROPHONE_HEADER
from app.preflight import router as preflight_router
from app.promise import PromiseEngine, PromiseEvent, SQLitePromiseRepository
from app.recovery import reconcile_orphaned_calls
from app.reset import RESET_CONFIRMATION
from app.reset import router as reset_router
from app.seeds import RAKESH_CASE, reset_and_reseed_demo_cases
from app.states import CallState, IdentityState, PromiseState
from app.takeover import TakeoverRegistry
from app.takeover import router as takeover_router

NOW = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)


def _start_durable_call(ledger: EvidenceLedger, call_id: str = "call-orphan") -> None:
    ledger.connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, 'streaming_pcm16_ws')
        """,
        (call_id, RAKESH_CASE.case_id, NOW.isoformat()),
    )


def _seed_read_back_candidate(
    ledger: EvidenceLedger,
    call_id: str = "call-orphan",
) -> None:
    snapshot = StateSnapshot(
        call=CallState.ACTIVE,
        identity=IdentityState.CONFIRMED,
        promise=PromiseState.NONE,
    )

    def apply_event(event: PromiseEvent, mutation: Callable[[], object]) -> object:
        nonlocal snapshot
        before = StateSnapshot(
            call=snapshot.call,
            identity=snapshot.identity,
            promise=event.state_before,
        )
        after = StateSnapshot(
            call=snapshot.call,
            identity=snapshot.identity,
            promise=event.state_after,
        )
        result, _seq = ledger.mutate_with_event(
            call_id=call_id,
            ts=NOW,
            event_type=event.event_type,
            state_before=before,
            state_after=after,
            redacted_reason=event.redacted_reason,
            mutation=mutation,
        )
        snapshot = after
        return result

    engine = PromiseEngine(
        call_id=call_id,
        repository=SQLitePromiseRepository(ledger),
        demo_time_anchor=NOW,
        clock=lambda: NOW,
        record_event=lambda _event: None,
        atomic_event_applier=apply_event,
    )
    asyncio.run(
        engine.create_candidate(
            caller_phrase="pandrah sau, Friday",
            amount="pandrah sau",
            date_phrase="Friday",
        )
    )
    asyncio.run(engine.read_back())


def _restart_app(ledger: EvidenceLedger) -> FastAPI:
    application = FastAPI()
    application.state.evidence_ledger = ledger
    application.state.sarvam_api_key = "backend-only-test-key"
    application.state.voice_calls = None
    application.state.takeover_sessions = TakeoverRegistry()
    application.state.orphan_call_reconciler = lambda call_id=None: _reconcile_registry_orphans(
        application, call_id
    )
    application.state.normal_call_ender = lambda call_id, reason: _end_normal_call(
        application,
        call_id,
        reason,
    )
    application.include_router(preflight_router)
    application.include_router(reset_router)
    application.include_router(takeover_router)
    return application


def _open_ledger(path: Path) -> EvidenceLedger:
    connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    return EvidenceLedger(connection)


def _open_seeded(path: Path) -> EvidenceLedger:
    ledger = _open_ledger(path)
    reset_and_reseed_demo_cases(ledger)
    return ledger


def test_restart_reconciles_active_row_and_unblocks_preflight_and_reset(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "restart.db"
    old_process = _open_seeded(database_path)
    _start_durable_call(old_process)
    _seed_read_back_candidate(old_process)
    old_process.close()

    new_process = _open_ledger(database_path)
    application = _restart_app(new_process)
    recovered = _reconcile_registry_orphans(application)

    assert len(recovered) == 1
    assert recovered[0].disposition is Disposition.ENDED_TECHNICAL
    assert _reconcile_registry_orphans(application) == ()
    call = new_process.connection.execute(
        "SELECT ended, disposition, operator_intervened FROM calls WHERE id = ?",
        ("call-orphan",),
    ).fetchone()
    assert call["ended"] is not None
    assert call["disposition"] == Disposition.ENDED_TECHNICAL.value
    assert call["operator_intervened"] == 0
    events = new_process.connection.execute(
        """
        SELECT seq, type, state_before, state_after, redacted_reason
        FROM events
        WHERE call_id = ?
        ORDER BY seq
        """,
        ("call-orphan",),
    ).fetchall()
    assert [event["type"] for event in events][-3:] == [
        "PROMISE_ABANDONED",
        LedgerEventType.STATE_TRANSITION.value,
        LedgerEventType.DISPOSITION_SET.value,
    ]
    disposition = events[-1]
    assert disposition["seq"] == 5
    assert disposition["redacted_reason"] == "orphaned by process restart"
    assert json.loads(disposition["state_before"]) == {
        "call": "ACTIVE",
        "identity": "CONFIRMED",
        "promise": "ABANDONED",
    }
    assert json.loads(disposition["state_after"]) == {
        "call": "ENDED",
        "identity": "UNVERIFIED",
        "promise": "ABANDONED",
    }
    repository = SQLitePromiseRepository(new_process)
    restored_state, restored_candidate = repository.load_state_now("call-orphan")
    assert restored_state is PromiseState.ABANDONED
    assert restored_candidate is not None
    assert restored_candidate.revision == 1
    assert (
        new_process.connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            ("call-orphan",),
        ).fetchone()[0]
        == 1
    )
    assert (
        new_process.connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            ("call-orphan",),
        ).fetchone()[0]
        == 0
    )
    assert (
        new_process.connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = ?",
            ("call-orphan",),
        ).fetchone()[0]
        == 5
    )

    with TestClient(application) as client:
        preflight = client.post(
            "/api/preflight",
            json={"api_version": "v0", "case_id": RAKESH_CASE.case_id},
            headers={
                MICROPHONE_HEADER: "granted",
                AUDIO_OUTPUT_HEADER: "confirmed",
            },
        )
        reset = client.post(
            "/api/reset",
            json={"api_version": "v0", "confirmation": RESET_CONFIRMATION},
        )

    assert preflight.status_code == 200
    assert preflight.json()["result"] == "READY"
    assert reset.status_code == 200
    new_process.close()


def test_operator_end_reconciles_registryless_call_idempotently(tmp_path: Path) -> None:
    ledger = _open_seeded(tmp_path / "operator-end.db")
    _start_durable_call(ledger)
    application = _restart_app(ledger)

    with TestClient(application) as client:
        first = client.post(
            "/api/call/end",
            json={
                "api_version": "v0",
                "call_id": "call-orphan",
                "reason": "Recover restart orphan",
            },
        )
        second = client.post(
            "/api/call/end",
            json={
                "api_version": "v0",
                "call_id": "call-orphan",
                "reason": "Retry recovery",
            },
        )

    assert first.status_code == second.status_code == 200
    assert first.json()["payload"]["disposition"] == Disposition.ENDED_TECHNICAL.value
    assert first.json()["payload"]["reason"] == "orphaned by process restart"
    assert second.json()["seq"] == first.json()["seq"]
    assert (
        ledger.connection.execute(
            """
            SELECT COUNT(*)
            FROM events
            WHERE call_id = ? AND type = ?
            """,
            ("call-orphan", LedgerEventType.DISPOSITION_SET.value),
        ).fetchone()[0]
        == 1
    )
    ledger.close()


def test_orphan_recovery_rolls_back_abandonment_when_disposition_evidence_fails(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "atomic-recovery.db"
    ledger = _open_seeded(database_path)
    _start_durable_call(ledger)
    _seed_read_back_candidate(ledger)
    events_before = ledger.connection.execute(
        "SELECT seq, type FROM events WHERE call_id = ? ORDER BY seq",
        ("call-orphan",),
    ).fetchall()
    injector = sqlite3.connect(database_path, isolation_level=None)
    injector.execute(
        """
        CREATE TRIGGER reject_orphan_disposition
        BEFORE INSERT ON events
        WHEN NEW.type = 'DISPOSITION_SET'
        BEGIN
            SELECT RAISE(ABORT, 'injected disposition evidence failure');
        END
        """
    )
    injector.close()

    with pytest.raises(sqlite3.IntegrityError, match="injected disposition evidence failure"):
        reconcile_orphaned_calls(ledger, clock=lambda: NOW)

    call = ledger.connection.execute(
        "SELECT ended, disposition FROM calls WHERE id = ?",
        ("call-orphan",),
    ).fetchone()
    assert call["ended"] is None
    assert call["disposition"] is None
    events_after = ledger.connection.execute(
        "SELECT seq, type FROM events WHERE call_id = ? ORDER BY seq",
        ("call-orphan",),
    ).fetchall()
    assert [tuple(row) for row in events_after] == [tuple(row) for row in events_before]
    restored_state, restored_candidate = SQLitePromiseRepository(ledger).load_state_now(
        "call-orphan"
    )
    assert restored_state is PromiseState.READ_BACK
    assert restored_candidate is not None
    ledger.close()


def test_takeover_returns_actionable_conflict_after_orphan_recovery(
    tmp_path: Path,
) -> None:
    ledger = _open_seeded(tmp_path / "takeover.db")
    _start_durable_call(ledger)
    application = _restart_app(ledger)

    with TestClient(application) as client:
        response = client.post(
            "/api/takeover",
            json={"api_version": "v0", "call_id": "call-orphan"},
        )

    assert response.status_code == 409
    assert response.json()["detail"].endswith("ENDED_TECHNICAL. Rerun preflight.")
    assert (
        ledger.connection.execute(
            "SELECT disposition FROM calls WHERE id = ?",
            ("call-orphan",),
        ).fetchone()[0]
        == Disposition.ENDED_TECHNICAL.value
    )
    ledger.close()


def test_reset_reconciles_orphan_but_still_refuses_live_registry_call(
    tmp_path: Path,
) -> None:
    orphan_ledger = _open_seeded(tmp_path / "orphan-reset.db")
    _start_durable_call(orphan_ledger)
    orphan_app = _restart_app(orphan_ledger)
    with TestClient(orphan_app) as client:
        recovered = client.post(
            "/api/reset",
            json={"api_version": "v0", "confirmation": RESET_CONFIRMATION},
        )
    assert recovered.status_code == 200
    orphan_ledger.close()

    live_ledger = _open_seeded(tmp_path / "live-reset.db")
    _start_durable_call(live_ledger)
    live_app = _restart_app(live_ledger)

    class LiveTakeover:
        call_id = "call-orphan"

    live_app.state.takeover_sessions.register(LiveTakeover())  # type: ignore[arg-type]
    with TestClient(live_app) as client:
        refused = client.post(
            "/api/reset",
            json={"api_version": "v0", "confirmation": RESET_CONFIRMATION},
        )
    assert refused.status_code == 403
    assert (
        live_ledger.connection.execute(
            "SELECT disposition FROM calls WHERE id = ?",
            ("call-orphan",),
        ).fetchone()[0]
        is None
    )
    live_ledger.close()
