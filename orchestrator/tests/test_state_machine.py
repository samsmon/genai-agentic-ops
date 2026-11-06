"""Tests for orchestrator/core/state_machine.py.

Verifies:
- 10-state task lifecycle transitions
- Strict boundary: workers cannot set verified or approved
- Governance engine verification transitions
- Human approval and user cancellation
- Workflow lifecycle transitions
"""
import unittest

from orchestrator.core.state_machine import (
    ActorRole,
    TaskState,
    WorkflowState,
    validate_task_transition,
    validate_workflow_transition,
)


class TestStateMachine(unittest.TestCase):
    def test_worker_cannot_self_certify(self) -> None:
        # Worker trying to mark completed -> verified
        valid, reason = validate_task_transition(
            TaskState.COMPLETED, TaskState.VERIFIED, ActorRole.WORKER
        )
        self.assertFalse(valid)
        self.assertIn("worker actors cannot self-certify", reason)

        # Worker trying to mark completed -> approved
        valid, reason = validate_task_transition(
            TaskState.COMPLETED, TaskState.APPROVED, ActorRole.WORKER
        )
        self.assertFalse(valid)
        self.assertIn("worker actors cannot self-certify", reason)

        # Worker reporting completion
        valid, _ = validate_task_transition(
            TaskState.RUNNING, TaskState.COMPLETED, ActorRole.WORKER
        )
        self.assertTrue(valid)

        # Worker reporting failure
        valid, _ = validate_task_transition(
            TaskState.RUNNING, TaskState.FAILED, ActorRole.WORKER
        )
        self.assertTrue(valid)

    def test_orchestrator_lifecycle(self) -> None:
        # pending -> ready
        valid, _ = validate_task_transition(
            TaskState.PENDING, TaskState.READY, ActorRole.ORCHESTRATOR
        )
        self.assertTrue(valid)

        # ready -> running
        valid, _ = validate_task_transition(
            TaskState.READY, TaskState.RUNNING, ActorRole.ORCHESTRATOR
        )
        self.assertTrue(valid)

        # running -> needs_recovery
        valid, _ = validate_task_transition(
            TaskState.RUNNING, TaskState.NEEDS_RECOVERY, ActorRole.ORCHESTRATOR
        )
        self.assertTrue(valid)

    def test_governance_verification(self) -> None:
        # completed -> verified
        valid, _ = validate_task_transition(
            TaskState.COMPLETED, TaskState.VERIFIED, ActorRole.GOVERNANCE
        )
        self.assertTrue(valid)

        # completed -> blocked
        valid, _ = validate_task_transition(
            TaskState.COMPLETED, TaskState.BLOCKED, ActorRole.GOVERNANCE
        )
        self.assertTrue(valid)

    def test_human_approval_and_abort(self) -> None:
        # verified -> approved (human only)
        valid, _ = validate_task_transition(
            TaskState.VERIFIED, TaskState.APPROVED, ActorRole.HUMAN
        )
        self.assertTrue(valid)

        # orchestrator cannot approve
        valid, _ = validate_task_transition(
            TaskState.VERIFIED, TaskState.APPROVED, ActorRole.ORCHESTRATOR
        )
        self.assertFalse(valid)

        # human cancellation from active state
        for state in [TaskState.PENDING, TaskState.READY, TaskState.RUNNING, TaskState.BLOCKED]:
            valid, _ = validate_task_transition(state, TaskState.CANCELLED, ActorRole.HUMAN)
            self.assertTrue(valid, f"Human should be able to cancel from {state}")

    def test_workflow_transitions(self) -> None:
        valid, _ = validate_workflow_transition(
            WorkflowState.DRAFT, WorkflowState.SUBMITTED, ActorRole.ORCHESTRATOR
        )
        self.assertTrue(valid)

        valid, _ = validate_workflow_transition(
            WorkflowState.SUBMITTED, WorkflowState.APPROVED, ActorRole.HUMAN
        )
        self.assertTrue(valid)

        valid, _ = validate_workflow_transition(
            WorkflowState.APPROVED, WorkflowState.RUNNING, ActorRole.ORCHESTRATOR
        )
        self.assertTrue(valid)


if __name__ == "__main__":
    unittest.main()
