"""Versioned wire contract shared by Vachan's REST and WebSocket surfaces.

These models describe transport data only. Domain state machines and evidence
persistence remain separate boundaries, and endpoint handlers must serialize
ledger rows through :class:`ServerEvent` instead of inventing UI-only state.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

PROTOCOL_VERSION = "v0"
ProtocolVersion = Literal["v0"]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class ProtocolModel(BaseModel):
    """Strict immutable base for all JSON protocol messages."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    api_version: ProtocolVersion = PROTOCOL_VERSION


class PreflightResult(StrEnum):
    """Whether policy and technical checks allow a call to start."""

    READY = "READY"
    BLOCKED_POLICY = "BLOCKED_POLICY"
    BLOCKED_TECHNICAL = "BLOCKED_TECHNICAL"


class EventType(StrEnum):
    """Server event categories mirrored one-for-one from evidence rows."""

    STATE_CHANGE = "state_change"
    UTTERANCE = "utterance"
    TOOL_DECISION = "tool_decision"
    GUARD_BLOCK = "guard_block"
    DISPOSITION = "disposition"
    DIAGNOSTIC = "diagnostic"
    ERROR = "error"


class TransportMode(StrEnum):
    """The two transports considered by the permanent H0:45 decision."""

    STREAMING_PCM16_WS = "streaming_pcm16_ws"
    TURN_BASED_REST = "turn_based_rest"


class MediaFrameKind(StrEnum):
    """The only transient agent-audio origins exposed to the browser."""

    OPENING = "opening"
    TURN = "turn"
    RECOVERY = "recovery"


class TurnTimings(BaseModel):
    """Non-negative stage timings attached to a measured media frame."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stt_ms: int = Field(ge=0)
    llm_ms: int = Field(ge=0)
    tts_ms: int = Field(ge=0)
    total_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "TurnTimings":
        """Reject internally impossible latency summaries."""
        if self.total_ms < self.stt_ms + self.llm_ms + self.tts_ms:
            raise ValueError("total_ms must cover every measured media stage")
        return self


class VoiceReadyFrame(ProtocolModel):
    """Call-correlated acknowledgement for the live PCM16 socket."""

    type: Literal["ready"] = "ready"
    call_id: Identifier
    sample_rate: int = Field(gt=0)
    encoding: Literal["pcm_s16le"] = "pcm_s16le"


class AgentAudioFrame(ProtocolModel):
    """Transient guarded audio, explicitly distinct from durable evidence."""

    type: Literal["agent_audio"] = "agent_audio"
    source: Literal["transient_media"] = "transient_media"
    call_id: Identifier
    media_seq: int = Field(gt=0)
    ts: AwareDatetime
    kind: MediaFrameKind
    final_media: bool = False
    audio_base64: Identifier
    content_type: Literal["audio/wav"] = "audio/wav"
    speech_text: Identifier
    timings: TurnTimings | None = None


class VoiceTransportErrorFrame(ProtocolModel):
    """Safe call-correlated transport failure sent before socket closure."""

    type: Literal["transport_error"] = "transport_error"
    call_id: Identifier
    detail: Reason


VoiceServerFrame = Annotated[
    VoiceReadyFrame | AgentAudioFrame | VoiceTransportErrorFrame,
    Field(discriminator="type"),
]
VOICE_SERVER_FRAME_ADAPTER = TypeAdapter(VoiceServerFrame)


class AgentFloorControlFrame(ProtocolModel):
    """Browser signal delimiting an agent-playback suppression window.

    The backend, not the browser, decides whether the edge interrupted an
    in-progress utterance from its authoritative STT/VAD state.
    """

    type: Literal["agent_floor"] = "agent_floor"
    held: StrictBool


VoiceClientControlFrame = Annotated[
    AgentFloorControlFrame,
    Field(discriminator="type"),
]
VOICE_CLIENT_CONTROL_FRAME_ADAPTER = TypeAdapter(VoiceClientControlFrame)


class CaseSummary(ProtocolModel):
    """Operator-safe mock case data; private account/auth fields are absent."""

    case_id: Identifier
    borrower_display_name: Identifier
    eligible: bool
    contact_cap_remaining: int = Field(ge=0)
    mock_data: Literal[True] = True


class CasesResponse(ProtocolModel):
    """Response body for ``GET /api/cases``."""

    cases: tuple[CaseSummary, ...]


class PreflightRequest(ProtocolModel):
    """Request body for ``POST /api/preflight``."""

    case_id: Identifier


class PreflightCheck(ProtocolModel):
    """One policy or technical preflight result."""

    name: Identifier
    passed: bool = Field(alias="pass", serialization_alias="pass")
    detail: Reason


class PreflightResponse(ProtocolModel):
    """Response body for ``POST /api/preflight``."""

    result: PreflightResult
    checks: tuple[PreflightCheck, ...]


class StartCallRequest(ProtocolModel):
    """Request body for ``POST /api/call/start``."""

    case_id: Identifier


class StartCallResponse(ProtocolModel):
    """Response body for ``POST /api/call/start``."""

    call_id: Identifier


class EndCallRequest(ProtocolModel):
    """Request body for ``POST /api/call/end``."""

    call_id: Identifier
    reason: Reason


class TakeoverRequest(ProtocolModel):
    """Request body for ``POST /api/takeover``."""

    call_id: Identifier


class ResetResponse(ProtocolModel):
    """Response body for a successful ``POST /api/reset``."""

    reset: Literal[True] = True
    seeded_case_count: int = Field(ge=0)


class UtteranceMetadata(ProtocolModel):
    """Form metadata accompanying the REST fallback's audio blob."""

    call_id: Identifier
    content_type: Identifier


class ServerEvent(ProtocolModel):
    """A JSON event sent over WS or returned by the evidence endpoint.

    ``seq`` is positive and monotonically increasing within one call.
    ``ts`` must carry a timezone. The event body is deliberately JSON-only so
    the persisted ledger representation and the wire representation cannot
    diverge through Python-specific values.
    """

    type: EventType
    call_id: Identifier
    seq: int = Field(gt=0)
    ts: AwareDatetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class EvidenceResponse(ProtocolModel):
    """Response body for ``GET /api/evidence/{call_id}``."""

    call_id: Identifier
    events: tuple[ServerEvent, ...]

    def model_post_init(self, context: object, /) -> None:
        """Reject cross-call or non-monotonic event collections."""
        if any(event.call_id != self.call_id for event in self.events):
            raise ValueError("all evidence events must belong to the requested call")

        sequences = [event.seq for event in self.events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("evidence event sequence numbers must be unique and ordered")


# FastAPI multipart handlers accept ``audio`` as UploadFile and validate these
# form fields through UtteranceMetadata. This constant makes that contract
# explicit without pretending a binary blob is a JSON/Pydantic field.
UTTERANCE_AUDIO_FORM_FIELD = "audio"
UTTERANCE_CONTENT_TYPES = frozenset({"audio/wav", "audio/webm", "audio/ogg"})


def utc_event_timestamp(value: AwareDatetime) -> datetime:
    """Return an event timestamp normalized to UTC for ledger serialization."""
    return value.astimezone(UTC)
