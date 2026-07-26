"""Explicit, demo-scoped reset endpoint."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status

from app.db import ActiveCallExists
from app.preflight import _ledger_for, _ready_case_ids
from app.protocol import ProtocolModel, ResetResponse
from app.seeds import reset_and_reseed_demo_cases

RESET_CONFIRMATION = "RESET DEMO / MOCK DATA"

router = APIRouter(tags=["demo"])


class DemoResetRequest(ProtocolModel):
    """Exact operator confirmation; arbitrary truthy flags are not accepted."""

    confirmation: Literal["RESET DEMO / MOCK DATA"]


@router.post("/api/reset", response_model=ResetResponse)
async def reset_demo(payload: DemoResetRequest, request: Request) -> ResetResponse:
    """Run the one sanctioned demo-data wipe outside active calls only."""
    assert payload.confirmation == RESET_CONFIRMATION
    reconciler = getattr(request.app.state, "orphan_call_reconciler", None)
    if callable(reconciler):
        reconciler()
    try:
        seeded_ids = reset_and_reseed_demo_cases(_ledger_for(request))
    except ActiveCallExists as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo reset is unavailable during an active call. End the call safely first.",
        ) from error

    # A READY decision made against pre-reset rows cannot authorize a new call.
    _ready_case_ids(request).clear()
    return ResetResponse(seeded_case_count=len(seeded_ids))
