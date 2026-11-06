"""Task manager for task registry, status transitions, and queries.

Handles task creation from plans, status persistence via FileSystemStorage,
and transition validation.
"""
from __future__ import annotations

import datetime
from typing import Any

from orchestrator.core.state_machine import (
    ActorRole,
    StateTransitionError,
    TaskState,
    validate_task_transition,
)
from orchestrator.storage.filesystem import FileSystemStorage


class TaskManager:
    """Manages task definitions and state transitions backed by storage."""

    def __init__(self, storage: FileSystemStorage) -> None:
        self.storage = storage

    def create_task_from_plan(
        self,
        task_spec: dict[str, Any],
        workflow_id: str,
        initial_status: TaskState = TaskState.PENDING,
    ) -> dict[str, Any]:
        """Create and store a task definition conforming to task.schema.json."""
        task_data = {
            "schema_version": "1.0",
            "task_id": task_spec["task_id"],
            "workflow_id": workflow_id,
            "title": task_spec["title"],
            "role": task_spec["role"],
            "runtime": task_spec["runtime"],
            "status": initial_status.value,
            "acceptance_criteria": task_spec["acceptance_criteria"],
            "description": task_spec.get("description", ""),
            "depends_on": task_spec.get("depends_on", []),
            "allowed_paths": task_spec.get("allowed_paths", []),
            "protected_paths": task_spec.get("protected_paths", []),
            "verification_commands": task_spec.get("verification_commands", []),
            "retry_limit": task_spec.get("retry_limit", 2),
            "timeout_seconds": task_spec.get("timeout_seconds", 300),
        }
        self.storage.save_task(task_data)
        return task_data

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Retrieve task by ID from storage."""
        return self.storage.load_task(task_id)

    def list_tasks(
        self,
        workflow_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filters."""
        return self.storage.list_tasks(workflow_id=workflow_id, status=status)

    def update_task_status(
        self,
        task_id: str,
        target_state: TaskState | str,
        actor: ActorRole | str,
    ) -> dict[str, Any]:
        """Validate and transition task to target state, saving update.

        Raises StateTransitionError if transition is unauthorized or illegal.
        """
        task = self.get_task(task_id)
        if not task:
            raise StateTransitionError(f"Task not found: '{task_id}'")

        current_state = task.get("status")
        valid, reason = validate_task_transition(current_state, target_state, actor)
        if not valid:
            raise StateTransitionError(
                f"Cannot update task '{task_id}' from '{current_state}' to '{target_state}': {reason}"
            )

        target_value = (
            target_state.value if isinstance(target_state, TaskState) else target_state
        )
        task["status"] = target_value
        self.storage.save_task(task)
        return task
