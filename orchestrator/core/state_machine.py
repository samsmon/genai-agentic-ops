"""State machine and lifecycle transitions for tasks and workflows.

Implements the 10-state task lifecycle, workflow lifecycle, and strict actor
permission checks preventing workers from self-certifying completion.
"""
from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    VERIFIED = "verified"
    APPROVED = "approved"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_RECOVERY = "needs_recovery"


class WorkflowState(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    RUNNING = "running"
    COMPLETED = "completed"
    VERIFIED = "verified"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActorRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    WORKER = "worker"
    GOVERNANCE = "governance"
    HUMAN = "human"


class StateTransitionError(Exception):
    """Raised when an invalid state transition or unauthorized actor is encountered."""


# Task transition matrix: (from_state, to_state) -> set of allowed ActorRoles
TASK_TRANSITION_RULES: dict[tuple[TaskState, TaskState], set[ActorRole]] = {
    (TaskState.PENDING, TaskState.READY): {ActorRole.ORCHESTRATOR},
    (TaskState.PENDING, TaskState.CANCELLED): {ActorRole.HUMAN, ActorRole.ORCHESTRATOR},
    (TaskState.READY, TaskState.RUNNING): {ActorRole.ORCHESTRATOR},
    (TaskState.READY, TaskState.CANCELLED): {ActorRole.HUMAN, ActorRole.ORCHESTRATOR},
    (TaskState.RUNNING, TaskState.COMPLETED): {ActorRole.WORKER, ActorRole.ORCHESTRATOR},
    (TaskState.RUNNING, TaskState.FAILED): {ActorRole.WORKER, ActorRole.ORCHESTRATOR},
    (TaskState.RUNNING, TaskState.NEEDS_RECOVERY): {ActorRole.ORCHESTRATOR},
    (TaskState.RUNNING, TaskState.CANCELLED): {ActorRole.HUMAN, ActorRole.ORCHESTRATOR},
    (TaskState.COMPLETED, TaskState.VERIFIED): {ActorRole.GOVERNANCE, ActorRole.ORCHESTRATOR},
    (TaskState.COMPLETED, TaskState.BLOCKED): {ActorRole.GOVERNANCE, ActorRole.ORCHESTRATOR},
    (TaskState.VERIFIED, TaskState.APPROVED): {ActorRole.HUMAN},
    (TaskState.VERIFIED, TaskState.READY): {ActorRole.HUMAN},
    (TaskState.BLOCKED, TaskState.READY): {ActorRole.HUMAN},
    (TaskState.FAILED, TaskState.READY): {ActorRole.HUMAN, ActorRole.ORCHESTRATOR},
    (TaskState.NEEDS_RECOVERY, TaskState.READY): {ActorRole.HUMAN, ActorRole.ORCHESTRATOR},
    # Human abort can cancel from any active state
    (TaskState.COMPLETED, TaskState.CANCELLED): {ActorRole.HUMAN},
    (TaskState.VERIFIED, TaskState.CANCELLED): {ActorRole.HUMAN},
    (TaskState.BLOCKED, TaskState.CANCELLED): {ActorRole.HUMAN},
    (TaskState.FAILED, TaskState.CANCELLED): {ActorRole.HUMAN},
    (TaskState.NEEDS_RECOVERY, TaskState.CANCELLED): {ActorRole.HUMAN},
}

WORKFLOW_TRANSITION_RULES: dict[tuple[WorkflowState, WorkflowState], set[ActorRole]] = {
    (WorkflowState.DRAFT, WorkflowState.SUBMITTED): {ActorRole.ORCHESTRATOR, ActorRole.HUMAN},
    (WorkflowState.SUBMITTED, WorkflowState.APPROVED): {ActorRole.HUMAN},
    (WorkflowState.SUBMITTED, WorkflowState.DRAFT): {ActorRole.HUMAN},
    (WorkflowState.APPROVED, WorkflowState.RUNNING): {ActorRole.ORCHESTRATOR},
    (WorkflowState.RUNNING, WorkflowState.COMPLETED): {ActorRole.ORCHESTRATOR},
    (WorkflowState.RUNNING, WorkflowState.BLOCKED): {ActorRole.ORCHESTRATOR, ActorRole.GOVERNANCE},
    (WorkflowState.RUNNING, WorkflowState.FAILED): {ActorRole.ORCHESTRATOR},
    (WorkflowState.COMPLETED, WorkflowState.VERIFIED): {ActorRole.GOVERNANCE, ActorRole.ORCHESTRATOR},
    (WorkflowState.VERIFIED, WorkflowState.APPROVED): {ActorRole.HUMAN},
    (WorkflowState.BLOCKED, WorkflowState.RUNNING): {ActorRole.HUMAN, ActorRole.ORCHESTRATOR},
    (WorkflowState.FAILED, WorkflowState.RUNNING): {ActorRole.HUMAN, ActorRole.ORCHESTRATOR},
}


def validate_task_transition(
    current_state: str | TaskState,
    target_state: str | TaskState,
    actor: str | ActorRole,
) -> tuple[bool, str]:
    """Validate whether current_state can transition to target_state by actor.

    Returns (is_valid, reason_or_error_message).
    """
    try:
        c_state = TaskState(current_state)
    except ValueError:
        return False, f"Invalid current task state: '{current_state}'"

    try:
        t_state = TaskState(target_state)
    except ValueError:
        return False, f"Invalid target task state: '{target_state}'"

    try:
        act = ActorRole(actor)
    except ValueError:
        return False, f"Invalid actor role: '{actor}'"

    # Strict boundary: Workers can never set verified or approved
    if act == ActorRole.WORKER and t_state in (TaskState.VERIFIED, TaskState.APPROVED):
        return (
            False,
            f"Unauthorized: worker actors cannot self-certify '{t_state.value}' state",
        )

    # Any state can be cancelled by human
    if t_state == TaskState.CANCELLED and act == ActorRole.HUMAN:
        return True, ""

    allowed_actors = TASK_TRANSITION_RULES.get((c_state, t_state))
    if allowed_actors is None:
        return (
            False,
            f"Illegal transition: '{c_state.value}' -> '{t_state.value}' is not allowed",
        )

    if act not in allowed_actors:
        allowed_names = ", ".join(a.value for a in allowed_actors)
        return (
            False,
            f"Unauthorized: actor '{act.value}' cannot transition '{c_state.value}' -> '{t_state.value}' (permitted: {allowed_names})",
        )

    return True, ""


def validate_workflow_transition(
    current_state: str | WorkflowState,
    target_state: str | WorkflowState,
    actor: str | ActorRole,
) -> tuple[bool, str]:
    """Validate workflow state transition."""
    try:
        c_state = WorkflowState(current_state)
        t_state = WorkflowState(target_state)
        act = ActorRole(actor)
    except ValueError as e:
        return False, str(e)

    if t_state == WorkflowState.CANCELLED and act == ActorRole.HUMAN:
        return True, ""

    allowed_actors = WORKFLOW_TRANSITION_RULES.get((c_state, t_state))
    if allowed_actors is None:
        return (
            False,
            f"Illegal workflow transition: '{c_state.value}' -> '{t_state.value}'",
        )

    if act not in allowed_actors:
        return (
            False,
            f"Unauthorized actor '{act.value}' for workflow transition '{c_state.value}' -> '{t_state.value}'",
        )

    return True, ""
