"""Pure preflight policy engine for deciding whether a call may start."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.db import EvidenceLedger
from app.protocol import (
    CasesResponse,
    CaseSummary,
    PreflightCheck,
    PreflightRequest,
    PreflightResponse,
    PreflightResult,
    StartCallRequest,
    StartCallResponse,
    TransportMode,
)
from app.seeds import reset_and_reseed_demo_cases

TECHNICAL_CHECK_NAMES = frozenset({"microphone", "audio_output", "backend", "sarvam_configuration"})
POLICY_CHECK_NAMES = frozenset({"eligibility", "contact_cap", "active_session"})
MICROPHONE_HEADER = "X-Vachan-Microphone"
AUDIO_OUTPUT_HEADER = "X-Vachan-Audio-Output"

router = APIRouter(tags=["calls"])


@dataclass(frozen=True, slots=True)
class PreflightInputs:
    """All facts needed for preflight, gathered without creating a call row."""

    microphone_permission: bool
    audio_output_confirmed: bool
    backend_healthy: bool
    sarvam_configured: bool
    case_eligible: bool
    contact_cap_remaining: int
    active_session_exists: bool

    def __post_init__(self) -> None:
        if self.contact_cap_remaining < 0:
            raise ValueError("contact_cap_remaining must not be negative")


def _check(name: str, passed: bool, success: str, failure: str) -> PreflightCheck:
    return PreflightCheck(name=name, **{"pass": passed}, detail=success if passed else failure)


def evaluate_preflight(inputs: PreflightInputs) -> PreflightResponse:
    """Return the ordered, fail-closed preflight decision without any mutation."""

    checks = (
        _check(
            "microphone",
            inputs.microphone_permission,
            "Microphone permission is granted.",
            "Grant microphone permission in browser settings, then rerun preflight.",
        ),
        _check(
            "audio_output",
            inputs.audio_output_confirmed,
            "Headphone output was confirmed.",
            "Connect headphones, play the test chime, and confirm it is audible.",
        ),
        _check(
            "backend",
            inputs.backend_healthy,
            "Backend health check passed.",
            "Backend is unavailable; restart it and rerun preflight.",
        ),
        _check(
            "sarvam_configuration",
            inputs.sarvam_configured,
            "Sarvam configuration is available backend-side.",
            "Sarvam configuration is unavailable; restore backend access and rerun preflight.",
        ),
        _check(
            "eligibility",
            inputs.case_eligible,
            "The mock case is eligible for contact.",
            "Policy blocks this case. Priya cannot override an eligibility block.",
        ),
        _check(
            "contact_cap",
            inputs.contact_cap_remaining > 0,
            "The mock case has contact capacity remaining.",
            "Contact cap is exhausted. Priya cannot override this policy block.",
        ),
        _check(
            "active_session",
            not inputs.active_session_exists,
            "No active session exists for this mock case.",
            "An active session already exists; end it before starting another call.",
        ),
    )

    failed_names = {check.name for check in checks if not check.passed}
    if failed_names & TECHNICAL_CHECK_NAMES:
        result = PreflightResult.BLOCKED_TECHNICAL
    elif failed_names & POLICY_CHECK_NAMES:
        result = PreflightResult.BLOCKED_POLICY
    else:
        result = PreflightResult.READY
    return PreflightResponse(result=result, checks=checks)


def _ledger_for(request: Request) -> EvidenceLedger:
    ledger = getattr(request.app.state, "evidence_ledger", None)
    if ledger is None:
        ledger = EvidenceLedger.open()
        if ledger.connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0:
            reset_and_reseed_demo_cases(ledger)
        request.app.state.evidence_ledger = ledger
    return ledger


def _ready_case_ids(request: Request) -> set[str]:
    ready_case_ids = getattr(request.app.state, "preflight_ready_case_ids", None)
    if ready_case_ids is None:
        ready_case_ids = set()
        request.app.state.preflight_ready_case_ids = ready_case_ids
    return ready_case_ids


def _inputs_from_ledger(
    request: Request,
    *,
    case_id: str,
    microphone_permission: bool,
    audio_output_confirmed: bool,
) -> PreflightInputs:
    ledger = _ledger_for(request)
    case = ledger.connection.execute(
        """
        SELECT eligibility, contact_cap_remaining
        FROM cases
        WHERE id = ?
        """,
        (case_id,),
    ).fetchone()
    active_session = ledger.connection.execute(
        """
        SELECT 1
        FROM calls
        WHERE case_id = ? AND disposition IS NULL
        LIMIT 1
        """,
        (case_id,),
    ).fetchone()
    return PreflightInputs(
        microphone_permission=microphone_permission,
        audio_output_confirmed=audio_output_confirmed,
        backend_healthy=True,
        sarvam_configured=bool(getattr(request.app.state, "sarvam_api_key", None)),
        case_eligible=bool(case["eligibility"]) if case is not None else False,
        contact_cap_remaining=int(case["contact_cap_remaining"]) if case is not None else 0,
        active_session_exists=active_session is not None,
    )


@router.get("/api/cases", response_model=CasesResponse)
async def list_cases(request: Request) -> CasesResponse:
    """Return only privacy-safe fields for the seeded mock cases."""

    rows = _ledger_for(request).connection.execute(
        """
        SELECT id, name, eligibility, contact_cap_remaining
        FROM cases
        ORDER BY id
        """
    )
    return CasesResponse(
        cases=tuple(
            CaseSummary(
                case_id=row["id"],
                borrower_display_name=row["name"],
                eligible=bool(row["eligibility"]),
                contact_cap_remaining=int(row["contact_cap_remaining"]),
                mock_data=True,
            )
            for row in rows
        )
    )


@router.post("/api/preflight", response_model=PreflightResponse)
async def run_preflight(
    payload: PreflightRequest,
    request: Request,
    microphone: str = Header(default="denied", alias=MICROPHONE_HEADER),
    audio_output: str = Header(default="unconfirmed", alias=AUDIO_OUTPUT_HEADER),
) -> PreflightResponse:
    """Combine browser attestations with backend policy checks without starting a call."""

    inputs = _inputs_from_ledger(
        request,
        case_id=payload.case_id,
        microphone_permission=microphone.casefold() == "granted",
        audio_output_confirmed=audio_output.casefold() == "confirmed",
    )
    response = evaluate_preflight(inputs)
    ready_case_ids = _ready_case_ids(request)
    if response.result is PreflightResult.READY:
        ready_case_ids.add(payload.case_id)
    else:
        ready_case_ids.discard(payload.case_id)
    return response


@router.post("/api/call/start", response_model=StartCallResponse)
async def start_call(payload: StartCallRequest, request: Request) -> StartCallResponse:
    """Create one call only after READY, with the database enforcing race safety."""

    ready_case_ids = _ready_case_ids(request)
    if payload.case_id not in ready_case_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A current READY preflight is required before starting a call.",
        )

    current = _inputs_from_ledger(
        request,
        case_id=payload.case_id,
        microphone_permission=True,
        audio_output_confirmed=True,
    )
    if evaluate_preflight(current).result is not PreflightResult.READY:
        ready_case_ids.discard(payload.case_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Preflight is no longer READY; rerun it before starting.",
        )

    call_id = f"call-{uuid4()}"
    try:
        _ledger_for(request).connection.execute(
            """
            INSERT INTO calls (id, case_id, started, transport)
            VALUES (?, ?, ?, ?)
            """,
            (
                call_id,
                payload.case_id,
                datetime.now(UTC).isoformat(),
                TransportMode.STREAMING_PCM16_WS.value,
            ),
        )
    except sqlite3.IntegrityError as error:
        ready_case_ids.discard(payload.case_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active call already exists for this case.",
        ) from error

    ready_case_ids.discard(payload.case_id)
    return StartCallResponse(call_id=call_id)
