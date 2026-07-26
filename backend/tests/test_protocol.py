"""Contract tests for Vachan's versioned REST and WebSocket messages."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.protocol import (
    PROTOCOL_VERSION,
    CasesResponse,
    CaseSummary,
    EventType,
    EvidenceResponse,
    PreflightCheck,
    PreflightResponse,
    PreflightResult,
    ServerEvent,
)


def event(*, call_id: str = "call-1", seq: int = 1) -> ServerEvent:
    """Build a minimal ledger-backed server event."""
    return ServerEvent(
        type=EventType.STATE_CHANGE,
        call_id=call_id,
        seq=seq,
        ts=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
        payload={"before": "READY", "after": "ACTIVE"},
    )


def test_all_json_messages_are_strict_and_versioned_v0() -> None:
    """Messages reject undeclared fields and serialize the frozen version tag."""
    case = CaseSummary(
        case_id="case-rakesh",
        borrower_display_name="Rakesh Yadav",
        eligible=True,
        contact_cap_remaining=1,
    )

    assert case.model_dump(mode="json")["api_version"] == PROTOCOL_VERSION
    with pytest.raises(ValidationError):
        CaseSummary(
            case_id="case-rakesh",
            borrower_display_name="Rakesh Yadav",
            eligible=True,
            contact_cap_remaining=1,
            verification_value="must-never-cross-the-wire",
        )


def test_case_list_contains_only_operator_safe_summaries() -> None:
    """The list contract cannot carry account or verification values."""
    response = CasesResponse(
        cases=(
            CaseSummary(
                case_id="case-rakesh",
                borrower_display_name="Rakesh Yadav",
                eligible=True,
                contact_cap_remaining=1,
            ),
        )
    )

    body = response.model_dump(mode="json")
    assert body["cases"][0]["mock_data"] is True
    assert set(body["cases"][0]) == {
        "api_version",
        "case_id",
        "borrower_display_name",
        "eligible",
        "contact_cap_remaining",
        "mock_data",
    }


def test_preflight_check_uses_the_wire_key_pass() -> None:
    """Python's safe attribute name still matches the frozen JSON contract."""
    response = PreflightResponse(
        result=PreflightResult.READY,
        checks=(PreflightCheck(name="backend", **{"pass": True}, detail="Backend is reachable."),),
    )

    body = response.model_dump(mode="json", by_alias=True)
    assert body["checks"][0]["pass"] is True
    assert "passed" not in body["checks"][0]


def test_server_event_requires_supported_type_sequence_and_timezone() -> None:
    """Ledger mirror events fail closed on malformed ordering metadata."""
    with pytest.raises(ValidationError):
        ServerEvent(
            type="invented_ui_state",
            call_id="call-1",
            seq=1,
            ts=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        ServerEvent(
            type=EventType.ERROR,
            call_id="call-1",
            seq=0,
            ts=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
        )
    with pytest.raises(ValidationError):
        ServerEvent(
            type=EventType.ERROR,
            call_id="call-1",
            seq=1,
            ts=datetime(2026, 7, 26, 12, 0),
        )


def test_evidence_events_are_ordered_unique_and_call_scoped() -> None:
    """The evidence response cannot combine or reorder ledger streams."""
    response = EvidenceResponse(call_id="call-1", events=(event(seq=1), event(seq=2)))
    assert [item.seq for item in response.events] == [1, 2]

    with pytest.raises(ValidationError, match="unique and ordered"):
        EvidenceResponse(call_id="call-1", events=(event(seq=2), event(seq=1)))
    with pytest.raises(ValidationError, match="requested call"):
        EvidenceResponse(call_id="call-1", events=(event(call_id="call-2"),))
