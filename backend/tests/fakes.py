"""Deterministic test doubles and evidence assertions for controller tests.

The fake models the network boundary, not policy. Scenario scripts provide
caller audio transcripts and untrusted model proposals; production code must
still perform verification, authorization, state transitions, and output
guarding itself.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.tools import ToolName

JsonObject = dict[str, Any]

STT_MODEL = "saaras:v3"
CHAT_MODEL = "sarvam-30b"
CHAT_TEMPERATURE = 0.1
CHAT_MAX_TOKENS = 4_096
TTS_MODEL = "bulbul:v3"

# A minimal RIFF/WAVE header is enough to prove that tests capture audio bytes
# rather than invoking a device. It is intentionally synthetic and silent.
SILENT_WAV = (
    b"RIFF"
    b"\x24\x00\x00\x00"
    b"WAVE"
    b"fmt "
    b"\x10\x00\x00\x00"
    b"\x01\x00"
    b"\x01\x00"
    b"\xc0\x5d\x00\x00"
    b"\x80\xbb\x00\x00"
    b"\x02\x00"
    b"\x10\x00"
    b"data"
    b"\x00\x00\x00\x00"
)


class ScenarioExhausted(AssertionError):
    """A fake call was made after its deterministic script was consumed."""


@dataclass(frozen=True, slots=True)
class ScriptedTurn:
    """One caller turn and the untrusted action proposed for it."""

    transcript: str
    action: Mapping[str, object]
    tts_audio: bytes = SILENT_WAV


@dataclass(frozen=True, slots=True)
class SarvamScenario:
    """Ordered network responses for one deterministic controller scenario."""

    name: str
    turns: tuple[ScriptedTurn, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name must not be empty")
        if not self.turns:
            raise ValueError("scenario must contain at least one turn")


@dataclass(slots=True)
class FakeSarvamClient:
    """Scripted async substitute for STT, chat completion, and TTS.

    STT and TTS response envelopes match the keys and value types captured by
    the live dependency smoke. Chat returns the OpenAI-compatible envelope
    documented by Sarvam, with the scripted typed action JSON in ``content``.
    """

    scenario: SarvamScenario
    stt_requests: list[JsonObject] = field(default_factory=list)
    chat_requests: list[JsonObject] = field(default_factory=list)
    tts_requests: list[JsonObject] = field(default_factory=list)
    captured_audio: list[bytes] = field(default_factory=list)
    _stt_index: int = 0
    _chat_index: int = 0
    _tts_index: int = 0

    def _turn(self, index: int, capability: str) -> ScriptedTurn:
        try:
            return self.scenario.turns[index]
        except IndexError as error:
            raise ScenarioExhausted(
                f"{self.scenario.name}: unexpected {capability} call at index {index}"
            ) from error

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str = "audio/wav",
        model: str = STT_MODEL,
        mode: str = "transcribe",
        language_code: str = "hi-IN",
    ) -> JsonObject:
        """Return the next live-capture-shaped STT envelope."""

        if not audio:
            raise ValueError("audio must not be empty")
        turn = self._turn(self._stt_index, "STT")
        self._stt_index += 1
        self.stt_requests.append(
            {
                "byte_count": len(audio),
                "content_type": content_type,
                "model": model,
                "mode": mode,
                "language_code": language_code,
            }
        )
        return {
            "request_id": f"fake-stt-{self._stt_index:04d}",
            "transcript": turn.transcript,
            "language_code": language_code,
        }

    async def chat_completion(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        model: str = CHAT_MODEL,
        temperature: float = CHAT_TEMPERATURE,
        max_tokens: int = CHAT_MAX_TOKENS,
    ) -> JsonObject:
        """Return the next scripted action in the production adapter envelope."""

        turn = self._turn(self._chat_index, "chat")
        self._chat_index += 1
        self.chat_requests.append(
            {
                "model": model,
                "messages": [dict(message) for message in messages],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            dict(turn.action),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    }
                }
            ],
        }

    async def synthesize(
        self,
        text: str,
        *,
        target_language_code: str = "hi-IN",
        model: str = TTS_MODEL,
        speaker: str = "priya",
        pace: float = 1.0,
        sample_rate: int = 24_000,
        output_audio_codec: str = "wav",
        temperature: float = 0.6,
        enable_preprocessing: bool = True,
    ) -> JsonObject:
        """Capture one request and return the production dialogue adapter shape."""

        if not text.strip():
            raise ValueError("text must not be empty")
        turn = self._turn(self._tts_index, "TTS")
        self._tts_index += 1
        self.tts_requests.append(
            {
                "text": text,
                "target_language_code": target_language_code,
                "model": model,
                "speaker": speaker,
                "pace": pace,
                "speech_sample_rate": sample_rate,
                "output_audio_codec": output_audio_codec,
                "temperature": temperature,
                "enable_preprocessing": enable_preprocessing,
            }
        )
        self.captured_audio.append(turn.tts_audio)
        return {
            "audio_base64": base64.b64encode(turn.tts_audio).decode("ascii"),
            "content_type": "audio/wav",
            "request_id": f"fake-tts-{self._tts_index:04d}",
        }

    def assert_consumed(self) -> None:
        """Assert that every scripted capability was called once per turn."""

        expected = len(self.scenario.turns)
        actual = (self._stt_index, self._chat_index, self._tts_index)
        if actual != (expected, expected, expected):
            raise AssertionError(
                f"{self.scenario.name}: expected {expected} calls per capability, got {actual}"
            )


@dataclass(frozen=True, slots=True)
class FrozenDemoClock:
    """Callable clock that can never consult wall time."""

    current: datetime

    def now(self) -> datetime:
        return self.current


_CONFIRMED_ONLY_TOOLS = frozenset(
    {
        ToolName.READ_MOCK_ACCOUNT.value,
        ToolName.CREATE_PROMISE_CANDIDATE.value,
        ToolName.CORRECT_PROMISE_CANDIDATE.value,
        ToolName.COMMIT_PROMISE.value,
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceAssertions:
    """Call-scoped assertions shared by the deterministic matrix tests."""

    connection: sqlite3.Connection

    def assert_event_sequence(self, call_id: str, expected: Sequence[str]) -> None:
        actual = [
            str(row["type"])
            for row in self.connection.execute(
                "SELECT type FROM events WHERE call_id = ? ORDER BY seq",
                (call_id,),
            )
        ]
        normalized = [getattr(item, "value", item) for item in expected]
        assert actual == normalized

    def assert_single_disposition(self, call_id: str) -> None:
        call = self.connection.execute(
            "SELECT disposition, ended FROM calls WHERE id = ?",
            (call_id,),
        ).fetchone()
        assert call is not None, f"unknown call_id={call_id}"
        assert call["disposition"] is not None
        assert call["ended"] is not None
        disposition_events = self.connection.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE call_id = ? AND type = 'DISPOSITION_SET'
            """,
            (call_id,),
        ).fetchone()[0]
        assert disposition_events == 1

    def assert_no_disclosure(self, call_id: str) -> None:
        """Prove private markers/tools do not appear outside CONFIRMED."""

        private_tool_rows = self.connection.execute(
            """
            SELECT tool FROM tool_decisions
            WHERE call_id = ?
              AND allowed = 1
              AND identity_state != 'CONFIRMED'
            """,
            (call_id,),
        ).fetchall()
        assert not ({str(row["tool"]) for row in private_tool_rows} & _CONFIRMED_ONLY_TOOLS), (
            "a confirmed-only tool was allowed before identity confirmation"
        )

        case_row = self.connection.execute(
            """
            SELECT lender_name, outstanding_minor, verification_reference_last4
            FROM cases
            WHERE id = (SELECT case_id FROM calls WHERE id = ?)
            """,
            (call_id,),
        ).fetchone()
        assert case_row is not None, f"unknown call_id={call_id}"
        private_markers = {
            str(case_row["lender_name"]).casefold(),
            str(case_row["outstanding_minor"]),
            str(case_row["verification_reference_last4"]),
        }

        rows = self.connection.execute(
            """
            SELECT state_before, state_after, redacted_reason
            FROM events WHERE call_id = ? ORDER BY seq
            """,
            (call_id,),
        ).fetchall()
        for row in rows:
            before = json.loads(row["state_before"])
            after = json.loads(row["state_after"])
            if before.get("identity") == after.get("identity") == "CONFIRMED":
                continue
            reason = str(row["redacted_reason"]).casefold()
            assert not any(marker in reason for marker in private_markers)
