"""Append-only persistence for redacted verification-attempt evidence."""

from __future__ import annotations

from datetime import datetime

from app.contracts import StateSnapshot
from app.db import EvidenceLedger
from app.verification import (
    VerificationAttemptEvidence,
    VerificationSession,
    reconstruct_verification_session,
)

VERIFICATION_ATTEMPT_EVENT = "VERIFICATION_ATTEMPT"


class VerificationEvidenceRepository:
    """Persist and reconstruct only the approved verification evidence shape."""

    def __init__(self, ledger: EvidenceLedger) -> None:
        self._ledger = ledger

    async def append_attempt(
        self,
        *,
        call_id: str,
        ts: datetime,
        state: StateSnapshot,
        evidence: VerificationAttemptEvidence,
    ) -> int:
        """Append one complete attempt before runtime session state advances."""

        return await self._ledger.append_event(
            call_id=call_id,
            ts=ts,
            event_type=VERIFICATION_ATTEMPT_EVENT,
            state_before=state,
            state_after=state,
            redacted_reason=evidence.as_redacted_reason(),
        )

    def attempts_for_call(self, call_id: str) -> tuple[VerificationAttemptEvidence, ...]:
        """Load the ordered durable attempts for one call."""

        rows = self._ledger.connection.execute(
            """
            SELECT redacted_reason
            FROM events
            WHERE call_id = ? AND type = ?
            ORDER BY seq
            """,
            (call_id, VERIFICATION_ATTEMPT_EVENT),
        ).fetchall()
        return tuple(
            VerificationAttemptEvidence.from_redacted_reason(str(row["redacted_reason"]))
            for row in rows
        )

    def reconstruct_session(self, call_id: str) -> VerificationSession:
        """Rebuild the consumed attempt budget from append-only evidence."""

        return reconstruct_verification_session(self.attempts_for_call(call_id))
