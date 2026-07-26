"""Production voice binding tests across controller, evidence, and browser audio."""

from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.controller import DialogueController, _action_payload
from app.db import EvidenceLedger
from app.llm import LLMUnavailable
from app.protocol import TransportMode
from app.seeds import RAKESH_CASE
from app.states import IdentityState, PromiseState
from app.templates import TemplateId, render_template
from app.voice import ProductionBreakGlassTakeover, VoiceCallBinding
from tests.fakes import SILENT_WAV

JsonObject = dict[str, Any]


def test_sarvam_markdown_fenced_action_is_parsed_without_exposing_prose() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        "```json\n"
                        '{"intent":"offer_promise","amount_minor":150000,'
                        '"date_phrase":"Friday","response_draft":""}\n'
                        "```"
                    )
                }
            }
        ]
    }

    assert _action_payload(response) == {
        "intent": "offer_promise",
        "amount_minor": 150_000,
        "date_phrase": "Friday",
        "response_draft": "",
    }


@dataclass(slots=True)
class FakeLiveDialogue:
    """Streaming-compatible fake: STT is external, chat/TTS remain scripted."""

    actions: list[dict[str, object] | Exception]
    last_llm_ms: float = 120.0
    last_tts_ms: float = 250.0
    chat_messages: list[tuple[dict[str, object], ...]] = field(default_factory=list)
    spoken: list[str] = field(default_factory=list)

    async def transcribe(self, audio: bytes, **kwargs: object) -> JsonObject:
        raise AssertionError("streaming voice binding must not invoke a second STT request")

    async def chat_completion(
        self,
        messages: Sequence[Mapping[str, object]],
        **kwargs: object,
    ) -> JsonObject:
        self.chat_messages.append(tuple(dict(message) for message in messages))
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(action),
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


def _existing_voice_call(
    connection: sqlite3.Connection,
    *,
    call_id: str,
    frozen_demo_clock,
) -> tuple[VoiceCallBinding, FakeLiveDialogue]:
    connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (
            call_id,
            RAKESH_CASE.case_id,
            frozen_demo_clock.now().isoformat(),
            TransportMode.STREAMING_PCM16_WS.value,
        ),
    )
    dialogue = FakeLiveDialogue(
        actions=[
            {"intent": "borrower_present"},
            {"intent": "verification_response"},
            {
                "intent": "offer_promise",
                "amount_minor": 150_000,
                "date_phrase": "Friday",
            },
        ]
    )
    controller = DialogueController(
        call_id=call_id,
        case=RAKESH_CASE,
        ledger=EvidenceLedger(connection),
        sarvam=dialogue,
        clock=frozen_demo_clock.now,
        transport=TransportMode.STREAMING_PCM16_WS.value,
    )
    return (
        VoiceCallBinding(
            controller=controller,
            dialogue_client=dialogue,  # type: ignore[arg-type]
        ),
        dialogue,
    )


def test_live_binding_reaches_uncommitted_read_back_with_timing_evidence(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, dialogue = _existing_voice_call(
        db_connection,
        call_id="call-live-001",
        frozen_demo_clock=frozen_demo_clock,
    )

    async def exercise() -> None:
        await binding.on_connected()
        opening = await binding.next_client_event()
        assert opening["type"] == "agent_audio"
        assert opening["kind"] == "opening"
        assert base64.b64decode(str(opening["audio_base64"])) == SILENT_WAV
        opening_timings = opening["timings"]
        assert isinstance(opening_timings, dict)
        assert opening_timings == {
            "stt_ms": 0,
            "llm_ms": 0,
            "tts_ms": 250,
            "total_ms": 250,
        }

        turns = (
            "Rakesh bol raha hoon",
            "चौदह सितंबर, reference 4729",
            "pandrah sau rupaye Friday ko de dunga",
        )
        for transcript in turns:
            await binding.on_stt_timing(binding.call_id, 35.4)
            await binding.on_final_transcript(binding.call_id, transcript)
            event = await binding.next_client_event()
            assert event["type"] == "agent_audio"
            assert event["transcript"] == transcript
            timings = event["timings"]
            assert isinstance(timings, dict)
            assert timings["stt_ms"] == 35
            assert timings["llm_ms"] == 120
            assert timings["tts_ms"] == 250
            assert int(timings["total_ms"]) >= 405

    asyncio.run(exercise())

    assert binding.controller.snapshot.identity is IdentityState.CONFIRMED
    assert binding.controller.snapshot.promise is PromiseState.READ_BACK
    assert db_connection.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1
    assert db_connection.execute("SELECT COUNT(*) FROM promise_candidates").fetchone()[0] == 1
    assert db_connection.execute("SELECT COUNT(*) FROM promises").fetchone()[0] == 0
    timing_rows = db_connection.execute(
        """
        SELECT redacted_reason FROM events
        WHERE call_id = ? AND type = 'TURN_TIMING'
        ORDER BY seq
        """,
        (binding.call_id,),
    ).fetchall()
    assert len(timing_rows) == 3
    assert all("stt_ms=35;llm_ms=120;tts_ms=250;total_ms=" in row[0] for row in timing_rows)
    assert len(dialogue.chat_messages) == 3
    assert len(dialogue.spoken) == 4


def test_voice_binding_drops_stale_transcript_after_call_ends(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, dialogue = _existing_voice_call(
        db_connection,
        call_id="call-live-stale",
        frozen_demo_clock=frozen_demo_clock,
    )

    async def exercise() -> None:
        await binding.on_connected()
        await binding.next_client_event()
        await binding.on_recovery_prompt(
            binding.call_id,
            render_template(TemplateId.STT_RECOVERY),
        )
        recovery = await binding.next_client_event()
        assert recovery["type"] == "agent_audio"
        assert recovery["kind"] == "recovery"
        timings = recovery["timings"]
        assert isinstance(timings, dict)
        assert timings == {
            "stt_ms": 0,
            "llm_ms": 0,
            "tts_ms": 250,
            "total_ms": 250,
        }
        db_connection.execute(
            """
            UPDATE calls
            SET ended = ?, disposition = 'ENDED_OPERATOR'
            WHERE id = ?
            """,
            (frozen_demo_clock.now().isoformat(), binding.call_id),
        )
        await binding.on_final_transcript(binding.call_id, "Rakesh bol raha hoon")

    asyncio.run(exercise())

    assert dialogue.chat_messages == []
    assert dialogue.spoken and len(dialogue.spoken) == 2
    assert (
        db_connection.execute(
            "SELECT COUNT(*) FROM events WHERE call_id = ? AND type = 'TURN_TIMING'",
            (binding.call_id,),
        ).fetchone()[0]
        == 0
    )


def test_recovery_prompt_allows_next_preconfirmation_turn(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, dialogue = _existing_voice_call(
        db_connection,
        call_id="call-live-recovery-continues",
        frozen_demo_clock=frozen_demo_clock,
    )

    async def exercise() -> None:
        await binding.on_connected()
        await binding.next_client_event()
        await binding.on_recovery_prompt(
            binding.call_id,
            render_template(TemplateId.STT_RECOVERY),
        )
        recovery = await binding.next_client_event()
        assert recovery["kind"] == "recovery"

        await binding.on_final_transcript(binding.call_id, "Rakesh bol raha hoon")
        next_turn = await binding.next_client_event()
        assert next_turn["kind"] == "turn"
        assert next_turn["transcript"] == "Rakesh bol raha hoon"

    asyncio.run(exercise())

    assert len(dialogue.chat_messages) == 1
    assert dialogue.spoken == [
        render_template(TemplateId.INTRO_ANTISCAM),
        render_template(TemplateId.STT_RECOVERY),
        render_template(TemplateId.VERIFY_REQUEST),
    ]


def test_unreviewed_recovery_fails_closed_before_tts(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, dialogue = _existing_voice_call(
        db_connection,
        call_id="call-live-unreviewed-recovery",
        frozen_demo_clock=frozen_demo_clock,
    )

    async def exercise() -> None:
        await binding.on_connected()
        await binding.next_client_event()
        await binding.on_recovery_prompt(binding.call_id, "arbitrary operational prose")

        assert await binding.next_client_event() == {
            "type": "call_degraded",
            "call_id": binding.call_id,
            "reason": "backend_failure",
        }

    asyncio.run(exercise())

    assert dialogue.spoken == [render_template(TemplateId.INTRO_ANTISCAM)]
    disposition = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (binding.call_id,),
    ).fetchone()[0]
    assert disposition == "ENDED_TECHNICAL"


def test_voice_binding_drops_stale_transcript_after_synchronous_revocation(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, dialogue = _existing_voice_call(
        db_connection,
        call_id="call-live-revoked",
        frozen_demo_clock=frozen_demo_clock,
    )
    binding.revoke_agent()

    asyncio.run(binding.on_final_transcript(binding.call_id, "Rakesh bol raha hoon"))

    assert dialogue.chat_messages == []
    assert dialogue.spoken == []


def test_transport_failure_before_connect_ends_call_technical(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, dialogue = _existing_voice_call(
        db_connection,
        call_id="call-live-preconnect-failure",
        frozen_demo_clock=frozen_demo_clock,
    )

    async def exercise() -> None:
        await binding.on_degraded(binding.call_id, "stt_network_failure")
        assert await binding.next_client_event() == {
            "type": "call_degraded",
            "call_id": binding.call_id,
            "reason": "stt_network_failure",
        }

    asyncio.run(exercise())

    call = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (binding.call_id,),
    ).fetchone()
    assert call["disposition"] == "ENDED_TECHNICAL"
    assert binding.controller.snapshot.call.value == "ENDED"
    assert dialogue.chat_messages == []
    assert dialogue.spoken == []


def test_active_takeover_runs_safety_effects_without_awaiting_voice_lock(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, _ = _existing_voice_call(
        db_connection,
        call_id="call-live-active-takeover",
        frozen_demo_clock=frozen_demo_clock,
    )
    timeline: list[str] = []

    def revoke() -> None:
        binding.revoke_agent()
        timeline.append("revoke")

    def cancel() -> tuple[str, ...]:
        timeline.append("cancel")
        return ("active-turn",)

    def stop() -> None:
        binding.stop_generated_speech()
        timeline.append("stop")

    takeover = ProductionBreakGlassTakeover(
        state=binding.controller.coordinator,
        event_writer=binding.controller.ledger,
        end_writer=binding.controller.ledger,
        revoke_tools=revoke,
        cancel_pending_work=cancel,
        stop_generated_speech=stop,
        clock=frozen_demo_clock.now,
    )
    takeover.attach_binding(binding)

    async def forbidden_prepare() -> None:
        raise AssertionError("ACTIVE takeover must not await the voice turn lock")

    async def exercise() -> None:
        await binding.on_connected()
        await binding.next_client_event()
        binding.prepare_takeover = forbidden_prepare  # type: ignore[method-assign]
        await takeover.takeover()

    asyncio.run(exercise())

    assert timeline[:3] == ["revoke", "cancel", "stop"]
    assert binding.controller.snapshot.call.value == "OPERATOR_TAKEOVER"


def test_voice_binding_attributes_llm_failure_without_relabeling_it_as_stt(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, dialogue = _existing_voice_call(
        db_connection,
        call_id="call-live-llm-failure",
        frozen_demo_clock=frozen_demo_clock,
    )
    dialogue.actions[0] = LLMUnavailable("safe failure")

    async def exercise() -> None:
        await binding.on_connected()
        await binding.next_client_event()
        await binding.on_final_transcript(binding.call_id, "Rakesh bol raha hoon")
        degraded = await binding.next_client_event()
        assert degraded == {
            "type": "call_degraded",
            "call_id": binding.call_id,
            "reason": "llm_unavailable",
        }

    asyncio.run(exercise())

    call = db_connection.execute(
        "SELECT disposition FROM calls WHERE id = ?",
        (binding.call_id,),
    ).fetchone()
    assert call["disposition"] == "ENDED_TECHNICAL"
    reasons = [
        row["redacted_reason"]
        for row in db_connection.execute(
            "SELECT redacted_reason FROM events WHERE call_id = ? ORDER BY seq",
            (binding.call_id,),
        )
    ]
    assert "technical_failure:llm_unavailable" in reasons
    assert all("stt_network_failure" not in reason for reason in reasons)


def test_normal_operator_end_releases_the_case_for_a_fresh_call(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    binding, _ = _existing_voice_call(
        db_connection,
        call_id="call-live-normal-end",
        frozen_demo_clock=frozen_demo_clock,
    )

    async def exercise() -> None:
        await binding.on_connected()
        await binding.next_client_event()
        result = await binding.end_by_operator("Stopped before promise confirmation")
        assert result.call_id == binding.call_id
        assert result.disposition_seq > 0

    asyncio.run(exercise())

    ended = db_connection.execute(
        "SELECT disposition, operator_intervened FROM calls WHERE id = ?",
        (binding.call_id,),
    ).fetchone()
    assert dict(ended) == {
        "disposition": "ENDED_OPERATOR",
        "operator_intervened": 1,
    }
    db_connection.execute(
        """
        INSERT INTO calls (id, case_id, started, transport)
        VALUES (?, ?, ?, ?)
        """,
        (
            "call-live-after-normal-end",
            RAKESH_CASE.case_id,
            frozen_demo_clock.now().isoformat(),
            TransportMode.STREAMING_PCM16_WS.value,
        ),
    )
