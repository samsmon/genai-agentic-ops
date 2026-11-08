"""Orchestration Coordinator linking storage, locks, governance, and state machine.

Implements M1 lifecycle orchestration:
- Plan submission and task instantiation
- Baseline snapshotting and advisory lock acquisition
- Write-ahead intent logging
- Post-execution scope verification
- Crash recovery detection
"""
from __future__ import annotations

import datetime
import uuid
from pathlib import Path
from typing import Any

from orchestrator.core.state_machine import (
    ActorRole,
    TaskState,
    WorkflowState,
    validate_task_transition,
)
from orchestrator.core.task_manager import TaskManager
from orchestrator.core.workflow_engine import WorkflowEngine
from orchestrator.governance.approval import ApprovalManager
from orchestrator.governance.audit import AuditLogger
from orchestrator.governance.lock import LockManager
from orchestrator.governance.metrics import TelemetryLedger
from orchestrator.governance.policy_bridge import PolicyBridge
from orchestrator.governance.process_info import get_host_tuple, is_process_alive
from orchestrator.governance.projection import CurrentOpsProjector
from orchestrator.governance.quarantine import WorkspaceQuarantine
from orchestrator.governance.scope_check import ScopeChecker
from orchestrator.planner.validator import PlanValidator
from orchestrator.registry.agents import AgentRegistry
from orchestrator.storage.filesystem import FileSystemStorage


class OrchestratorCoordinator:
    """Coordinates lifecycle across storage, locks, state machine, and governance."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.storage = FileSystemStorage(self.root_dir)
        self.lock_manager = LockManager(self.storage.locks_dir)
        self.scope_checker = ScopeChecker(self.root_dir)
        self.task_manager = TaskManager(self.storage)
        self.validator = PlanValidator()
        self.registry = AgentRegistry()
        self.policy_bridge = PolicyBridge(self.root_dir)
        self.approval_manager = ApprovalManager(self.root_dir)
        self.audit_logger = AuditLogger(self.root_dir)
        self.projector = CurrentOpsProjector(self.root_dir)
        self.quarantine = WorkspaceQuarantine(self.root_dir)
        self.telemetry = TelemetryLedger(self.root_dir)

    def submit_plan(self, plan_data_or_file: dict[str, Any] | str | Path) -> dict[str, Any]:
        """Validate and submit an execution plan, registering tasks and resolving ready items."""
        if isinstance(plan_data_or_file, (str, Path)):
            val_res = self.validator.validate_plan_file(plan_data_or_file)
        else:
            val_res = self.validator.validate_plan_dict(plan_data_or_file)

        if not val_res.valid:
            raise ValueError(f"Plan validation failed: {'; '.join(val_res.errors)}")

        plan = val_res.plan_data or {}
        wf_id = plan["workflow_id"]

        # 1. Save plan definition
        self.storage.save_plan(wf_id, plan)

        # 2. Initialize workflow record
        initial_wf_state = (
            WorkflowState.SUBMITTED.value
            if plan.get("approval_required", True)
            else WorkflowState.APPROVED.value
        )
        wf_record = {
            "schema_version": "1.0",
            "workflow_id": wf_id,
            "title": plan["title"],
            "status": initial_wf_state,
            "tasks": [t["task_id"] for t in plan["tasks"]],
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        self.storage.save_workflow(wf_record)

        # 3. Register tasks in PENDING state
        created_tasks: list[dict[str, Any]] = []
        for t_spec in plan["tasks"]:
            t_obj = self.task_manager.create_task_from_plan(
                t_spec, wf_id, initial_status=TaskState.PENDING
            )
            created_tasks.append(t_obj)

        # 4. If workflow is approved, resolve initial ready tasks
        if initial_wf_state == WorkflowState.APPROVED.value:
            self._advance_ready_tasks(wf_id)

        self.audit_logger.log_event(
            "submitted",
            workflow_id=wf_id,
            details={"title": plan["title"], "tasks_count": len(created_tasks)},
        )
        self.projector.project(self.task_manager.list_tasks())

        return {
            "workflow_id": wf_id,
            "status": initial_wf_state,
            "tasks_count": len(created_tasks),
        }

    def _advance_ready_tasks(self, workflow_id: str) -> list[str]:
        """Find pending tasks whose dependencies are met and transition them to READY."""
        tasks = self.task_manager.list_tasks(workflow_id=workflow_id)
        ready_tasks = WorkflowEngine.get_ready_tasks(tasks)
        advanced: list[str] = []

        for rt in ready_tasks:
            t_id = rt["task_id"]
            self.task_manager.update_task_status(
                t_id, TaskState.READY, ActorRole.ORCHESTRATOR
            )
            advanced.append(t_id)

        return advanced

    def prepare_task_execution(self, task_id: str) -> dict[str, Any]:
        """Acquire lock, capture baseline snapshot, write intent, transition to RUNNING."""
        task = self.task_manager.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")

        if task["status"] != TaskState.READY.value:
            raise ValueError(
                f"Task '{task_id}' cannot start from state '{task['status']}' (expected 'ready')"
            )

        wf_id = task["workflow_id"]
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. Acquire advisory lock
        self.lock_manager.acquire(
            task_id=task_id,
            workflow_id=wf_id,
            allowed_paths=task.get("allowed_paths", []),
        )

        # 2. Baseline snapshot
        baseline = self.scope_checker.capture_snapshot()

        # 3. Write-ahead intent log
        intent_record = {
            "schema_version": "1.0",
            "run_id": run_id,
            "workflow_id": wf_id,
            "status": "running",
            "host": get_host_tuple(),
            "intent": {
                "target_state": "running",
                "action": "execute_task",
                "timestamp": now,
            },
            "workspace_baseline": {
                "git_commit": "untracked",
                "clean": True,
                "snapshot_hash": baseline["snapshot_hash"],
                "timestamp": now,
            },
            "active_task_id": task_id,
            "created_at": now,
            "updated_at": now,
        }
        self.storage.write_intent(run_id, intent_record)
        self.storage.save_run(run_id, intent_record)

        # 4. Transition task to RUNNING
        self.task_manager.update_task_status(
            task_id, TaskState.RUNNING, ActorRole.ORCHESTRATOR
        )

        self.audit_logger.log_event(
            "started", task_id=task_id, workflow_id=wf_id, run_id=run_id
        )
        self.audit_logger.log_event(
            "lock_acquired", task_id=task_id, workflow_id=wf_id, run_id=run_id
        )
        self.projector.project(self.task_manager.list_tasks())

        return {
            "run_id": run_id,
            "task_id": task_id,
            "baseline": baseline,
            "intent_record": intent_record,
            "created_at": now,
        }

    def complete_task_execution(
        self,
        task_id: str,
        run_id: str,
        exit_code: int = 0,
        stdout_ref: str = "",
        stderr_ref: str = "",
    ) -> dict[str, Any]:
        """Record worker process termination, write result log, release lock."""
        task = self.task_manager.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")

        target_state = (
            TaskState.COMPLETED if exit_code == 0 else TaskState.FAILED
        )
        self.task_manager.update_task_status(
            task_id, target_state, ActorRole.WORKER
        )

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        result_record = {
            "schema_version": "1.0",
            "run_id": run_id,
            "task_id": task_id,
            "workflow_id": task["workflow_id"],
            "exit_code": exit_code,
            "status": target_state.value,
            "completed_at": now,
            "stdout_ref": stdout_ref,
            "stderr_ref": stderr_ref,
        }
        self.storage.write_result(run_id, result_record)

        # Release advisory lock
        self.lock_manager.release(force=True)
        return result_record

    def verify_task(
        self,
        task_id: str,
        baseline_snapshot: dict[str, Any],
        verification_passed: bool = True,
    ) -> dict[str, Any]:
        """Verify workspace diff against allowed/protected paths and transition task."""
        task = self.task_manager.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")

        diff = self.scope_checker.compute_diff(baseline_snapshot)
        scope_res = self.scope_checker.verify_scope(
            diff,
            allowed_paths=task.get("allowed_paths", []),
            protected_paths=task.get("protected_paths", []),
        )

        if scope_res["in_scope"] and verification_passed:
            self.task_manager.update_task_status(
                task_id, TaskState.VERIFIED, ActorRole.GOVERNANCE
            )
        else:
            self.task_manager.update_task_status(
                task_id, TaskState.BLOCKED, ActorRole.GOVERNANCE
            )

        self._refresh_workflow_status(task["workflow_id"])
        return scope_res

    def approve_task(
        self,
        task_id: str,
        token: str | None = None,
        approver: str = "human",
    ) -> dict[str, Any]:
        """Human approval grants task completion and unlocks downstream ready tasks."""
        task = self.task_manager.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")

        if self.approval_manager.has_pending_approval(task_id):
            if not token:
                raise ValueError(
                    f"Approval token is required to approve task '{task_id}' with a pending approval request"
                )
            self.approval_manager.grant_approval(task_id, token, approver)

        self.task_manager.update_task_status(
            task_id, TaskState.APPROVED, ActorRole.HUMAN
        )
        wf_id = task["workflow_id"]
        advanced = self._advance_ready_tasks(wf_id)
        self._refresh_workflow_status(wf_id)

        self.audit_logger.log_event(
            "approval_granted",
            task_id=task_id,
            workflow_id=wf_id,
            details={"approver": approver},
        )
        self.projector.project(self.task_manager.list_tasks())

        return {"task_id": task_id, "status": "approved", "unlocked_tasks": advanced}

    def _refresh_workflow_status(self, workflow_id: str) -> None:
        """Recompute and save workflow aggregate status."""
        wf = self.storage.load_workflow(workflow_id)
        if not wf:
            return
        tasks = self.task_manager.list_tasks(workflow_id=workflow_id)
        new_status = WorkflowEngine.compute_workflow_status(
            tasks, wf.get("status", WorkflowState.RUNNING.value)
        )
        if new_status != wf.get("status"):
            wf["status"] = new_status
            self.storage.save_workflow(wf)

    def detect_and_recover_crashes(self) -> list[dict[str, Any]]:
        """Identify orphaned intent logs from dead processes and reconcile tasks."""
        orphaned = self.storage.detect_orphaned_intents()
        reconciled: list[dict[str, Any]] = []

        for item in orphaned:
            run_id = item["run_id"]
            intent = item["intent"]
            host = intent.get("host", {})
            hostname = host.get("hostname", "")
            pid = host.get("pid", 0)
            start_time = host.get("process_start_time", "")

            alive = is_process_alive(hostname, pid, start_time)
            if alive is False:
                # Process is dead without writing result.json
                task_id = intent.get("active_task_id") or intent.get("task_id")
                if task_id:
                    task = self.task_manager.get_task(task_id)
                    if task and task.get("status") == TaskState.RUNNING.value:
                        self.task_manager.update_task_status(
                            task_id, TaskState.NEEDS_RECOVERY, ActorRole.ORCHESTRATOR
                        )
                # Break any lingering lock
                self.lock_manager.break_stale_lock()
                reconciled.append(
                    {"run_id": run_id, "task_id": task_id, "reason": "Process died"}
                )

        return reconciled
