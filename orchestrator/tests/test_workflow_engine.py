"""Tests for orchestrator/core/workflow_engine.py.

Verifies:
- DAG dependency resolution and topological sort
- Cyclic dependency rejection
- Missing dependency rejection
- Ready task resolution based on satisfied dependencies
- Workflow aggregated status computation
"""
import unittest

from orchestrator.core.state_machine import TaskState, WorkflowState
from orchestrator.core.workflow_engine import WorkflowEngine, WorkflowGraphError


class TestWorkflowEngine(unittest.TestCase):
    def test_topological_sort_success(self) -> None:
        tasks = [
            {"task_id": "task-3", "depends_on": ["task-1", "task-2"]},
            {"task_id": "task-1", "depends_on": []},
            {"task_id": "task-2", "depends_on": ["task-1"]},
        ]
        order = WorkflowEngine.validate_dag(tasks)
        self.assertEqual(order[0], "task-1")
        self.assertEqual(order[1], "task-2")
        self.assertEqual(order[2], "task-3")

    def test_cycle_detection(self) -> None:
        tasks = [
            {"task_id": "task-1", "depends_on": ["task-2"]},
            {"task_id": "task-2", "depends_on": ["task-1"]},
        ]
        with self.assertRaises(WorkflowGraphError) as ctx:
            WorkflowEngine.validate_dag(tasks)
        self.assertIn("Cyclic dependency", str(ctx.exception))

    def test_missing_dependency(self) -> None:
        tasks = [
            {"task_id": "task-1", "depends_on": ["task-ghost"]},
        ]
        with self.assertRaises(WorkflowGraphError) as ctx:
            WorkflowEngine.validate_dag(tasks)
        self.assertIn("non-existent task", str(ctx.exception))

    def test_get_ready_tasks(self) -> None:
        tasks = [
            {"task_id": "task-1", "status": TaskState.APPROVED.value, "depends_on": []},
            {"task_id": "task-2", "status": TaskState.PENDING.value, "depends_on": ["task-1"]},
            {"task_id": "task-3", "status": TaskState.PENDING.value, "depends_on": ["task-2"]},
        ]
        ready = WorkflowEngine.get_ready_tasks(tasks)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["task_id"], "task-2")

    def test_compute_workflow_status(self) -> None:
        # Blocked if any task is blocked
        t_blocked = [
            {"status": TaskState.APPROVED.value},
            {"status": TaskState.BLOCKED.value},
        ]
        self.assertEqual(
            WorkflowEngine.compute_workflow_status(t_blocked),
            WorkflowState.BLOCKED.value,
        )

        # Running if tasks are active
        t_running = [
            {"status": TaskState.RUNNING.value},
            {"status": TaskState.PENDING.value},
        ]
        self.assertEqual(
            WorkflowEngine.compute_workflow_status(t_running),
            WorkflowState.RUNNING.value,
        )

        # Approved if all tasks are approved
        t_approved = [
            {"status": TaskState.APPROVED.value},
            {"status": TaskState.APPROVED.value},
        ]
        self.assertEqual(
            WorkflowEngine.compute_workflow_status(t_approved),
            WorkflowState.APPROVED.value,
        )


if __name__ == "__main__":
    unittest.main()
