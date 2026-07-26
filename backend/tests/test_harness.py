"""Self-tests for the reusable deterministic controller harness."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.audio_spike as audio_spike
from app.actions import (
    PreConfirmationIntent,
    PreConfirmationTemplate,
    validate_preconfirmation_classification,
)
from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import SCHEMA_VERSION, EvidenceLedger
from app.llm import MAX_RESPONSE_TOKENS, SarvamChatClient
from app.sarvam_client import SarvamTextToSpeechClient
from app.seeds import DEMO_TIME_ANCHOR, RAKESH_CASE
from app.states import CallState, IdentityState, PromiseState
from app.stt import StreamingSttSession, SttOutcome
from tests.fakes import FakeSarvamClient, FrozenDemoClock, SarvamScenario

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
SHAPES_PATH = PROJECT_ROOT / "tests" / "fixtures" / "sarvam_api_shapes.json"
TTS_CAPTURE_PATH = PROJECT_ROOT / "artifacts" / "sarvam_tts_smoke_response.json"

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)

JsonObject = dict[str, Any]
ShapeContract = Mapping[str, object]


def _values_at_path(payload: object, path: str) -> list[object]:
    values = [payload]
    for raw_segment in path.split("."):
        is_array = raw_segment.endswith("[]")
        segment = raw_segment[:-2] if is_array else raw_segment
        next_values: list[object] = []
        for value in values:
            if not isinstance(value, Mapping) or segment not in value:
                raise AssertionError(f"missing required field path={path!r} at segment={segment!r}")
            nested = value[segment]
            if is_array:
                if not isinstance(nested, list):
                    raise AssertionError(
                        f"wrong value type path={path!r}: expected array, "
                        f"got {type(nested).__name__}"
                    )
                if not nested:
                    raise AssertionError(f"required array path={path!r} must not be empty")
                next_values.extend(nested)
            else:
                next_values.append(nested)
        values = next_values
    return values


def _matches_type(value: object, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "string|null":
        return value is None or isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "number|null":
        return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "object|null":
        return value is None or isinstance(value, Mapping)
    if expected == "array[object]":
        return (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, Mapping) for item in value)
        )
    if expected == "array[string]":
        return (
            isinstance(value, list) and bool(value) and all(isinstance(item, str) for item in value)
        )
    raise AssertionError(f"unsupported frozen shape type={expected!r}")


def _assert_field_set(
    payload: Mapping[str, object],
    contract: ShapeContract,
    label: str,
) -> None:
    required = set(contract["required_fields"])
    optional = set(contract["optional_fields"])
    actual = set(payload)
    missing = sorted(required - actual)
    unexpected = sorted(actual - required - optional)
    assert not missing, f"{label}: missing required fields={missing}"
    assert not unexpected, f"{label}: undocumented fields={unexpected}"


def _optional_values_at_path(payload: object, path: str) -> list[object]:
    values = [payload]
    for raw_segment in path.split("."):
        is_array = raw_segment.endswith("[]")
        segment = raw_segment[:-2] if is_array else raw_segment
        next_values: list[object] = []
        for value in values:
            if not isinstance(value, Mapping):
                raise AssertionError(
                    f"wrong value type path={path!r}: expected object, got {type(value).__name__}"
                )
            if segment not in value:
                return []
            nested = value[segment]
            if is_array:
                if not isinstance(nested, list):
                    raise AssertionError(
                        f"wrong value type path={path!r}: expected array, "
                        f"got {type(nested).__name__}"
                    )
                next_values.extend(nested)
            else:
                next_values.append(nested)
        values = next_values
    return values


def _assert_shape(payload: Mapping[str, object], contract: ShapeContract, label: str) -> None:
    _assert_field_set(payload, contract, label)

    nested_fields = contract.get("nested_fields", {})
    assert isinstance(nested_fields, Mapping)
    for path, field_contract in nested_fields.items():
        assert isinstance(path, str)
        assert isinstance(field_contract, Mapping)
        for value in _values_at_path(payload, path):
            assert isinstance(value, Mapping), (
                f"{label}: wrong value type path={path!r}; "
                f"expected=object, got={type(value).__name__}"
            )
            _assert_field_set(value, field_contract, f"{label}.{path}")

    value_types = contract["value_types"]
    assert isinstance(value_types, Mapping)
    for path, expected in value_types.items():
        assert isinstance(path, str)
        assert isinstance(expected, str)
        for value in _values_at_path(payload, path):
            assert _matches_type(value, expected), (
                f"{label}: wrong value type path={path!r}; "
                f"expected={expected}, got={type(value).__name__}"
            )

    optional_value_types = contract.get("optional_value_types", {})
    assert isinstance(optional_value_types, Mapping)
    for path, expected in optional_value_types.items():
        assert isinstance(path, str)
        assert isinstance(expected, str)
        for value in _optional_values_at_path(payload, path):
            assert _matches_type(value, expected), (
                f"{label}: wrong optional value type path={path!r}; "
                f"expected={expected}, got={type(value).__name__}"
            )

    allowed_values = contract.get("allowed_values", {})
    assert isinstance(allowed_values, Mapping)
    for path, allowed in allowed_values.items():
        assert isinstance(path, str)
        assert isinstance(allowed, list)
        for value in _values_at_path(payload, path):
            assert value in allowed, (
                f"{label}: unsupported value path={path!r}; allowed={allowed!r}, got={value!r}"
            )

    expected_values = contract.get("expected_values", {})
    assert isinstance(expected_values, Mapping)
    for path, expected in expected_values.items():
        assert isinstance(path, str)
        values = _values_at_path(payload, path)
        assert values == [expected], (
            f"{label}: wrong fixed value path={path!r}; expected={expected!r}, got={values!r}"
        )


class _CapturedStream:
    def __init__(self) -> None:
        self.chunk_request: JsonObject | None = None
        self.responses: asyncio.Queue[JsonObject] = asyncio.Queue()

    async def transcribe(self, **kwargs: object) -> None:
        self.chunk_request = dict(kwargs)

    async def flush(self) -> None:
        return None

    def __aiter__(self) -> _CapturedStream:
        return self

    async def __anext__(self) -> JsonObject:
        return await self.responses.get()


class _CapturedSttCallbacks:
    def __init__(self) -> None:
        self.transcripts: list[tuple[str, str]] = []
        self.recoveries: list[tuple[str, str]] = []
        self.degradations: list[tuple[str, str]] = []

    async def on_final_transcript(self, call_id: str, transcript: str) -> None:
        self.transcripts.append((call_id, transcript))

    async def on_recovery_prompt(self, call_id: str, line: str) -> None:
        self.recoveries.append((call_id, line))

    async def on_degraded(self, call_id: str, reason_code: str) -> None:
        self.degradations.append((call_id, reason_code))


class _CapturedStreamContext:
    def __init__(self, stream: _CapturedStream) -> None:
        self.stream = stream

    async def __aenter__(self) -> _CapturedStream:
        return self.stream

    async def __aexit__(self, *args: object) -> None:
        return None


class _CapturedStreamingApi:
    def __init__(self, stream: _CapturedStream) -> None:
        self.stream = stream
        self.connect_request: JsonObject | None = None

    def connect(self, **kwargs: object) -> _CapturedStreamContext:
        self.connect_request = dict(kwargs)
        return _CapturedStreamContext(self.stream)


class _CapturedSarvamApi:
    instance: _CapturedSarvamApi | None = None

    def __init__(self, *, api_subscription_key: str) -> None:
        assert api_subscription_key == "test-key"
        self.stream = _CapturedStream()
        self.speech_to_text_streaming = _CapturedStreamingApi(self.stream)
        type(self).instance = self


def _start_call(connection: sqlite3.Connection, call_id: str = "call-harness-001") -> str:
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, 'case-rakesh-001', ?, 'streaming_pcm16_ws')
        """,
        (call_id, NOW.isoformat()),
    )
    return call_id


def _snapshot(identity: IdentityState = IdentityState.UNVERIFIED) -> StateSnapshot:
    return StateSnapshot(
        call=CallState.ACTIVE,
        identity=identity,
        promise=PromiseState.NONE,
    )


def test_database_fixture_is_migrated_seeded_and_fresh(
    db_connection: sqlite3.Connection,
) -> None:
    assert db_connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert [row["id"] for row in db_connection.execute("SELECT id FROM cases ORDER BY id")] == [
        "case-capped-001",
        "case-capped-002",
        "case-rakesh-001",
    ]
    db_connection.execute("UPDATE cases SET contact_cap_remaining = 1 WHERE id = 'case-rakesh-001'")


def test_database_fixture_does_not_share_prior_test_mutations(
    db_connection: sqlite3.Connection,
) -> None:
    remaining = db_connection.execute(
        "SELECT contact_cap_remaining FROM cases WHERE id = 'case-rakesh-001'"
    ).fetchone()[0]
    assert remaining == RAKESH_CASE.contact_cap_remaining


def test_frozen_clock_is_the_seeded_demo_anchor(
    frozen_demo_clock: FrozenDemoClock,
) -> None:
    assert frozen_demo_clock.now() is DEMO_TIME_ANCHOR
    assert frozen_demo_clock.now().isoformat() == "2026-07-26T12:00:00+05:30"


def test_production_requests_and_responses_match_frozen_sarvam_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shapes = json.loads(SHAPES_PATH.read_text())
    live_tts = json.loads(TTS_CAPTURE_PATH.read_text())
    captured_chat: JsonObject = {}
    captured_tts: JsonObject = {}
    raw_chat = {
        "id": "chat-shape-001",
        "object": "chat.completion",
        "created": 0,
        "model": "sarvam-30b",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"intent":"other"}',
                }
            }
        ],
    }

    def chat_handler(request: httpx.Request) -> httpx.Response:
        captured_chat.update(json.loads(request.content))
        return httpx.Response(200, json=raw_chat)

    def tts_handler(request: httpx.Request) -> httpx.Response:
        captured_tts.update(json.loads(request.content))
        return httpx.Response(200, json=live_tts)

    async def exercise() -> None:
        monkeypatch.setattr(audio_spike, "AsyncSarvamAI", _CapturedSarvamApi)
        _CapturedSarvamApi.instance = None
        async with audio_spike.open_sarvam_stream("test-key") as stream:
            await stream.transcribe(
                audio="UklGRg==",
                encoding="audio/wav",
                sample_rate=16_000,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(chat_handler)) as chat_http:
            await SarvamChatClient("test-key", http_client=chat_http).complete(
                [{"role": "user", "content": "typed boundary probe"}],
                timeout_seconds=1.0,
                max_tokens=MAX_RESPONSE_TOKENS,
            )
        async with httpx.AsyncClient(transport=httpx.MockTransport(tts_handler)) as tts_http:
            speech = await SarvamTextToSpeechClient(
                "test-key",
                http_client=tts_http,
            ).synthesize("समीक्षित सुरक्षित पंक्ति।")
            assert speech.audio.startswith(b"RIFF")

    asyncio.run(exercise())

    captured_api = _CapturedSarvamApi.instance
    assert captured_api is not None
    connect_request = captured_api.speech_to_text_streaming.connect_request
    chunk_request = captured_api.stream.chunk_request
    assert connect_request is not None
    assert chunk_request is not None

    _assert_shape(
        connect_request,
        shapes["speech_to_text_streaming"]["connect_request"],
        "production STT connect request",
    )
    _assert_shape(
        chunk_request,
        shapes["speech_to_text_streaming"]["chunk_request"],
        "production STT chunk request",
    )
    _assert_shape(
        captured_chat,
        shapes["chat_completion"]["request"],
        "production chat request",
    )
    _assert_shape(
        raw_chat,
        shapes["chat_completion"]["response"],
        "production chat response",
    )
    _assert_shape(
        captured_tts,
        shapes["text_to_speech"]["request"],
        "production TTS request",
    )
    _assert_shape(
        live_tts,
        shapes["text_to_speech"]["response"],
        "production TTS response",
    )


def test_production_stt_consumer_matches_frozen_external_response_shapes() -> None:
    shapes = json.loads(SHAPES_PATH.read_text())
    transcript_response = shapes["speech_to_text_streaming"]["external_transcript_response"][
        "capture"
    ]
    start_response = shapes["speech_to_text_streaming"]["external_vad_response"]["capture"]
    end_response = json.loads(json.dumps(start_response))
    end_response["data"]["signal_type"] = "END_SPEECH"

    _assert_shape(
        transcript_response,
        shapes["speech_to_text_streaming"]["external_transcript_response"],
        "production STT transcript response",
    )
    for signal_response in (start_response, end_response):
        _assert_shape(
            signal_response,
            shapes["speech_to_text_streaming"]["external_vad_response"],
            "production STT VAD response",
        )

    async def exercise() -> None:
        stream = _CapturedStream()
        callbacks = _CapturedSttCallbacks()
        session = StreamingSttSession(
            call_id="call-stt-boundary-001",
            stream=stream,
            callbacks=callbacks,
            is_call_active=lambda: True,
            timeout_seconds=1.0,
        )
        reader = asyncio.create_task(session.run_finalized_results())
        await stream.responses.put(start_response)
        await stream.responses.put(end_response)
        await stream.responses.put(transcript_response)
        for _ in range(20):
            if callbacks.transcripts:
                break
            await asyncio.sleep(0)

        assert callbacks.transcripts == [("call-stt-boundary-001", "synthetic boundary probe")]
        assert callbacks.recoveries == []
        assert callbacks.degradations == []
        session.cancel()
        assert (await reader).outcome is SttOutcome.DROPPED

    asyncio.run(exercise())


def test_fake_envelopes_match_production_dialogue_adapter_shapes(
    fake_sarvam_factory,
    correct_verification_scenario: SarvamScenario,
) -> None:
    shapes = json.loads(SHAPES_PATH.read_text())
    fake: FakeSarvamClient = fake_sarvam_factory(correct_verification_scenario)

    async def exercise() -> tuple[dict, dict, dict]:
        stt = await fake.transcribe(b"synthetic wav")
        chat = await fake.chat_completion([{"role": "user", "content": "typed boundary probe"}])
        tts = await fake.synthesize("कृपया सत्यापन पूरा करें।")
        return stt, chat, tts

    stt, chat, tts = asyncio.run(exercise())
    _assert_shape(
        stt,
        shapes["speech_to_text_streaming"]["controller_test_adapter_response"],
        "fake STT adapter response",
    )
    _assert_shape(
        fake.chat_requests[0],
        shapes["chat_completion"]["request"],
        "fake chat request",
    )
    _assert_shape(
        chat,
        shapes["chat_completion"]["dialogue_adapter_response"],
        "fake chat adapter response",
    )
    _assert_shape(
        fake.tts_requests[0],
        shapes["text_to_speech"]["request"],
        "fake TTS request",
    )
    _assert_shape(
        tts,
        shapes["text_to_speech"]["dialogue_adapter_response"],
        "fake TTS adapter response",
    )
    assert base64.b64decode(tts["audio_base64"]).startswith(b"RIFF")
    assert fake.captured_audio[0].startswith(b"RIFF")


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    [
        ("missing", "missing required fields=['speaker']"),
        ("wrong_type", "wrong value type path='speech_sample_rate'"),
        ("undocumented", "undocumented fields=['voice_clone']"),
    ],
)
def test_shape_failures_name_the_drifted_field(mutation: str, diagnostic: str) -> None:
    shapes = json.loads(SHAPES_PATH.read_text())
    payload: JsonObject = {
        "text": "reviewed line",
        **shapes["text_to_speech"]["request"]["expected_values"],
    }
    if mutation == "missing":
        del payload["speaker"]
    elif mutation == "wrong_type":
        payload["speech_sample_rate"] = "24000"
    else:
        payload["voice_clone"] = "undocumented"

    with pytest.raises(AssertionError, match=re.escape(diagnostic)):
        _assert_shape(
            payload,
            shapes["text_to_speech"]["request"],
            "mutated TTS request",
        )


@pytest.mark.parametrize(
    ("response_name", "path", "replacement", "diagnostic"),
    [
        (
            "external_transcript_response",
            "data.transcript",
            None,
            "production STT transcript response.data: missing required fields=['transcript']",
        ),
        (
            "external_transcript_response",
            "data.transcript",
            7,
            "wrong value type path='data.transcript'",
        ),
        (
            "external_vad_response",
            "data.signal_type",
            None,
            "production STT VAD response.data: missing required fields=['signal_type']",
        ),
        (
            "external_vad_response",
            "data.signal_type",
            7,
            "wrong value type path='data.signal_type'",
        ),
    ],
)
def test_nested_stt_response_drift_names_the_required_field(
    response_name: str,
    path: str,
    replacement: object,
    diagnostic: str,
) -> None:
    shapes = json.loads(SHAPES_PATH.read_text())
    contract = shapes["speech_to_text_streaming"][response_name]
    payload = json.loads(json.dumps(contract["capture"]))
    parent_name, field_name = path.split(".")
    if replacement is None:
        del payload[parent_name][field_name]
    else:
        payload[parent_name][field_name] = replacement

    label = (
        "production STT transcript response"
        if response_name == "external_transcript_response"
        else "production STT VAD response"
    )
    with pytest.raises(AssertionError, match=re.escape(diagnostic)):
        _assert_shape(payload, contract, label)


def test_correct_verification_scenario_runs_through_scripted_network_boundary(
    fake_sarvam_factory,
    correct_verification_scenario: SarvamScenario,
) -> None:
    fake: FakeSarvamClient = fake_sarvam_factory(correct_verification_scenario)

    async def exercise() -> tuple[dict, dict, dict]:
        stt = await fake.transcribe(b"synthetic caller audio")
        chat = await fake.chat_completion(
            [
                {
                    "role": "system",
                    "content": "Classify only; expected verification values are unavailable.",
                },
                {"role": "user", "content": "verification response received"},
            ]
        )
        tts = await fake.synthesize("धन्यवाद।")
        return stt, chat, tts

    stt, chat, tts = asyncio.run(exercise())
    action_json = chat["choices"][0]["message"]["content"]
    result = validate_preconfirmation_classification(action_json)

    assert stt["language_code"] == "hi-IN"
    assert result.accepted is True
    assert result.classification.intent is PreConfirmationIntent.VERIFICATION_RESPONSE
    assert result.template is PreConfirmationTemplate.VERIFY_REQUEST
    assert set(tts) == {"audio_base64", "content_type", "request_id"}
    assert fake.chat_requests[0]["messages"][0]["content"].endswith("unavailable.")
    fake.assert_consumed()


def test_event_assertion_helpers_prove_order_disposition_and_no_disclosure(
    db_connection: sqlite3.Connection,
    evidence_ledger: EvidenceLedger,
    assert_event_sequence,
    assert_no_disclosure,
    assert_single_disposition,
) -> None:
    call_id = _start_call(db_connection)
    before = _snapshot()
    after = _snapshot(IdentityState.VERIFYING)

    async def write_events() -> None:
        await evidence_ledger.append_event(
            call_id=call_id,
            ts=NOW,
            event_type=LedgerEventType.STATE_TRANSITION,
            state_before=before,
            state_after=after,
            redacted_reason="identity_challenge_started",
        )
        await evidence_ledger.append_event(
            call_id=call_id,
            ts=NOW,
            event_type=LedgerEventType.DISPOSITION_SET,
            state_before=after,
            state_after=after,
            redacted_reason="verification_attempts_exhausted",
        )

    asyncio.run(write_events())
    db_connection.execute(
        """
        UPDATE calls
        SET ended = ?, disposition = ?
        WHERE id = ?
        """,
        (NOW.isoformat(), Disposition.VERIFICATION_FAILED.value, call_id),
    )

    assert_event_sequence(
        call_id,
        [LedgerEventType.STATE_TRANSITION, LedgerEventType.DISPOSITION_SET],
    )
    assert_no_disclosure(call_id)
    assert_single_disposition(call_id)
