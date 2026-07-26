"""Contract tests for Vachan's versioned REST and WebSocket messages."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.protocol import (
    PROTOCOL_VERSION,
    VOICE_CLIENT_CONTROL_FRAME_ADAPTER,
    VOICE_SERVER_FRAME_ADAPTER,
    AgentAudioFrame,
    AgentFloorControlFrame,
    CasesResponse,
    CaseSummary,
    EventType,
    EvidenceResponse,
    MediaFrameKind,
    PreflightCheck,
    PreflightResponse,
    PreflightResult,
    ServerEvent,
    TurnTimings,
    VoiceReadyFrame,
    VoiceTransportErrorFrame,
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


def test_live_voice_frames_are_versioned_call_scoped_and_discriminated() -> None:
    """Transient media has an explicit contract and cannot pose as ledger evidence."""
    timestamp = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    frames = (
        VoiceReadyFrame(call_id="call-1", sample_rate=16_000),
        AgentAudioFrame(
            call_id="call-1",
            media_seq=1,
            ts=timestamp,
            kind=MediaFrameKind.OPENING,
            final_media=False,
            audio_base64="UklGRg==",
            speech_text="सुरक्षित शुरुआत।",
            timings=TurnTimings(stt_ms=0, llm_ms=0, tts_ms=250, total_ms=250),
        ),
        VoiceTransportErrorFrame(call_id="call-1", detail="Speech controller is unavailable"),
    )

    for frame in frames:
        body = frame.model_dump(mode="json")
        assert body["api_version"] == PROTOCOL_VERSION
        assert body["call_id"] == "call-1"
        assert VOICE_SERVER_FRAME_ADAPTER.validate_python(body) == frame
    assert frames[1].model_dump(mode="json")["source"] == "transient_media"
    assert "seq" not in frames[1].model_dump(mode="json")


def test_agent_floor_control_is_versioned_strict_and_content_free() -> None:
    """The browser reports only playback ownership; STT decides interruption."""
    frame = AgentFloorControlFrame(held=True)
    body = frame.model_dump(mode="json")

    assert body == {
        "api_version": PROTOCOL_VERSION,
        "type": "agent_floor",
        "held": True,
    }
    assert VOICE_CLIENT_CONTROL_FRAME_ADAPTER.validate_python(body) == frame

    for invalid in (
        {**body, "held": "true"},
        {**body, "held": 1},
        {**body, "interrupted": True},
        {**body, "transcript": "borrower speech must not cross this control"},
        {**body, "api_version": "v1"},
        {**body, "type": "mute"},
    ):
        with pytest.raises(ValidationError):
            VOICE_CLIENT_CONTROL_FRAME_ADAPTER.validate_python(invalid)


def test_live_audio_contract_rejects_legacy_and_impossible_frames() -> None:
    """Legacy side-protocol aliases and dishonest timing fail closed."""
    timestamp = datetime(2026, 7, 26, 12, 0, tzinfo=UTC).isoformat()
    valid = {
        "api_version": PROTOCOL_VERSION,
        "type": "agent_audio",
        "source": "transient_media",
        "call_id": "call-1",
        "media_seq": 1,
        "ts": timestamp,
        "kind": "turn",
        "final_media": False,
        "audio_base64": "UklGRg==",
        "content_type": "audio/wav",
        "speech_text": "सुरक्षित उत्तर।",
        "timings": {"stt_ms": 100, "llm_ms": 200, "tts_ms": 300, "total_ms": 600},
    }

    for field, invalid in (
        ("api_version", "v1"),
        ("type", "agent_turn"),
        ("source", "persisted_ledger"),
        ("call_id", ""),
        ("media_seq", 0),
        ("ts", "2026-07-26T12:00:00"),
    ):
        body = {**valid, field: invalid}
        with pytest.raises(ValidationError):
            VOICE_SERVER_FRAME_ADAPTER.validate_python(body)

    impossible = {
        **valid,
        "timings": {"stt_ms": 100, "llm_ms": 200, "tts_ms": 300, "total_ms": 599},
    }
    with pytest.raises(ValidationError, match="cover every measured media stage"):
        VOICE_SERVER_FRAME_ADAPTER.validate_python(impossible)


def test_shared_live_voice_frame_cases_match_backend_contract() -> None:
    """The Python validator agrees with the mirrored browser fixture verdicts."""
    fixture_path = Path(__file__).parent / "fixtures" / "live_voice_frame_cases.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))

    for case in cases:
        try:
            VOICE_SERVER_FRAME_ADAPTER.validate_python(case["frame"])
            accepted = True
        except ValidationError:
            accepted = False
        assert accepted is case["accepted"], case["name"]
