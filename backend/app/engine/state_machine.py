from enum import Enum


class ExecutionMode(str, Enum):
    LIVE = "LIVE"
    SANDBOX = "SANDBOX"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RECONCILING = "RECONCILING"
    COMPENSATING = "COMPENSATING"
    DISPATCHING_FINAL = "DISPATCHING_FINAL"
    COMPLETED = "COMPLETED"
    COMPENSATED_HALTED = "COMPENSATED_HALTED"
    FAILED_NEEDS_HUMAN = "FAILED_NEEDS_HUMAN"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    COMMITTED = "COMMITTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CONSUMED_FOR_DISPATCH = "CONSUMED_FOR_DISPATCH"
    REJECTED = "REJECTED"
    INVALIDATED_STALE = "INVALIDATED_STALE"


class VerificationStatus(str, Enum):
    APPLIED = "APPLIED"
    DEFINITIVELY_NOT_APPLIED = "DEFINITIVELY_NOT_APPLIED"
    UNKNOWN = "UNKNOWN"


class CompensationStatus(str, Enum):
    NOT_NEEDED = "NOT_NEEDED"
    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"


class IdempotencyMode(str, Enum):
    DEDUP_KEY_SUPPORTED = "DEDUP_KEY_SUPPORTED"
    VERIFY_THEN_FENCE = "VERIFY_THEN_FENCE"


class Compensatability(str, Enum):
    COMPENSATABLE = "COMPENSATABLE"
    IRREVERSIBLE_TERMINAL = "IRREVERSIBLE_TERMINAL"


RUN_TRANSITIONS = {
    RunStatus.RUNNING: {
        RunStatus.AWAITING_APPROVAL,
        RunStatus.RECONCILING,
        RunStatus.COMPENSATING,
        RunStatus.DISPATCHING_FINAL,
        RunStatus.FAILED_NEEDS_HUMAN,
    },
    RunStatus.AWAITING_APPROVAL: {
        RunStatus.RUNNING,
        RunStatus.COMPENSATING,
        RunStatus.DISPATCHING_FINAL,
        RunStatus.FAILED_NEEDS_HUMAN,
    },
    RunStatus.RECONCILING: {
        RunStatus.RUNNING,
        RunStatus.COMPENSATING,
        RunStatus.DISPATCHING_FINAL,
        RunStatus.FAILED_NEEDS_HUMAN,
    },
    RunStatus.COMPENSATING: {
        RunStatus.COMPENSATED_HALTED,
        RunStatus.RUNNING,
        RunStatus.FAILED_NEEDS_HUMAN,
    },
    RunStatus.DISPATCHING_FINAL: {
        RunStatus.RECONCILING,
        RunStatus.COMPLETED,
        RunStatus.FAILED_NEEDS_HUMAN,
    },
    RunStatus.FAILED_NEEDS_HUMAN: {
        RunStatus.RECONCILING,
        RunStatus.COMPENSATING,
        RunStatus.DISPATCHING_FINAL,
        RunStatus.RUNNING,
    },
    RunStatus.COMPLETED: set(),
    RunStatus.COMPENSATED_HALTED: set(),
}
STEP_TRANSITIONS = {
    StepStatus.PENDING: {
        StepStatus.IN_FLIGHT,
        StepStatus.COMMITTED,
        StepStatus.FAILED_TERMINAL,
    },
    StepStatus.IN_FLIGHT: {
        StepStatus.COMMITTED,
        StepStatus.OUTCOME_UNKNOWN,
        StepStatus.FAILED_RETRYABLE,
        StepStatus.FAILED_TERMINAL,
    },
    StepStatus.OUTCOME_UNKNOWN: {
        StepStatus.COMMITTED,
        StepStatus.FAILED_RETRYABLE,
        StepStatus.FAILED_TERMINAL,
    },
    StepStatus.FAILED_RETRYABLE: {StepStatus.IN_FLIGHT, StepStatus.FAILED_TERMINAL},
    StepStatus.COMMITTED: {StepStatus.COMPENSATING},
    StepStatus.COMPENSATING: {StepStatus.COMPENSATED, StepStatus.COMPENSATION_FAILED},
    StepStatus.COMPENSATION_FAILED: {StepStatus.COMPENSATING},
    StepStatus.COMPENSATED: set(),
    StepStatus.FAILED_TERMINAL: set(),
}


def transition(obj, target):
    table = RUN_TRANSITIONS if isinstance(obj.status, RunStatus) else STEP_TRANSITIONS
    if obj.status != target and target not in table[obj.status]:
        raise ValueError(f"Illegal transition {obj.status} -> {target}")
    obj.status = target
