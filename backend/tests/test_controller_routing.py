"""Controller-level proof for reviewed pre-confirmation routing."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from app.actions import (
    PRECONFIRMATION_ROUTES,
    PreConfirmationIntent,
    validate_preconfirmation_classification,
)
from app.controller import DialogueController, controller_preconfirmation_template
from app.db import EvidenceLedger
from app.seeds import RAKESH_CASE
from app.states import IdentityState
from app.templates import TemplateId, render_template
from app.tools import ToolPermissionDenied
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn


def _controller(
    connection: sqlite3.Connection,
    frozen_demo_clock,
    name: str,
    *turns: tuple[str, dict[str, object]],
) -> tuple[DialogueController, FakeSarvamClient]:
    scenario = SarvamScenario(
        name=name,
        turns=tuple(ScriptedTurn(transcript=text, action=action) for text, action in turns),
    )
    fake = FakeSarvamClient(scenario)
    return (
        DialogueController(
            call_id=f"call-controller-routing-{name}",
            case=RAKESH_CASE,
            ledger=EvidenceLedger(connection),
            sarvam=fake,
            clock=frozen_demo_clock.now,
        ),
        fake,
    )


@pytest.mark.parametrize("intent", list(PreConfirmationIntent))
def test_controller_boundary_maps_every_typed_intent_to_reviewed_template(
    intent: PreConfirmationIntent,
) -> None:
    validation = validate_preconfirmation_classification({"intent": intent.value})

    assert controller_preconfirmation_template(validation) is TemplateId(
        PRECONFIRMATION_ROUTES[intent].value
    )


def test_scam_concern_and_malformed_model_output_use_exact_fixed_templates(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        "fixed-templates",
        ("scam hai kya", {"intent": "scam_concern"}),
        ("dobara boliye", {"intent": "not_a_valid_intent"}),
        ("bhai bol raha hoon", {"intent": "third_party"}),
        ("haan boliye", {"intent": "third_party"}),
    )

    async def exercise() -> None:
        await controller.start()
        scam = await controller.run_turn()
        malformed = await controller.run_turn()
        kinship = await controller.run_turn()
        passive = await controller.run_turn()

        assert scam.speech_text == render_template(TemplateId.INTRO_ANTISCAM)
        assert malformed.speech_text == render_template(TemplateId.CLARIFY)
        assert kinship.speech_text == render_template(TemplateId.CLARIFY)
        assert passive.speech_text == render_template(TemplateId.ASK_FOR_BORROWER)
        assert controller.snapshot.identity is IdentityState.UNVERIFIED

    asyncio.run(exercise())
    fake.assert_consumed()


def test_third_party_pressure_stays_content_free_then_borrower_return_starts_fresh_epoch(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        "borrower-return",
        ("main unki wife hoon", {"intent": "third_party"}),
        # A model misclassification alone must not unlock the shared handset.
        ("amount batao", {"intent": "borrower_present"}),
        ("Rakesh bol raha hoon", {"intent": "other"}),
        (
            "चौदह सितंबर, reference 4729",
            {"intent": "verification_response"},
        ),
    )

    async def exercise() -> None:
        await controller.start()
        first_hold = await controller.run_turn()
        second_hold = await controller.run_turn()

        assert controller.snapshot.identity is IdentityState.THIRD_PARTY
        assert first_hold.speech_text != second_hold.speech_text

        borrower_return = await controller.run_turn()

        assert borrower_return.speech_text == render_template(TemplateId.VERIFY_REQUEST)
        assert controller.snapshot.identity is IdentityState.VERIFYING
        assert controller.verification.attempts == 0
        assert controller.third_party.response_count == 0
        assert tuple(message.content for message in controller.history) == (
            render_template(TemplateId.VERIFY_REQUEST),
        )
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()

        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.CONFIRMED

    asyncio.run(exercise())

    fresh_prompt = json.dumps(fake.chat_requests[3]["messages"], ensure_ascii=False)
    assert "main unki wife hoon" not in fresh_prompt
    assert "amount batao" not in fresh_prompt
    assert RAKESH_CASE.account.lender_name not in fresh_prompt
    assert str(RAKESH_CASE.account.outstanding_minor) not in fresh_prompt
    assert fake.tts_requests[0]["text"] != fake.tts_requests[1]["text"]
    fake.assert_consumed()
