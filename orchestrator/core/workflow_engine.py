"""Workflow dependency resolution and DAG lifecycle evaluation.

Implements topological sorting, cyclic dependency detection, next-eligible task
resolution, and workflow aggregated status calculation.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from orchestrator.core.state_machine import TaskState, WorkflowState


class WorkflowGraphError(Exception):
    """Raised when task dependencies are cyclic, missing, or malformed."""


class WorkflowEngine:
    """Manages DAG dependency resolution and task eligibility."""

    @staticmethod
    def validate_dag(tasks: list[dict[str, Any]]) -> list[str]:
        """Validate DAG acyclicity and return topologically sorted task IDs.

        Raises WorkflowGraphError if cyclic or references unknown dependencies.
        """
        task_map = {t["task_id"]: t for t in tasks}
        in_degree: dict[str, int] = {t_id: 0 for t_id in task_map}
        adj: dict[str, list[str]] = {t_id: [] for t_id in task_map}

        # Build graph: edge u -> v means task v depends on u (u must complete before v)
        for t_id, task in task_map.items():
            depends_on = task.get("depends_on") or []
            for dep in depends_on:
                if dep not in task_map:
                    raise WorkflowGraphError(
                        f"Task '{t_id}' depends on non-existent task '{dep}'"
                    )
                adj[dep].append(t_id)
                in_degree[t_id] += 1

        # Kahn's algorithm
        queue = deque([t_id for t_id, deg in in_degree.items() if deg == 0])
        sorted_order: list[str] = []

        while queue:
            curr = queue.popleft()
            sorted_order.append(curr)
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_order) != len(task_map):
            unresolved = [t_id for t_id, deg in in_degree.items() if deg > 0]
            raise WorkflowGraphError(
                f"Cyclic dependency detected among tasks: {', '.join(unresolved)}"
            )

        return sorted_order

    @staticmethod
    def get_ready_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Identify pending tasks whose dependencies are fully approved or verified."""
        task_by_id = {t["task_id"]: t for t in tasks}
        eligible: list[dict[str, Any]] = []

        finished_states = {
            TaskState.APPROVED.value,
            TaskState.VERIFIED.value,
        }

        for task in tasks:
            if task.get("status") != TaskState.PENDING.value:
                continue

            deps = task.get("depends_on") or []
            deps_satisfied = all(
                task_by_id.get(dep, {}).get("status") in finished_states
                for dep in deps
            )

            if deps_satisfied:
                eligible.append(task)

        return eligible

    @staticmethod
    def compute_workflow_status(
        tasks: list[dict[str, Any]],
        current_workflow_status: str = WorkflowState.RUNNING.value,
    ) -> str:
        """Compute the aggregate workflow state from task states."""
        if not tasks:
            return current_workflow_status

        statuses = [t.get("status") for t in tasks]

        # Prioritize terminal blocker states
        if any(s == TaskState.BLOCKED.value for s in statuses):
            return WorkflowState.BLOCKED.value

        if any(s == TaskState.FAILED.value for s in statuses):
            return WorkflowState.FAILED.value

        if any(s == TaskState.CANCELLED.value for s in statuses) and all(
            s in (TaskState.CANCELLED.value, TaskState.COMPLETED.value, TaskState.APPROVED.value)
            for s in statuses
        ):
            return WorkflowState.CANCELLED.value

        if any(s in (TaskState.RUNNING.value, TaskState.READY.value) for s in statuses):
            return WorkflowState.RUNNING.value

        # Completion criteria
        if all(s == TaskState.APPROVED.value for s in statuses):
            return WorkflowState.APPROVED.value

        if all(s in (TaskState.VERIFIED.value, TaskState.APPROVED.value) for s in statuses):
            return WorkflowState.VERIFIED.value

        if all(
            s in (TaskState.COMPLETED.value, TaskState.VERIFIED.value, TaskState.APPROVED.value)
            for s in statuses
        ):
            return WorkflowState.COMPLETED.value

        # Still has pending tasks
        return WorkflowState.RUNNING.value
