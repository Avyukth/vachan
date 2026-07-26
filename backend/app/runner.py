"""Timestamped Tier-3 evidence runner for the current Vachan build.

The runner never accepts manually typed pass counts. It executes the Tier-2
pytest matrix, streams three honestly labeled prerecorded WAVs through real
Saaras STT, runs their transcripts through the production parsing/controller
boundaries, and writes a replaceable artifact derived from those results.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import io
import json
import re
import sqlite3
import subprocess
import unicodedata
import wave
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.audio_spike import open_sarvam_stream, response_payload
from app.controller import DialogueController
from app.db import EvidenceLedger, connect_database, migrate_schema
from app.llm import deterministic_preconfirmation_intent
from app.promise import normalize_amount_minor
from app.sarvam_client import load_sarvam_api_key
from app.seeds import DEMO_TIME_ANCHOR, RAKESH_CASE, reset_and_reseed_demo_cases
from app.states import IdentityState, PromiseState

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
MATRIX_PATH = BACKEND_ROOT / "tests" / "test_matrix.py"
DEFAULT_ARTIFACT_PATH = BACKEND_ROOT / "artifacts" / "evidence_run.txt"
IST = ZoneInfo("Asia/Kolkata")
TRANSPORT_LABEL = "streaming_pcm16_ws"
STT_TIMEOUT_SECONDS = 20.0
PCM_CHUNK_BYTES = 3_200
MINIMUM_MATRIX_CASES = 13
_MATRIX_TEST_NAME = re.compile(r"^test_matrix_(?P<case_id>\d{2})(?:_|$)")


class EvidenceTier(StrEnum):
    MATRIX = "matrix-offline"
    AUDIO = "audio-real-stt"


@dataclass(frozen=True, slots=True)
class CaseResult:
    """One derived result line with redacted failure diagnostics."""

    case_id: str
    name: str
    tier: EvidenceTier
    passed: bool
    input_label: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class AudioEvidenceCase:
    """One prerecorded input and its deterministic post-STT scenario."""

    case_id: str
    name: str
    wav_path: Path
    scenario: str
    source_label: str = "synthetic-hi-IN"


AUDIO_CASES = (
    AudioEvidenceCase(
        "A1",
        "borrower-promise-offer",
        BACKEND_ROOT / "tests" / "fixtures" / "audio_e2e_correct.wav",
        "offer",
    ),
    AudioEvidenceCase(
        "A2",
        "spouse-pressure",
        BACKEND_ROOT / "tests" / "fixtures" / "audio_e2e_spouse.wav",
        "spouse",
    ),
    AudioEvidenceCase(
        "A3",
        "promise-correction",
        BACKEND_ROOT / "tests" / "fixtures" / "audio_e2e_correction.wav",
        "correction",
    ),
)


def _redacted_event_sequence(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """
        SELECT call_id, seq, type, state_after
        FROM events
        ORDER BY call_id, seq
        """
    ).fetchall()
    sequence = []
    for row in rows:
        state_after = json.loads(row["state_after"])
        sequence.append(
            {
                "call": str(row["call_id"]),
                "seq": int(row["seq"]),
                "type": str(row["type"]),
                "state": {
                    "call": state_after.get("call"),
                    "identity": state_after.get("identity"),
                    "promise": state_after.get("promise"),
                },
            }
        )
    return json.dumps(sequence, separators=(",", ":"), sort_keys=True)


class _MatrixPlugin:
    """Capture pytest outcomes plus state-only diagnostics before fixture teardown."""

    def __init__(self) -> None:
        self.results: list[CaseResult] = []
        self.expected_case_ids: tuple[str, ...] = ()

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        """Derive the matrix contract from pytest's collected test metadata."""

        case_ids = []
        for item in session.items:
            if not item.nodeid.startswith("tests/test_matrix.py::"):
                continue
            match = _MATRIX_TEST_NAME.match(item.name)
            case_ids.append(match.group("case_id") if match is not None else "UNNUMBERED")
        self.expected_case_ids = tuple(case_ids)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: pytest.CallInfo[Any]):
        outcome = yield
        report = outcome.get_result()
        if report.when != "call" or not item.nodeid.startswith("tests/test_matrix.py::"):
            return
        match = _MATRIX_TEST_NAME.match(item.name)
        case_id = match.group("case_id") if match is not None else "UNNUMBERED"
        detail = ""
        if report.failed:
            connection = item.funcargs.get("db_connection")
            if isinstance(connection, sqlite3.Connection):
                detail = f"seq: {_redacted_event_sequence(connection)}"
            else:
                detail = "seq: []"
        self.results.append(
            CaseResult(
                case_id=case_id,
                name=item.name.removeprefix("test_matrix_").replace("_", "-"),
                tier=EvidenceTier.MATRIX,
                passed=report.passed,
                input_label="typed-script",
                detail=detail,
            )
        )


def _matrix_collection_contract_failure(
    results: Sequence[CaseResult],
    exit_code: pytest.ExitCode,
    expected_case_ids: Sequence[str],
) -> CaseResult | None:
    """Describe collection drift without hiding the cases that did execute."""

    collected = tuple(result.case_id for result in results)
    counts = Counter(collected)
    expected = tuple(expected_case_ids)
    expected_counts = Counter(expected)
    missing = tuple(
        case_id
        for case_id, expected_count in expected_counts.items()
        if counts[case_id] < expected_count
    )
    extra = tuple(sorted(case_id for case_id in counts if case_id not in expected_counts))
    duplicates = tuple(sorted(case_id for case_id, count in counts.items() if count > 1))
    invalid = tuple(
        sorted(
            case_id
            for case_id in {*expected, *collected}
            if re.fullmatch(r"\d{2}", case_id) is None
        )
    )
    collection_failed = exit_code not in {pytest.ExitCode.OK, pytest.ExitCode.TESTS_FAILED}
    below_floor = len(expected) < MINIMUM_MATRIX_CASES
    if (
        not missing
        and not extra
        and not duplicates
        and not invalid
        and not collection_failed
        and not below_floor
    ):
        return None

    diagnostic = json.dumps(
        {
            "collected": collected,
            "collected_count": len(collected),
            "duplicates": duplicates,
            "exit_code": exit_code.name,
            "expected": expected,
            "expected_count": len(expected),
            "extra": extra,
            "invalid": invalid,
            "minimum": MINIMUM_MATRIX_CASES,
            "missing": missing,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return CaseResult(
        "00",
        "matrix-collection-contract",
        EvidenceTier.MATRIX,
        False,
        "typed-script",
        f"seq: [] collection={diagnostic}",
    )


def run_matrix() -> tuple[CaseResult, ...]:
    """Execute the contracted pytest matrix without parsing console prose."""

    plugin = _MatrixPlugin()
    pytest_output = io.StringIO()
    with contextlib.redirect_stdout(pytest_output), contextlib.redirect_stderr(pytest_output):
        exit_code = pytest.main(
            ["-q", str(MATRIX_PATH), "--disable-warnings"],
            plugins=[plugin],
        )
    results = tuple(plugin.results)
    contract_failure = _matrix_collection_contract_failure(
        results,
        exit_code,
        plugin.expected_case_ids,
    )
    return results if contract_failure is None else (*results, contract_failure)


def _load_pcm16(wav_path: Path) -> bytes:
    if not wav_path.is_file():
        raise FileNotFoundError(f"prerecorded fixture is missing: {wav_path.name}")
    with wave.open(str(wav_path), "rb") as recording:
        shape = (
            recording.getnchannels(),
            recording.getsampwidth(),
            recording.getframerate(),
        )
        if shape != (1, 2, 16_000):
            raise ValueError(f"{wav_path.name} must be mono PCM16 at 16000 Hz; received {shape}")
        return recording.readframes(recording.getnframes())


def _stream_transcript(message: object) -> str | None:
    payload = message if isinstance(message, dict) else response_payload(message)
    if payload.get("type") != "data":
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    transcript = data.get("transcript")
    return transcript.strip() if isinstance(transcript, str) and transcript.strip() else None


async def transcribe_prerecorded_wav(wav_path: Path) -> str:
    """Stream one validated fixture through the real Saaras v3 boundary."""

    pcm = _load_pcm16(wav_path)
    api_key = load_sarvam_api_key()
    async with open_sarvam_stream(api_key) as stream:
        for offset in range(0, len(pcm), PCM_CHUNK_BYTES):
            chunk = pcm[offset : offset + PCM_CHUNK_BYTES]
            if not chunk:
                continue
            await stream.transcribe(
                audio=base64.b64encode(chunk).decode("ascii"),
                encoding="audio/wav",
                sample_rate=16_000,
            )
        await stream.flush()
        async with asyncio.timeout(STT_TIMEOUT_SECONDS):
            async for message in stream:
                transcript = _stream_transcript(message)
                if transcript is not None:
                    return transcript
    raise RuntimeError("Saaras returned no finalized transcript")


class _RecordedBoundary:
    """Controller network boundary after the real STT transcript is captured."""

    def __init__(
        self,
        turns: Sequence[tuple[str, Mapping[str, object]]],
    ) -> None:
        self._turns = tuple(turns)
        self._stt_index = 0
        self._chat_index = 0

    async def transcribe(self, audio: bytes, **_: object) -> dict[str, object]:
        transcript = self._turns[self._stt_index][0]
        self._stt_index += 1
        return {"transcript": transcript, "language_code": "hi-IN"}

    async def chat_completion(
        self,
        messages: Sequence[Mapping[str, object]],
        **_: object,
    ) -> dict[str, object]:
        del messages
        action = self._turns[self._chat_index][1]
        self._chat_index += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            dict(action),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    }
                }
            ]
        }

    async def synthesize(self, text: str, **_: object) -> dict[str, object]:
        del text
        return {"request_id": "evidence-tts-skipped", "audios": []}


def _fresh_ledger() -> EvidenceLedger:
    connection = connect_database(":memory:")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    return ledger


_VERIFY_TURNS = (
    ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
    ("चौदह सितंबर, reference 4729", {"intent": "verification_response"}),
)


def parse_audio_amount(transcript: str) -> int:
    """Extract only the reviewed audio-evidence amount vectors."""

    normalized = " ".join(
        re.sub(
            r"[^\w\u0900-\u097f]+",
            " ",
            unicodedata.normalize("NFKC", transcript).casefold(),
        ).split()
    )
    for phrase in (
        "पंद्रह सौ",
        "pandrah sau",
        "एक हजार पचास",
        "एक हज़ार पचास",
        "ek hazaar pachaas",
        "ek hazaar paanchas",
    ):
        if phrase in normalized:
            return normalize_amount_minor(phrase)
    numeric = re.search(r"(?<!\d)(1050|1500)(?!\d)", normalized)
    if numeric is not None:
        return normalize_amount_minor(numeric.group(1))
    raise ValueError("audio transcript does not contain a reviewed evidence amount")


async def _exercise_audio_case(case: AudioEvidenceCase, transcript: str) -> tuple[bool, str]:
    ledger = _fresh_ledger()
    try:
        if case.scenario == "offer":
            amount_minor = parse_audio_amount(transcript)
            turns = (
                *_VERIFY_TURNS,
                (
                    transcript,
                    {
                        "intent": "offer_promise",
                        "amount_minor": amount_minor,
                        "date_phrase": "Friday",
                    },
                ),
            )
        elif case.scenario == "spouse":
            intent = deterministic_preconfirmation_intent(
                transcript,
                borrower_display_name=RAKESH_CASE.borrower_display_name,
            )
            turns = tuple((transcript, {"intent": intent.value}) for _ in range(3))
        elif case.scenario == "correction":
            amount_minor = parse_audio_amount(transcript)
            turns = (
                *_VERIFY_TURNS,
                (
                    "pandrah sau Friday",
                    {
                        "intent": "offer_promise",
                        "amount_minor": 150_000,
                        "date_phrase": "Friday",
                    },
                ),
                (
                    transcript,
                    {
                        "intent": "correct_promise",
                        "amount_minor": amount_minor,
                    },
                ),
            )
        else:
            raise ValueError(f"unsupported audio evidence scenario: {case.scenario}")

        controller = DialogueController(
            call_id=f"call-evidence-{case.case_id.casefold()}",
            case=RAKESH_CASE,
            ledger=ledger,
            sarvam=_RecordedBoundary(turns),
            clock=lambda: DEMO_TIME_ANCHOR,
            transport=TRANSPORT_LABEL,
        )
        await controller.start()
        for _ in turns:
            await controller.run_turn()

        if case.scenario == "offer":
            passed = (
                controller.snapshot.identity is IdentityState.CONFIRMED
                and controller.snapshot.promise is PromiseState.READ_BACK
                and controller._promise.candidate is not None  # noqa: SLF001
                and controller._promise.candidate.amount_minor == 150_000  # noqa: SLF001
            )
        elif case.scenario == "spouse":
            passed = (
                controller.disposition is not None
                and len(controller.callback_payloads) == 1
                and len({request[0] for request in turns}) == 1
            )
        else:
            candidate = controller._promise.candidate  # noqa: SLF001
            passed = (
                candidate is not None
                and candidate.amount_minor == 105_000
                and candidate.revision == 2
                and controller.snapshot.promise is PromiseState.READ_BACK
            )
        return passed, "" if passed else f"seq: {controller.event_types()}"
    finally:
        ledger.close()


Transcriber = Callable[[Path], Awaitable[str]]


async def run_audio_cases(
    *,
    transcribe: Transcriber = transcribe_prerecorded_wav,
) -> tuple[CaseResult, ...]:
    """Run all prerecorded cases through STT then real code-owned boundaries."""

    results: list[CaseResult] = []
    for case in AUDIO_CASES:
        try:
            transcript = await transcribe(case.wav_path)
            passed, detail = await _exercise_audio_case(case, transcript)
        except Exception as error:
            passed = False
            detail = f"seq: [] error={type(error).__name__}"
        results.append(
            CaseResult(
                case.case_id,
                case.name,
                EvidenceTier.AUDIO,
                passed,
                f"prerecorded-wav source:{case.source_label}",
                detail,
            )
        )
    return tuple(results)


def _build_id() -> str:
    try:
        revision = subprocess.run(  # noqa: S603
            ("git", "rev-parse", "--short", "HEAD"),
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(  # noqa: S603
            ("git", "status", "--porcelain"),
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return "unknown"
    return f"{revision}-dirty" if dirty else revision


def render_artifact(
    matrix: Sequence[CaseResult],
    audio: Sequence[CaseResult],
    *,
    timestamp: datetime,
    build_id: str,
) -> str:
    """Render one deterministic, monospace-friendly evidence block."""

    matrix_passed = sum(result.passed for result in matrix)
    audio_passed = sum(result.passed for result in audio)
    lines = [
        "=== VACHAN EVIDENCE RUN ===",
        (
            f"ts: {timestamp.astimezone(IST).isoformat()}  "
            f"transport: {TRANSPORT_LABEL}  build: {build_id}"
        ),
        f"matrix (offline): {matrix_passed}/{len(matrix)}",
        f"audio e2e (real STT): {audio_passed}/{len(audio)}",
    ]
    for result in (*matrix, *audio):
        status = "PASS" if result.passed else "FAIL"
        line = f"{result.case_id:<3} {result.name:<42} {status}  input: {result.input_label}"
        if result.detail:
            line = f"{line}  {result.detail}"
        lines.append(line)
    lines.append(f"score: {matrix_passed + audio_passed}/{len(matrix) + len(audio)}")
    return "\n".join(lines) + "\n"


async def generate_evidence(
    *,
    artifact_path: Path = DEFAULT_ARTIFACT_PATH,
    matrix_runner: Callable[[], Sequence[CaseResult]] = run_matrix,
    transcribe: Transcriber = transcribe_prerecorded_wav,
    now: Callable[[], datetime] = lambda: datetime.now(IST),
) -> tuple[int, str]:
    """Run both tiers, write the derived artifact, and return a process code."""

    # The matrix contains synchronous tests that intentionally own their own
    # event loops. Keep pytest off this runner's live-STT event loop.
    matrix = tuple(await asyncio.to_thread(matrix_runner))
    audio = await run_audio_cases(transcribe=transcribe)
    artifact = render_artifact(
        matrix,
        audio,
        timestamp=now(),
        build_id=_build_id(),
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(artifact, encoding="utf-8")
    return (0 if all(result.passed for result in (*matrix, *audio)) else 1), artifact


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=DEFAULT_ARTIFACT_PATH,
        help="derived evidence artifact path",
    )
    args = parser.parse_args(argv)
    exit_code, artifact = asyncio.run(generate_evidence(artifact_path=args.artifact))
    print(artifact, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
