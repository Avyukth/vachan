"""Permission-matrix contract tests."""

from dataclasses import replace

import pytest

from app.tools import (
    TOOL_PERMISSION_MATRIX,
    PermissionContext,
    ToolDecision,
    ToolName,
    ToolPermissionDenied,
    authorize_tool,
    evaluate_tool_permission,
)


def context(**changes: object) -> PermissionContext:
    """Return an allowed-by-default context with targeted overrides."""

    base = PermissionContext(
        identity_state="CONFIRMED",
        call_state="ACTIVE",
        promise_state="READ_BACK",
        verification_attempts=0,
        amount_minor=150_000,
        date_is_allowed=True,
        candidate_exists=True,
        candidate_committed=False,
        candidate_read_back=True,
        explicit_affirmative=True,
        callback_payload_is_content_free=True,
        end_reason_is_valid=True,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    ("tool", "allowed_context", "denied_context"),
    [
        (
            ToolName.SUBMIT_VERIFICATION,
            context(identity_state="VERIFYING", verification_attempts=1),
            context(identity_state="VERIFYING", verification_attempts=2),
        ),
        (
            ToolName.READ_MOCK_ACCOUNT,
            context(),
            context(identity_state="UNVERIFIED"),
        ),
        (
            ToolName.CREATE_PROMISE_CANDIDATE,
            context(),
            context(amount_minor=0),
        ),
        (
            ToolName.CORRECT_PROMISE_CANDIDATE,
            context(),
            context(candidate_committed=True),
        ),
        (
            ToolName.COMMIT_PROMISE,
            context(),
            context(explicit_affirmative=False),
        ),
        (
            ToolName.SCHEDULE_CONTENT_FREE_CALLBACK,
            context(identity_state="THIRD_PARTY"),
            context(
                identity_state="THIRD_PARTY",
                callback_payload_is_content_free=False,
            ),
        ),
        (
            ToolName.END_CALL,
            context(call_state="OPERATOR_TAKEOVER"),
            context(call_state="COMPLETED"),
        ),
    ],
)
def test_each_matrix_row_has_allowed_and_denied_case(
    tool: ToolName,
    allowed_context: PermissionContext,
    denied_context: PermissionContext,
) -> None:
    assert evaluate_tool_permission(tool, allowed_context).allowed
    assert not evaluate_tool_permission(tool, denied_context).allowed


def test_matrix_contains_exactly_the_seven_contract_tools() -> None:
    assert set(TOOL_PERMISSION_MATRIX) == set(ToolName)
    assert len(TOOL_PERMISSION_MATRIX) == 7


@pytest.mark.parametrize(
    "tool",
    [
        ToolName.SUBMIT_VERIFICATION,
        ToolName.READ_MOCK_ACCOUNT,
        ToolName.CREATE_PROMISE_CANDIDATE,
        ToolName.CORRECT_PROMISE_CANDIDATE,
        ToolName.COMMIT_PROMISE,
        ToolName.SCHEDULE_CONTENT_FREE_CALLBACK,
    ],
)
def test_technical_failure_locks_every_non_ending_tool(tool: ToolName) -> None:
    degraded_context = context(
        call_state="DEGRADED",
        identity_state=("VERIFYING" if tool is ToolName.SUBMIT_VERIFICATION else "CONFIRMED"),
    )
    if tool is ToolName.SCHEDULE_CONTENT_FREE_CALLBACK:
        degraded_context = replace(degraded_context, identity_state="THIRD_PARTY")

    assert not evaluate_tool_permission(tool, degraded_context).allowed


def test_denial_is_recorded_before_typed_failure() -> None:
    decisions: list[ToolDecision] = []

    with pytest.raises(ToolPermissionDenied) as error:
        authorize_tool(
            ToolName.READ_MOCK_ACCOUNT,
            context(identity_state="UNVERIFIED"),
            decisions.append,
        )

    assert decisions == [error.value.decision]
    assert decisions[0].allowed is False
    assert decisions[0].tool is ToolName.READ_MOCK_ACCOUNT
    assert decisions[0].identity_state == "UNVERIFIED"
    assert "identity_state=UNVERIFIED" in decisions[0].reason


def test_allowed_decision_is_also_recorded() -> None:
    decisions: list[ToolDecision] = []

    decision = authorize_tool(ToolName.COMMIT_PROMISE, context(), decisions.append)

    assert decision.allowed
    assert decisions == [decision]


def test_denied_decision_contains_only_redacted_authorization_facts() -> None:
    decision = evaluate_tool_permission(
        ToolName.CREATE_PROMISE_CANDIDATE,
        context(amount_minor=-10, date_is_allowed=False),
    )

    assert decision.reason == ("condition_failed=positive_amount; condition_failed=allowed_date")
    assert "-10" not in decision.reason
