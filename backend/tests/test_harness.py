"""Self-tests for the reusable deterministic controller harness."""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.actions import (
    PreConfirmationIntent,
    PreConfirmationTemplate,
    validate_preconfirmation_classification,
)
from app.contracts import Disposition, LedgerEventType, StateSnapshot
from app.db import SCHEMA_VERSION, EvidenceLedger
from app.seeds import DEMO_TIME_ANCHOR, RAKESH_CASE
from app.states import CallState, IdentityState, PromiseState
from tests.fakes import FakeSarvamClient, FrozenDemoClock, SarvamScenario

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
SHAPES_PATH = PROJECT_ROOT / "tests" / "fixtures" / "sarvam_api_shapes.json"
STT_CAPTURE_PATH = PROJECT_ROOT / "artifacts" / "sarvam_stt_smoke_response.json"
TTS_CAPTURE_PATH = PROJECT_ROOT / "artifacts" / "sarvam_tts_smoke_response.json"

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


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


def test_fake_envelopes_match_real_stt_and_tts_capture_shapes(
    fake_sarvam_factory,
    correct_verification_scenario: SarvamScenario,
) -> None:
    shapes = json.loads(SHAPES_PATH.read_text())
    live_stt = json.loads(STT_CAPTURE_PATH.read_text())
    live_tts = json.loads(TTS_CAPTURE_PATH.read_text())
    fake: FakeSarvamClient = fake_sarvam_factory(correct_verification_scenario)

    async def exercise() -> tuple[dict, dict]:
        stt = await fake.transcribe(b"synthetic wav")
        tts = await fake.synthesize("कृपया सत्यापन पूरा करें।")
        return stt, tts

    stt, tts = asyncio.run(exercise())
    expected_stt_keys = set(shapes["speech_to_text"]["response"]["required_keys"])
    expected_tts_keys = set(shapes["text_to_speech"]["response"]["required_keys"])
    assert set(live_stt) == expected_stt_keys
    assert set(stt) == expected_stt_keys
    assert set(live_tts) == expected_tts_keys
    assert set(tts) == expected_tts_keys
    assert isinstance(tts["audios"], list)
    assert base64.b64decode(tts["audios"][0]).startswith(b"RIFF")
    assert fake.captured_audio[0].startswith(b"RIFF")


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
    assert set(tts) == {"request_id", "audios"}
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
