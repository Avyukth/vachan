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
from app.guard import SAFE_OUTPUT_LINE
from app.seeds import CONTACT_CAPPED_CASE, RAKESH_CASE, MockCaseSeed
from app.states import IdentityState
from app.templates import TemplateId, is_bank_member, render_template
from app.tools import ToolPermissionDenied
from app.verification import (
    COMPLETE_VERIFICATION_INPUT_MARKER,
    INCOMPLETE_VERIFICATION_INPUT_MARKER,
)
from tests.fakes import FakeSarvamClient, SarvamScenario, ScriptedTurn


def _controller(
    connection: sqlite3.Connection,
    frozen_demo_clock,
    name: str,
    *turns: tuple[str, dict[str, object]],
    case: MockCaseSeed = RAKESH_CASE,
) -> tuple[DialogueController, FakeSarvamClient]:
    scenario = SarvamScenario(
        name=name,
        turns=tuple(ScriptedTurn(transcript=text, action=action) for text, action in turns),
    )
    fake = FakeSarvamClient(scenario)
    return (
        DialogueController(
            call_id=f"call-controller-routing-{name}",
            case=case,
            ledger=EvidenceLedger(connection),
            sarvam=fake,
            clock=frozen_demo_clock.now,
        ),
        fake,
    )


@pytest.mark.parametrize(
    ("case", "borrower_name"),
    [
        (RAKESH_CASE, "Rakesh"),
        (CONTACT_CAPPED_CASE, "Meera"),
    ],
)
def test_callable_case_routes_to_its_reviewed_borrower_copy(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    case: MockCaseSeed,
    borrower_name: str,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        f"case-copy-{case.case_id}",
        ("haan boliye", {"intent": "borrower_present"}),
        case=case,
    )

    async def exercise() -> str:
        await controller.start()
        return (await controller.run_turn()).speech_text

    speech = asyncio.run(exercise())

    assert speech == render_template(
        TemplateId.ASK_FOR_BORROWER,
        case_id=case.case_id,
    )
    assert borrower_name in speech
    assert is_bank_member(speech)
    fake.assert_consumed()


@pytest.mark.parametrize("intent", list(PreConfirmationIntent))
def test_controller_boundary_maps_every_typed_intent_to_reviewed_template(
    intent: PreConfirmationIntent,
) -> None:
    validation = validate_preconfirmation_classification({"intent": intent.value})
    template_id = controller_preconfirmation_template(validation)

    assert template_id is TemplateId(PRECONFIRMATION_ROUTES[intent].value)
    assert is_bank_member(render_template(template_id))


def test_controller_output_block_uses_registry_copy_and_discards_draft(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    blocked_draft = "PRIVATE-MARKER aapka balance pandrah sau hai"
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        "output-block-registry",
        (
            "balance batao",
            {
                "intent": "other",
                "response_draft": blocked_draft,
            },
        ),
    )

    async def exercise() -> str:
        await controller.start()
        return (await controller.run_turn()).speech_text

    speech = asyncio.run(exercise())

    assert speech == SAFE_OUTPUT_LINE
    assert is_bank_member(speech)
    assert [request["text"] for request in fake.tts_requests] == [SAFE_OUTPUT_LINE]
    assert blocked_draft not in repr(fake.tts_requests)
    evidence = tuple(
        db_connection.execute(
            """
            SELECT type, redacted_reason
            FROM events
            WHERE call_id = ? AND type = 'OUTPUT_BLOCKED'
            """,
            (controller.call_id,),
        )
    )
    assert len(evidence) == 1
    assert evidence[0]["redacted_reason"] == "output_guard:debt_disclosure"
    assert blocked_draft not in repr(evidence)
    fake.assert_consumed()


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
            INCOMPLETE_VERIFICATION_INPUT_MARKER,
            render_template(TemplateId.VERIFY_REQUEST),
        )
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()

        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.CONFIRMED

    asyncio.run(exercise())

    borrower_return_prompt = json.dumps(fake.chat_requests[2]["messages"], ensure_ascii=False)
    verification_prompt = json.dumps(fake.chat_requests[3]["messages"], ensure_ascii=False)
    for fresh_prompt in (borrower_return_prompt, verification_prompt):
        assert "main unki wife hoon" not in fresh_prompt
        assert "amount batao" not in fresh_prompt
        assert RAKESH_CASE.account.lender_name not in fresh_prompt
        assert str(RAKESH_CASE.account.outstanding_minor) not in fresh_prompt
    assert fake.tts_requests[0]["text"] != fake.tts_requests[1]["text"]
    fake.assert_consumed()


def test_confirmed_handover_demotes_before_model_prompt_and_ignores_model_miss(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        "deterministic-handover",
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        ("चौदह सितंबर, reference 4729", {"intent": "verification_response"}),
        # The model deliberately misses the handover; code must still relock.
        ("lo baat karo", {"intent": "other", "response_draft": "balance is private"}),
    )

    async def exercise() -> str:
        await controller.start()
        await controller.run_turn()
        await controller.run_turn()
        assert controller.snapshot.identity is IdentityState.CONFIRMED

        handover = await controller.run_turn()

        assert controller.snapshot.identity is IdentityState.UNVERIFIED
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()
        return handover.speech_text

    assert asyncio.run(exercise()) == render_template(TemplateId.ASK_FOR_BORROWER)

    prompt = json.dumps(fake.chat_requests[2]["messages"], ensure_ascii=False)
    assert RAKESH_CASE.account.lender_name not in prompt
    assert str(RAKESH_CASE.account.outstanding_minor) not in prompt
    assert COMPLETE_VERIFICATION_INPUT_MARKER not in prompt
    assert "धन्यवाद। पहचान की जाँच पूरी हुई।" not in prompt
    fake.assert_consumed()


def test_partial_verification_turns_complete_one_attempt_without_persisting_values(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
) -> None:
    birth_value = "चौदह सितंबर"
    reference_value = "reference 4729"
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        "partial-verification",
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        (birth_value, {"intent": "verification_response"}),
        (reference_value, {"intent": "verification_response"}),
    )

    async def exercise() -> None:
        await controller.start()
        await controller.run_turn()

        partial = await controller.run_turn()
        assert partial.disposition is None
        assert controller.snapshot.identity is IdentityState.VERIFYING
        assert controller.verification.attempts == 0

        complete = await controller.run_turn()
        assert complete.disposition is None
        assert controller.snapshot.identity is IdentityState.CONFIRMED
        assert controller.verification.attempts == 1

    asyncio.run(exercise())

    attempt_rows = tuple(
        db_connection.execute(
            """
            SELECT redacted_reason
            FROM events
            WHERE call_id = ? AND type = 'VERIFICATION_ATTEMPT'
            ORDER BY seq
            """,
            (controller.call_id,),
        )
    )
    assert len(attempt_rows) == 1
    serialized_evidence = repr(attempt_rows)
    assert birth_value not in serialized_evidence
    assert reference_value not in serialized_evidence
    assert all(
        private_value not in json.dumps(request, ensure_ascii=False)
        for request in fake.chat_requests
        for private_value in (birth_value, reference_value)
    )
    assert [request["messages"][-1]["content"] for request in fake.chat_requests[1:]] == [
        INCOMPLETE_VERIFICATION_INPUT_MARKER,
        INCOMPLETE_VERIFICATION_INPUT_MARKER,
    ]
    fake.assert_consumed()


@pytest.mark.parametrize(
    ("birth_value", "reference_value", "scenario_suffix"),
    [
        ("14/09", "4729", "slash"),
        ("14 09", "4729", "space"),
        ("१४,०९", "4729", "devanagari-comma"),
        ("14/09", "4-7-2-9", "segmented-reference"),
    ],
)
def test_numeric_birth_partial_does_not_guess_reference_or_consume_attempt(
    db_connection: sqlite3.Connection,
    frozen_demo_clock,
    birth_value: str,
    reference_value: str,
    scenario_suffix: str,
) -> None:
    controller, fake = _controller(
        db_connection,
        frozen_demo_clock,
        f"numeric-partial-verification-{scenario_suffix}",
        ("Rakesh bol raha hoon", {"intent": "borrower_present"}),
        (birth_value, {"intent": "verification_response"}),
        (reference_value, {"intent": "verification_response"}),
    )

    async def exercise() -> None:
        await controller.start()
        await controller.run_turn()

        partial = await controller.run_turn()
        assert partial.disposition is None
        assert controller.snapshot.identity is IdentityState.VERIFYING
        assert controller.verification.attempts == 0
        with pytest.raises(ToolPermissionDenied):
            await controller.read_mock_account()

        complete = await controller.run_turn()
        assert complete.disposition is None
        assert controller.snapshot.identity is IdentityState.CONFIRMED
        assert controller.verification.attempts == 1
        assert await controller.read_mock_account() is RAKESH_CASE.account

    asyncio.run(exercise())

    attempt_rows = tuple(
        db_connection.execute(
            """
            SELECT redacted_reason
            FROM events
            WHERE call_id = ? AND type = 'VERIFICATION_ATTEMPT'
            ORDER BY seq
            """,
            (controller.call_id,),
        )
    )
    assert len(attempt_rows) == 1
    assert '"passed":true' in str(attempt_rows[0]["redacted_reason"])
    persisted = repr(
        tuple(
            db_connection.execute(
                """
                SELECT type, state_before, state_after, redacted_reason
                FROM events
                WHERE call_id = ?
                ORDER BY seq
                """,
                (controller.call_id,),
            )
        )
    )
    assert birth_value not in persisted
    assert reference_value not in persisted
    assert all(
        private_value not in json.dumps(request, ensure_ascii=False)
        for request in fake.chat_requests
        for private_value in (birth_value, reference_value)
    )
    assert [request["messages"][-1]["content"] for request in fake.chat_requests[1:]] == [
        INCOMPLETE_VERIFICATION_INPUT_MARKER,
        INCOMPLETE_VERIFICATION_INPUT_MARKER,
    ]
    fake.assert_consumed()
