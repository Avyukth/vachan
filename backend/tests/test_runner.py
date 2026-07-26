"""Tests for honest, derived evidence-runner artifacts."""

from __future__ import annotations

import asyncio
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.runner import (
    AUDIO_CASES,
    CaseResult,
    EvidenceTier,
    _load_pcm16,
    generate_evidence,
    parse_audio_amount,
    render_artifact,
    run_audio_cases,
    run_matrix,
)

IST = ZoneInfo("Asia/Kolkata")


def _matrix(passed: bool = True) -> tuple[CaseResult, ...]:
    return tuple(
        CaseResult(
            f"{index:02d}",
            f"matrix-case-{index}",
            EvidenceTier.MATRIX,
            passed,
            "typed-script",
        )
        for index in range(1, 14)
    )


def _fixture_transcripts() -> dict[str, str]:
    return {
        "audio_e2e_correct.wav": "मैं शुक्रवार को पंद्रह सौ रुपये दूँगा",
        "audio_e2e_spouse.wav": "मैं उनकी पत्नी हूँ वो घर पे नहीं हैं",
        "audio_e2e_correction.wav": "नहीं एक हजार पचास रुपये",
    }


def test_all_prerecorded_fixtures_are_real_pcm16_wav_files() -> None:
    for case in AUDIO_CASES:
        pcm = _load_pcm16(case.wav_path)
        assert len(pcm) > 3_200
        with wave.open(str(case.wav_path), "rb") as recording:
            assert (
                recording.getnchannels(),
                recording.getsampwidth(),
                recording.getframerate(),
            ) == (1, 2, 16_000)


def test_audio_amount_parser_accepts_only_reviewed_vectors() -> None:
    assert parse_audio_amount("मैं शुक्रवार को पंद्रह सौ रुपये दूँगा") == 150_000
    assert parse_audio_amount("नहीं एक हजार पचास रुपये") == 105_000


def test_matrix_wrapper_derives_all_thirteen_results() -> None:
    results = run_matrix()

    assert len(results) == 13
    assert all(result.passed for result in results)
    assert all(result.tier is EvidenceTier.MATRIX for result in results)


def test_audio_cases_run_real_controller_boundaries_after_transcription() -> None:
    transcripts = _fixture_transcripts()

    async def transcribe(path: Path) -> str:
        return transcripts[path.name]

    results = asyncio.run(run_audio_cases(transcribe=transcribe))

    assert len(results) == 3
    assert all(result.passed for result in results)
    assert all(result.tier is EvidenceTier.AUDIO for result in results)
    assert all("prerecorded-wav" in result.input_label for result in results)
    assert all("synthetic-hi-IN" in result.input_label for result in results)


def test_audio_failure_is_visible_and_contains_no_raw_exception() -> None:
    async def fail(_: Path) -> str:
        raise RuntimeError("private or dependency detail")

    results = asyncio.run(run_audio_cases(transcribe=fail))

    assert all(not result.passed for result in results)
    assert all(result.detail == "seq: [] error=RuntimeError" for result in results)
    assert "private or dependency detail" not in repr(results)


def test_artifact_separates_offline_matrix_from_real_stt_audio() -> None:
    audio = tuple(
        CaseResult(
            case.case_id,
            case.name,
            EvidenceTier.AUDIO,
            True,
            "prerecorded-wav source:synthetic-hi-IN",
        )
        for case in AUDIO_CASES
    )
    artifact = render_artifact(
        _matrix(),
        audio,
        timestamp=datetime(2026, 7, 26, 15, 42, 7, tzinfo=IST),
        build_id="abc1234",
    )

    assert artifact.startswith("=== VACHAN EVIDENCE RUN ===")
    assert "ts: 2026-07-26T15:42:07+05:30" in artifact
    assert "transport: streaming_pcm16_ws" in artifact
    assert "build: abc1234" in artifact
    assert "matrix (offline): 13/13" in artifact
    assert "audio e2e (real STT): 3/3" in artifact
    assert artifact.count("input: prerecorded-wav") == 3
    assert artifact.endswith("score: 16/16\n")


def test_generate_evidence_writes_current_derived_artifact_and_zero_exit(
    tmp_path: Path,
) -> None:
    transcripts = _fixture_transcripts()

    async def transcribe(path: Path) -> str:
        return transcripts[path.name]

    artifact_path = tmp_path / "evidence.txt"
    exit_code, artifact = asyncio.run(
        generate_evidence(
            artifact_path=artifact_path,
            matrix_runner=_matrix,
            transcribe=transcribe,
            now=lambda: datetime(2026, 7, 26, 15, 42, 7, tzinfo=IST),
        )
    )

    assert exit_code == 0
    assert artifact_path.read_text(encoding="utf-8") == artifact
    assert "score: 16/16" in artifact


def test_any_failure_forces_nonzero_exit_and_preserves_diagnostic(
    tmp_path: Path,
) -> None:
    failed = list(_matrix())
    failed[8] = CaseResult(
        "09",
        "guard-block",
        EvidenceTier.MATRIX,
        False,
        "typed-script",
        'seq: [{"seq":14,"type":"OUTPUT_BLOCKED"}]',
    )
    transcripts = _fixture_transcripts()

    async def transcribe(path: Path) -> str:
        return transcripts[path.name]

    exit_code, artifact = asyncio.run(
        generate_evidence(
            artifact_path=tmp_path / "evidence.txt",
            matrix_runner=lambda: failed,
            transcribe=transcribe,
        )
    )

    assert exit_code == 1
    assert "09  guard-block" in artifact
    assert "FAIL" in artifact
    assert '"type":"OUTPUT_BLOCKED"' in artifact
