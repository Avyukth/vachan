"""Declarative state-gated tool permissions and typed denials.

This module is the authorization contract for every controller tool.  It does
not execute tools or mutate application data: callers must authorize and
record the returned decision before invoking a tool implementation.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, StrEnum
from types import MappingProxyType


class ToolName(StrEnum):
    """Tools that the dialogue controller may request."""

    SUBMIT_VERIFICATION = "submit_verification"
    READ_MOCK_ACCOUNT = "read_mock_account"
    CREATE_PROMISE_CANDIDATE = "create_promise_candidate"
    CORRECT_PROMISE_CANDIDATE = "correct_promise_candidate"
    COMMIT_PROMISE = "commit_promise"
    SCHEDULE_CONTENT_FREE_CALLBACK = "schedule_content_free_callback"
    END_CALL = "end_call"


class Condition(StrEnum):
    """Additional, non-state requirements referenced by permission rules."""

    VERIFICATION_ATTEMPTS_AVAILABLE = "verification_attempts_available"
    POSITIVE_AMOUNT = "positive_amount"
    ALLOWED_DATE = "allowed_date"
    UNCOMMITTED_CANDIDATE_EXISTS = "uncommitted_candidate_exists"
    CANDIDATE_READ_BACK = "candidate_read_back"
    EXPLICIT_AFFIRMATIVE = "explicit_affirmative"
    CONTENT_FREE_PAYLOAD = "content_free_payload"
    VALID_END_REASON = "valid_end_reason"


@dataclass(frozen=True, slots=True)
class ToolRule:
    """One row in the permission matrix."""

    identity_states: frozenset[str] | None = None
    call_states: frozenset[str] | None = None
    promise_states: frozenset[str] | None = None
    conditions: tuple[Condition, ...] = ()


@dataclass(frozen=True, slots=True)
class PermissionContext:
    """Redacted facts needed to evaluate a tool request.

    State values may be passed as strings or as enum members.  Conditions are
    booleans computed by the owning domain modules, keeping this contract free
    of account values, verification answers, and mutable model objects.
    """

    identity_state: str | Enum
    call_state: str | Enum
    promise_state: str | Enum
    verification_attempts: int = 0
    max_verification_attempts: int = 2
    amount_minor: int | None = None
    date_is_allowed: bool = False
    candidate_exists: bool = False
    candidate_committed: bool = False
    candidate_read_back: bool = False
    explicit_affirmative: bool = False
    callback_payload_is_content_free: bool = False
    end_reason_is_valid: bool = False


@dataclass(frozen=True, slots=True)
class ToolDecision:
    """Append-only, safe-to-log authorization decision."""

    tool: ToolName
    allowed: bool
    identity_state: str
    call_state: str
    promise_state: str
    reason: str


type DecisionRecorder = Callable[[ToolDecision], None]


class ToolPermissionDenied(RuntimeError):
    """Typed failure raised after a denied decision has been recorded."""

    def __init__(self, decision: ToolDecision) -> None:
        self.decision = decision
        super().__init__(f"{decision.tool.value} denied: {decision.reason}")


_ACTIVE_AGENT_CALL_STATES = frozenset({"ACTIVE"})
_ENDABLE_CALL_STATES = frozenset({"ACTIVE", "DEGRADED", "OPERATOR_TAKEOVER"})

TOOL_PERMISSION_MATRIX = MappingProxyType(
    {
        ToolName.SUBMIT_VERIFICATION: ToolRule(
            identity_states=frozenset({"VERIFYING"}),
            call_states=_ACTIVE_AGENT_CALL_STATES,
            conditions=(Condition.VERIFICATION_ATTEMPTS_AVAILABLE,),
        ),
        ToolName.READ_MOCK_ACCOUNT: ToolRule(
            identity_states=frozenset({"CONFIRMED"}),
            call_states=_ACTIVE_AGENT_CALL_STATES,
        ),
        ToolName.CREATE_PROMISE_CANDIDATE: ToolRule(
            identity_states=frozenset({"CONFIRMED"}),
            call_states=_ACTIVE_AGENT_CALL_STATES,
            conditions=(Condition.POSITIVE_AMOUNT, Condition.ALLOWED_DATE),
        ),
        ToolName.CORRECT_PROMISE_CANDIDATE: ToolRule(
            identity_states=frozenset({"CONFIRMED"}),
            call_states=_ACTIVE_AGENT_CALL_STATES,
            conditions=(Condition.UNCOMMITTED_CANDIDATE_EXISTS,),
        ),
        ToolName.COMMIT_PROMISE: ToolRule(
            identity_states=frozenset({"CONFIRMED"}),
            call_states=_ACTIVE_AGENT_CALL_STATES,
            conditions=(Condition.CANDIDATE_READ_BACK, Condition.EXPLICIT_AFFIRMATIVE),
        ),
        ToolName.SCHEDULE_CONTENT_FREE_CALLBACK: ToolRule(
            identity_states=frozenset({"THIRD_PARTY"}),
            call_states=_ACTIVE_AGENT_CALL_STATES,
            conditions=(Condition.CONTENT_FREE_PAYLOAD,),
        ),
        ToolName.END_CALL: ToolRule(
            call_states=_ENDABLE_CALL_STATES,
            conditions=(Condition.VALID_END_REASON,),
        ),
    }
)


def _state_value(state: str | Enum) -> str:
    value = state.value if isinstance(state, Enum) else state
    return str(value)


_CONDITION_CHECKS: MappingProxyType[Condition, Callable[[PermissionContext], bool]] = (
    MappingProxyType(
        {
            Condition.VERIFICATION_ATTEMPTS_AVAILABLE: (
                lambda context: context.verification_attempts < context.max_verification_attempts
            ),
            Condition.POSITIVE_AMOUNT: (
                lambda context: context.amount_minor is not None and context.amount_minor > 0
            ),
            Condition.ALLOWED_DATE: lambda context: context.date_is_allowed,
            Condition.UNCOMMITTED_CANDIDATE_EXISTS: (
                lambda context: context.candidate_exists and not context.candidate_committed
            ),
            Condition.CANDIDATE_READ_BACK: lambda context: context.candidate_read_back,
            Condition.EXPLICIT_AFFIRMATIVE: lambda context: context.explicit_affirmative,
            Condition.CONTENT_FREE_PAYLOAD: (
                lambda context: context.callback_payload_is_content_free
            ),
            Condition.VALID_END_REASON: lambda context: context.end_reason_is_valid,
        }
    )
)


def evaluate_tool_permission(
    tool: ToolName,
    context: PermissionContext,
) -> ToolDecision:
    """Evaluate one permission-matrix row without performing I/O."""

    rule = TOOL_PERMISSION_MATRIX[tool]
    identity_state = _state_value(context.identity_state)
    call_state = _state_value(context.call_state)
    promise_state = _state_value(context.promise_state)
    failures: list[str] = []

    state_checks = (
        ("identity_state", identity_state, rule.identity_states),
        ("call_state", call_state, rule.call_states),
        ("promise_state", promise_state, rule.promise_states),
    )
    for label, actual, allowed in state_checks:
        if allowed is not None and actual not in allowed:
            failures.append(f"{label}={actual} requires one of {sorted(allowed)}")

    failures.extend(
        f"condition_failed={condition.value}"
        for condition in rule.conditions
        if not _CONDITION_CHECKS[condition](context)
    )

    allowed = not failures
    return ToolDecision(
        tool=tool,
        allowed=allowed,
        identity_state=identity_state,
        call_state=call_state,
        promise_state=promise_state,
        reason="allowed" if allowed else "; ".join(failures),
    )


def authorize_tool(
    tool: ToolName,
    context: PermissionContext,
    record_decision: DecisionRecorder,
) -> ToolDecision:
    """Record a decision, then return it or raise a typed denial.

    Recording happens before the exception, so a denied request always has an
    auditable ``tool_decision`` event and the caller cannot accidentally mutate
    application state first.
    """

    decision = evaluate_tool_permission(tool, context)
    record_decision(decision)
    if not decision.allowed:
        raise ToolPermissionDenied(decision)
    return decision


def execute_authorized_tool[ResultT](
    tool: ToolName,
    context: PermissionContext,
    record_decision: DecisionRecorder,
    operation: Callable[[], ResultT],
) -> ResultT:
    """Run a synchronous low-level effect only after its decision is recorded.

    Runtime controller code should prefer ``GatedToolExecutor``, which derives
    state from the coordinator, persists atomically, and rechecks after await.
    This pure helper remains useful for isolated adapters and unit tests.
    """
    authorize_tool(tool, context, record_decision)
    return operation()
