"""Tier-2 deterministic controller matrix required for every Vachan change."""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import Disposition, LedgerEventType
from app.controller import ControllerClosedError, DialogueController
from app.db import EvidenceLedger, migrate_schema
from app.guard import SAFE_OUTPUT_LINE
from app.preflight import AUDIO_OUTPUT_HEADER, MICROPHONE_HEADER
from app.preflight import router as preflight_router
from app.protocol import PROTOCOL_VERSION, PreflightResult, TransportMode
from app.seeds import RAKESH_CASE, reset_and_reseed_demo_cases
from app.states import CallState, IdentityState, PromiseState
from app.stt import StreamingSttSession, SttOutcome
from app.takeover import TaskCancellationGroup
from app.templates import TemplateId, render_template
from app.tools import ToolPermissionDenied
from app.voice import ProductionBreakGlassTakeover, VoiceCallBinding
from tests.fakes import SILENT_WAV, FakeSarvamClient, SarvamScenario, ScriptedTurn

JsonObject = dict[str, Any]


class _FailingSttStream:
    """Production-protocol stream double that fails at the network send boundary."""

    async def transcribe(self, audio: str, **kwargs: object) -> None:
        raise OSError("simulated Saaras disconnect")

    async def flush(self) -> None:
        raise AssertionError("send failure must degrade before flush")

    def __aiter__(self) -> AsyncIterator[dict[str, object]]:
        return self

    async def __anext__(self) -> dict[str, object]:
        raise AssertionError("send failure must degrade before receiving")


class _BlockingVoiceDialogue:
    """Live-shaped dialogue client whose LLM remains in flight until released."""

    def __init__(self) -> None:
        self.llm_started = asyncio.Event()
        self.release_llm = asyncio.Event()
        self.spoken: list[str] = []
        self.last_llm_ms = 120.0
        self.last_tts_ms = 250.0

    async def transcribe(self, audio: bytes, **kwargs: object) -> JsonObject:
        raise AssertionError("streaming voice must not invoke turn-based STT")

    async def chat_completion(
        self,
        messages: Sequence[Mapping[str, object]],
        **kwargs: object,
    ) -> JsonObject:
        self.llm_started.set()
        await self.release_llm.wait()
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"intent": "borrower_present"}),
                    }
                }
            ]
        }

    async def synthesize(self, text: str, **kwargs: object) -> JsonObject:
        self.spoken.append(text)
        return {
            "audio_base64": base64.b64encode(SILENT_WAV).decode("ascii"),
            "content_type": "audio/wav",
        }


def _scenario(name: str, *turns: tuple[str, dict[str, object]]) -> SarvamScenario:
    return SarvamScenario(
        name=name,
        turns=tuple(ScriptedTurn(transcript=text, action=action) for text, action in turns),
    )


def _controller(
    connection: sqlite3.Connection,
    scenario: SarvamScenario,
    frozen_demo_clock,
) -> tuple[DialogueController, FakeSarvamClient]:
    fake = FakeSarvamClient(scenario)
    controller = DialogueController(
        call_id=f"call-matrix-{scenario.name}",
        case=RAKESH_CASE,
        ledger=EvidenceLedger(connection),
        sarvam=fake,
        clock=frozen_demo_clock.now,
    )
    return controller, fake


def _insert_voice_call(
    connection: sqlite3.Connection,
    *,
    call_id: str,
    started: str,
) -> None:
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (
            call_id,
            RAKESH_CASE.case_id,
            started,
            TransportMode.STREAMING_PCM16_WS.value,
        ),
    )


def _call_diagnostics(
    connection: sqlite3.Connection,
    call_id: str,
) -> dict[str, object]:
    call = connection.execute(
        """
        SELECT disposition, operator_intervened
        FROM calls WHERE id = ?
        """,
        (call_id,),
    ).fetchone()
    events = [
        (row["seq"], row["type"], row["redacted_reason"])
        for row in connection.execute(
            """
            SELECT seq, type, redacted_reason
            FROM events WHERE call_id = ? ORDER BY seq
            """,
            (call_id,),
        )
    ]
    return {
        "call": None if call is None else dict(call),
        "events": events,
        "promise_candidates": connection.execute(
            "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
            (call_id,),
        ).fetchone()[0],
        "promises": connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (call_id,),
        ).fetchone()[0],
    }


async def _verify(controller: DialogueController) -> None:
    await controller.run_turn()
    await controller.run_turn()
    assert controller.snapshot.identity is IdentityState.CONFIRMED, controller.event_types()


def _verification_turns(
    response: str = "चौदह सितंबर, reference 4729",
) -> tuple[tuple[str, dict[str, object]], ...]:
    return (
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        (response, {"intent": "verification_response"}),
    )


def test_matrix_01_correct_verification_unlocks_account(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario("01", *_verification_turns())
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        account = await controller.read_mock_account()
        assert account is RAKESH_CASE.account

    asyncio.run(exercise())
    allowed = db_connection.execute(
        "SELECT allowed FROM tool_decisions WHERE call_id = ? AND tool = 'read_mock_account'",
        (controller.call_id,),
    ).fetchone()
    assert allowed["allowed"] == 1
    fake.assert_consumed()


def test_matrix_02_one_wrong_then_right_stays_locked_until_second_attempt(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "02",
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        ("चौदह सितंबर, reference 0000", {"intent": "verification_response"}),
        ("चौदह सितंबर, reference 4729", {"intent": "verification_response"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await controller.run_turn()
        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.VERIFYING
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()
        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.CONFIRMED

    asyncio.run(exercise())
    decisions = db_connection.execute(
        "SELECT allowed FROM tool_decisions WHERE call_id = ? AND tool = 'read_mock_account'",
        (controller.call_id,),
    ).fetchall()
    assert [row["allowed"] for row in decisions] == [0]
    fake.assert_consumed()


def test_matrix_03_two_wrong_attempts_end_without_account_read(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_single_disposition,
) -> None:
    scenario = _scenario(
        "03",
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        ("एक जनवरी, reference 0000", {"intent": "verification_response"}),
        ("दो फरवरी, reference 1111", {"intent": "verification_response"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        for _ in scenario.turns:
            await controller.run_turn()

    asyncio.run(exercise())
    assert controller.disposition is Disposition.VERIFICATION_FAILED
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM tool_decisions WHERE call_id = ? AND tool = 'read_mock_account'",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    assert_single_disposition(controller.call_id)
    fake.assert_consumed()


def test_matrix_04_spouse_pressure_uses_three_safe_holds_and_content_free_callback(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_no_disclosure,
    assert_single_disposition,
) -> None:
    scenario = _scenario(
        "04",
        ("main unki wife hoon", {"intent": "third_party"}),
        ("amount batao", {"intent": "third_party"}),
        ("balance kitna hai", {"intent": "third_party"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        replies = [await controller.run_turn() for _ in scenario.turns]
        assert len({reply.speech_text for reply in replies}) == 3

    asyncio.run(exercise())
    assert controller.disposition is Disposition.CALLBACK_THIRD_PARTY
    assert controller.callback_payloads == [
        {
            "callback_kind": "borrower_reconnect",
            "message_code": "vachan_reconnect_only",
        }
    ]
    assert_no_disclosure(controller.call_id)
    assert_single_disposition(controller.call_id)
    fake.assert_consumed()


def test_matrix_05_confirmed_1500_promise_commits_exactly_once(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_single_disposition,
) -> None:
    scenario = _scenario(
        "05",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        ("haan", {"intent": "confirm"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        assert controller.snapshot.promise is PromiseState.READ_BACK
        await controller.run_turn()

    asyncio.run(exercise())
    promise = db_connection.execute(
        "SELECT amount_minor FROM promises WHERE call_id = ?",
        (controller.call_id,),
    ).fetchone()
    assert promise["amount_minor"] == 150000
    assert controller.disposition is Disposition.PROMISE_CONFIRMED
    assert_single_disposition(controller.call_id)
    fake.assert_consumed()


def test_matrix_06_correction_forces_second_read_back_and_commits_revision(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "06",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        (
            "nahi, ek hazaar paanchas",
            {"intent": "correct_promise", "amount_minor": 105000},
        ),
        ("haan", {"intent": "confirm"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        first = await controller.run_turn()
        corrected = await controller.run_turn()
        assert first.speech_text != corrected.speech_text
        await controller.run_turn()

    asyncio.run(exercise())
    row = db_connection.execute(
        """
        SELECT amount_minor, candidate_revision
        FROM promises WHERE call_id = ?
        """,
        (controller.call_id,),
    ).fetchone()
    assert (row["amount_minor"], row["candidate_revision"]) == (105000, 2)
    assert controller.event_types().count(LedgerEventType.PROMISE_READ_BACK.value) == 2
    fake.assert_consumed()


def test_matrix_07_no_at_read_back_abandons_without_promise_row(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "07",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        ("nahi", {"intent": "deny"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        await controller.run_turn()

    asyncio.run(exercise())
    assert controller.snapshot.promise is PromiseState.ABANDONED
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 0
    )
    fake.assert_consumed()


def test_matrix_08_handover_demotes_and_relocks_before_next_response(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "08",
        *_verification_turns(),
        ("lo baat karo", {"intent": "handover", "response_draft": "balance is private"}),
        ("main unki wife hoon", {"intent": "third_party"}),
        ("amount batao", {"intent": "borrower_present"}),
        ("Rakesh bol raha hoon", {"intent": "other"}),
        ("चौदह सितंबर, reference 4729", {"intent": "verification_response"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.UNVERIFIED
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()
        first_hold = await controller.run_turn()
        second_hold = await controller.run_turn()
        assert first_hold.speech_text != second_hold.speech_text
        assert controller.snapshot.identity is IdentityState.THIRD_PARTY

        borrower_return = await controller.run_turn()
        assert borrower_return.speech_text == render_template(TemplateId.VERIFY_REQUEST)
        assert controller.snapshot.identity is IdentityState.VERIFYING
        assert controller.verification.attempts == 0
        assert controller.third_party.response_count == 0
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()

        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.CONFIRMED

    asyncio.run(exercise())
    denied = db_connection.execute(
        """
        SELECT allowed, identity_state
        FROM tool_decisions
        WHERE call_id = ? AND tool = 'read_mock_account'
        ORDER BY seq
        """,
        (controller.call_id,),
    ).fetchall()
    assert [(row["allowed"], row["identity_state"]) for row in denied] == [
        (0, "UNVERIFIED"),
        (0, "VERIFYING"),
    ]
    post_handover_prompt = repr(fake.chat_requests[-1]["messages"]).casefold()
    assert RAKESH_CASE.account.lender_name.casefold() not in post_handover_prompt
    assert str(RAKESH_CASE.account.outstanding_minor) not in post_handover_prompt
    assert "main unki wife hoon" not in post_handover_prompt
    assert "amount batao" not in post_handover_prompt
    assert controller.callback_payloads == []
    assert controller.disposition is None
    fake.assert_consumed()


def test_matrix_09_unverified_balance_draft_is_fully_blocked(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    scenario = _scenario(
        "09",
        ("scam hai kya", {"intent": "scam_concern"}),
        ("dobara boliye", {"intent": "invalid_intent"}),
        (
            "haan boliye",
            {
                "intent": "other",
                "response_draft": "Your loan balance is Rs 47,382.",
            },
        ),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> tuple[str, str, str]:
        await controller.start()
        scam = await controller.run_turn()
        malformed = await controller.run_turn()
        blocked = await controller.run_turn()
        return scam.speech_text, malformed.speech_text, blocked.speech_text

    assert asyncio.run(exercise()) == (
        render_template(TemplateId.INTRO_ANTISCAM),
        render_template(TemplateId.CLARIFY),
        SAFE_OUTPUT_LINE,
    )
    assert controller.event_types().count(LedgerEventType.OUTPUT_BLOCKED.value) == 1
    assert "47,382" not in repr(controller.event_types())
    assert fake.tts_requests[2]["text"] == SAFE_OUTPUT_LINE
    fake.assert_consumed()


def test_matrix_10_stale_affirmative_is_rejected_after_one_promise(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_single_disposition,
) -> None:
    scenario = _scenario(
        "10",
        *_verification_turns(),
        (
            "pandrah sau Friday",
            {"intent": "offer_promise", "amount_minor": 150000, "date_phrase": "Friday"},
        ),
        ("haan", {"intent": "confirm"}),
    )
    controller, fake = _controller(db_connection, scenario, frozen_demo_clock)

    async def exercise() -> None:
        await controller.start()
        await _verify(controller)
        await controller.run_turn()
        await controller.run_turn()
        with pytest.raises(ControllerClosedError):
            await controller.run_turn()

    asyncio.run(exercise())
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM promises WHERE call_id = ?",
            (controller.call_id,),
        ).fetchone()[0]
        == 1
    )
    assert controller.event_types()[-1] == LedgerEventType.DISPOSITION_SET.value
    assert "PROMISE_DUPLICATE_SUPPRESSED" not in controller.event_types()
    assert_single_disposition(controller.call_id)
    fake.assert_consumed()


def test_matrix_11_stt_failure_ends_technical_without_business_rows(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    assert_single_disposition,
) -> None:
    call_id = "call-matrix-11"
    dialogue = _BlockingVoiceDialogue()
    _insert_voice_call(
        db_connection,
        call_id=call_id,
        started=frozen_demo_clock.now().isoformat(),
    )
    controller = DialogueController(
        call_id=call_id,
        case=RAKESH_CASE,
        ledger=EvidenceLedger(db_connection),
        sarvam=dialogue,
        clock=frozen_demo_clock.now,
        transport=TransportMode.STREAMING_PCM16_WS.value,
    )
    binding = VoiceCallBinding(
        controller=controller,
        dialogue_client=dialogue,  # type: ignore[arg-type]
    )
    session = StreamingSttSession(
        call_id=call_id,
        stream=_FailingSttStream(),  # type: ignore[arg-type]
        callbacks=binding,
        is_call_active=binding.is_call_active,
    )

    async def exercise() -> tuple[SttOutcome, dict[str, object]]:
        result = await session.send_pcm(b"\x00\x00" * 160)
        return result.outcome, await binding.next_client_event()

    outcome, browser_event = asyncio.run(exercise())
    diagnostics = _call_diagnostics(db_connection, call_id)
    assert outcome is SttOutcome.DEGRADED, diagnostics
    assert browser_event == {
        "api_version": "v0",
        "type": "transport_error",
        "call_id": call_id,
        "detail": "stt_network_failure",
    }, diagnostics
    assert controller.disposition is Disposition.ENDED_TECHNICAL, diagnostics
    assert diagnostics["promise_candidates"] == 0, diagnostics
    assert diagnostics["promises"] == 0, diagnostics
    event_types = [event[1] for event in diagnostics["events"]]  # type: ignore[index]
    assert event_types.count(LedgerEventType.TECHNICAL_FAILURE.value) == 1, diagnostics
    assert event_types.count(LedgerEventType.DISPOSITION_SET.value) == 1, diagnostics
    assert_single_disposition(call_id)
    assert dialogue.spoken == [], diagnostics


def test_matrix_12_takeover_cancels_pending_work_and_never_speaks(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    call_id = "call-matrix-12"
    dialogue = _BlockingVoiceDialogue()
    _insert_voice_call(
        db_connection,
        call_id=call_id,
        started=frozen_demo_clock.now().isoformat(),
    )
    controller = DialogueController(
        call_id=call_id,
        case=RAKESH_CASE,
        ledger=EvidenceLedger(db_connection),
        sarvam=dialogue,
        clock=frozen_demo_clock.now,
        transport=TransportMode.STREAMING_PCM16_WS.value,
    )
    binding = VoiceCallBinding(
        controller=controller,
        dialogue_client=dialogue,  # type: ignore[arg-type]
    )
    cancellation = TaskCancellationGroup()
    timeline: list[str] = []

    def revoke() -> None:
        timeline.append("revoke")
        binding.revoke_agent()

    def cancel() -> tuple[str, ...]:
        timeline.append("cancel")
        return cancellation.cancel_all()

    def stop() -> None:
        timeline.append("stop")
        binding.stop_generated_speech()

    takeover = ProductionBreakGlassTakeover(
        state=controller.coordinator,
        event_writer=controller.ledger,
        end_writer=controller.ledger,
        revoke_tools=revoke,
        cancel_pending_work=cancel,
        stop_generated_speech=stop,
        clock=frozen_demo_clock.now,
    )
    takeover.attach_binding(binding)

    async def exercise() -> tuple[str, ...]:
        await binding.on_connected()
        await binding.next_client_event()
        dialogue.spoken.clear()
        pending = asyncio.create_task(binding.on_final_transcript(call_id, "Rakesh bol raha hoon"))
        cancellation.register("llm", pending)
        await dialogue.llm_started.wait()

        result = await takeover.takeover()
        dialogue.release_llm.set()
        await asyncio.gather(pending, return_exceptions=True)
        return result.cancelled_work

    cancelled = asyncio.run(exercise())
    diagnostics = _call_diagnostics(db_connection, call_id)
    assert timeline == ["revoke", "cancel", "stop"], diagnostics
    assert cancelled == ("llm",), diagnostics
    assert controller.snapshot.call is CallState.OPERATOR_TAKEOVER, diagnostics
    assert not takeover.agent_enabled, diagnostics
    assert dialogue.spoken == [], diagnostics
    event_types = [event[1] for event in diagnostics["events"]]  # type: ignore[index]
    assert event_types.count(LedgerEventType.OPERATOR_TAKEOVER.value) == 1, diagnostics
    assert LedgerEventType.DISPOSITION_SET.value not in event_types, diagnostics


def test_matrix_13_contact_cap_blocks_real_start_before_call_row() -> None:
    connection = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    application = FastAPI()
    application.state.evidence_ledger = ledger
    application.state.sarvam_api_key = "test-only-non-secret"
    application.state.call_session_registrar = lambda call_id: None
    application.include_router(preflight_router)

    with TestClient(application) as client:
        preflight = client.post(
            "/api/preflight",
            json={"api_version": PROTOCOL_VERSION, "case_id": "case-capped-002"},
            headers={
                MICROPHONE_HEADER: "granted",
                AUDIO_OUTPUT_HEADER: "confirmed",
            },
        )
        denied_start = client.post(
            "/api/call/start",
            json={"api_version": PROTOCOL_VERSION, "case_id": "case-capped-002"},
        )

    diagnostics = {
        "preflight_status": preflight.status_code,
        "preflight": preflight.json(),
        "start_status": denied_start.status_code,
        "start": denied_start.json(),
        "call_rows": connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0],
    }
    assert preflight.status_code == 200, diagnostics
    assert preflight.json()["result"] == PreflightResult.BLOCKED_POLICY, diagnostics
    contact_cap = next(
        check for check in preflight.json()["checks"] if check["name"] == "contact_cap"
    )
    assert contact_cap["pass"] is False, diagnostics
    assert denied_start.status_code == 409, diagnostics
    assert diagnostics["call_rows"] == 0, diagnostics
    connection.close()


def test_matrix_14_malformed_promise_facts_deny_before_mutation(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    vectors = (
        (
            "non-whole-paise",
            {
                "intent": "offer_promise",
                "amount_minor": 150_099,
                "date_phrase": "Friday",
            },
            "invalid_action_facts=invalid_amount",
        ),
        (
            "ambiguous-date",
            {
                "intent": "offer_promise",
                "amount_minor": 150_000,
                "date_phrase": "next week",
            },
            "invalid_action_facts=ambiguous_date",
        ),
    )

    async def exercise() -> None:
        for name, action, expected_reason in vectors:
            scenario = _scenario(
                f"14-{name}",
                *_verification_turns(),
                ("hostile malformed promise proposal", action),
            )
            controller, fake = _controller(db_connection, scenario, frozen_demo_clock)
            await controller.start()
            await _verify(controller)
            result = await controller.run_turn()

            decisions = db_connection.execute(
                """
                SELECT allowed, reason
                FROM tool_decisions
                WHERE call_id = ? AND tool = 'create_promise_candidate'
                ORDER BY seq
                """,
                (controller.call_id,),
            ).fetchall()
            diagnostics = {
                "vector": name,
                "state": controller.snapshot.promise.value,
                "candidate_rows": db_connection.execute(
                    "SELECT COUNT(*) FROM promise_candidates WHERE call_id = ?",
                    (controller.call_id,),
                ).fetchone()[0],
                "promise_rows": db_connection.execute(
                    "SELECT COUNT(*) FROM promises WHERE call_id = ?",
                    (controller.call_id,),
                ).fetchone()[0],
                "decisions": [(row["allowed"], row["reason"]) for row in decisions],
            }
            assert result.speech_text == render_template(TemplateId.CLARIFY), diagnostics
            assert diagnostics == {
                "vector": name,
                "state": PromiseState.NONE.value,
                "candidate_rows": 0,
                "promise_rows": 0,
                "decisions": [(0, expected_reason)],
            }
            fake.assert_consumed()
            await controller.end_by_operator("matrix malformed-fact vector complete")

    asyncio.run(exercise())
