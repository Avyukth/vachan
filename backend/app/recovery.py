"""Fail-closed recovery for durable calls orphaned by a process restart."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import EvidenceLedger
from app.states import CallState, IdentityState, PromiseState

ORPHANED_RESTART_REASON = "orphaned by process restart"


@dataclass(frozen=True, slots=True)
class OrphanRecovery:
    """One persisted technical ending produced without a live call runtime."""

    call_id: str
    disposition_seq: int
    ts: datetime
    disposition: Disposition = Disposition.ENDED_TECHNICAL


def _fallback_snapshot() -> StateSnapshot:
    return StateSnapshot(
        call=CallState.ACTIVE,
        identity=IdentityState.UNVERIFIED,
        promise=PromiseState.NONE,
    )


def _last_snapshot(ledger: EvidenceLedger, call_id: str) -> StateSnapshot:
    row = ledger.connection.execute(
        """
        SELECT state_after
        FROM events
        WHERE call_id = ?
        ORDER BY seq DESC
        LIMIT 1
        """,
        (call_id,),
    ).fetchone()
    if row is None:
        return _fallback_snapshot()
    try:
        payload = json.loads(str(row["state_after"]))
        return StateSnapshot(
            call=CallState(str(payload["call"])),
            identity=IdentityState(str(payload["identity"])),
            promise=PromiseState(str(payload["promise"])),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _fallback_snapshot()


def orphan_recovery_for_call(
    ledger: EvidenceLedger,
    call_id: str,
) -> OrphanRecovery | None:
    """Return an already-persisted restart ending for idempotent operator recovery."""

    row = ledger.connection.execute(
        """
        SELECT calls.ended, calls.disposition, events.seq
        FROM calls
        JOIN events ON events.call_id = calls.id
        WHERE calls.id = ?
          AND calls.disposition = ?
          AND events.type = ?
          AND events.redacted_reason = ?
        ORDER BY events.seq DESC
        LIMIT 1
        """,
        (
            call_id,
            Disposition.ENDED_TECHNICAL.value,
            LedgerEventType.DISPOSITION_SET.value,
            ORPHANED_RESTART_REASON,
        ),
    ).fetchone()
    if row is None:
        return None
    return OrphanRecovery(
        call_id=call_id,
        disposition_seq=int(row["seq"]),
        ts=datetime.fromisoformat(str(row["ended"])),
    )


def reconcile_orphaned_calls(
    ledger: EvidenceLedger,
    *,
    call_ids: Iterable[str] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[OrphanRecovery, ...]:
    """Atomically end selected durable active calls as technical failures."""

    selected = None if call_ids is None else {call_id for call_id in call_ids}
    active_rows = ledger.connection.execute(
        """
        SELECT id
        FROM calls
        WHERE ended IS NULL AND disposition IS NULL
        ORDER BY started, id
        """
    ).fetchall()
    recoveries: list[OrphanRecovery] = []
    for row in active_rows:
        call_id = str(row["id"])
        if selected is not None and call_id not in selected:
            continue
        before = _last_snapshot(ledger, call_id)
        after = StateSnapshot(
            call=CallState.ENDED,
            identity=IdentityState.UNVERIFIED,
            promise=(
                PromiseState.ABANDONED
                if before.promise
                in {
                    PromiseState.CANDIDATE,
                    PromiseState.READ_BACK,
                    PromiseState.CORRECTED,
                    PromiseState.CONFIRMED,
                }
                else before.promise
            ),
        )
        timestamp = clock()
        seq = ledger.end_orphaned_technical_call(
            call_id=call_id,
            ts=timestamp,
            state_before=before,
            state_after=after,
            reason=ORPHANED_RESTART_REASON,
        )
        recoveries.append(
            OrphanRecovery(
                call_id=call_id,
                disposition_seq=seq,
                ts=timestamp,
            )
        )
    return tuple(recoveries)
