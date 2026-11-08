"""Execution runner for tasks and sequential workflows.

Implements M3 execution orchestration:
- Checks task readiness and workflow dependencies
- Prepares execution: advisory lock, baseline snapshot, write-ahead intent log
- Invokes declared runtime adapter from registry
- Captures post-execution workspace diff against allowed and protected paths
- Runs deterministic verification commands
- Records result conforming to contracts/result.schema.json and releases lock
- Executes ready tasks sequentially across the shared workspace
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path
from typing import Any

from orchestrator.adapters.base import ExecutionResult
from orchestrator.adapters.process_runner import ProcessRunner
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.state_machine import ActorRole, TaskState
from orchestrator.core.workflow_engine import WorkflowEngine
from orchestrator.governance.process_info import get_host_tuple


class TaskRunner:
    """Coordinates task execution, runtime adapter invocation, and post-run verification."""

    def __init__(
        self,
        coordinator: OrchestratorCoordinator,
        process_runner: ProcessRunner | None = None,
    ) -> None:
        self.coord = coordinator
        self.runner = process_runner or ProcessRunner()

    def run_task(
        self,
        task_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Execute a ready task through its runtime adapter and verify outcomes."""
        task = self.coord.task_manager.get_task(task_id)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")

        # 1. Dependency and readiness verification
        if task.get("status") != TaskState.READY.value:
            tasks = self.coord.task_manager.list_tasks(workflow_id=task["workflow_id"])
            ready_task_ids = [t["task_id"] for t in WorkflowEngine.get_ready_tasks(tasks)]
            if task_id in ready_task_ids:
                self.coord.task_manager.update_task_status(
                    task_id, TaskState.READY, ActorRole.ORCHESTRATOR
                )
                task["status"] = TaskState.READY.value
            else:
                raise ValueError(
                    f"Task '{task_id}' is not in READY state (current: '{task.get('status')}')"
                )

        runtime = task.get("runtime", "antigravity")
        role = task.get("role", "developer")
        adapter = self.coord.registry.resolve_runtime(runtime, role=role)
        if not adapter:
            raise ValueError(f"No runtime adapter registered for runtime '{runtime}'")

        # 2. Prepare execution (advisory lock, baseline snapshot, quarantine backup, intent log)
        backup = self.coord.quarantine.capture_backup()
        prep = self.coord.prepare_task_execution(task_id)
        run_id = prep["run_id"]
        baseline = prep["baseline"]

        handoff = {
            "task_id": task_id,
            "workflow_id": task["workflow_id"],
            "title": task.get("title", ""),
            "description": task.get("description", ""),
            "role": task.get("role", "developer"),
            "prompt": task.get("description") or task.get("title", ""),
            "allowed_paths": task.get("allowed_paths", []),
            "protected_paths": task.get("protected_paths", []),
            "acceptance_criteria": task.get("acceptance_criteria", []),
            "verification_commands": task.get("verification_commands", []),
        }

        timeout = timeout_seconds or task.get("timeout_seconds") or 300

        try:
            # 3. Invoke worker adapter
            exec_res = adapter.execute(
                task=task,
                handoff=handoff,
                run_handle=run_id,
                timeout_seconds=timeout,
            )
        except Exception as exc:
            exec_res = ExecutionResult(
                exit_code=1,
                status="failed",
                stderr=str(exc),
            )

        # Write stdout and stderr logs under .agentic/runs/<run_id>/
        run_log_dir = self.coord.storage.runs_dir / run_id
        run_log_dir.mkdir(parents=True, exist_ok=True)
        stdout_file = run_log_dir / "stdout.log"
        stderr_file = run_log_dir / "stderr.log"
        stdout_file.write_text(exec_res.stdout or "", encoding="utf-8")
        stderr_file.write_text(exec_res.stderr or "", encoding="utf-8")
        stdout_ref = str(stdout_file.relative_to(self.coord.root_dir)).replace("\\", "/")
        stderr_ref = str(stderr_file.relative_to(self.coord.root_dir)).replace("\\", "/")

        # Transition task out of RUNNING
        if exec_res.exit_code == 0 and exec_res.status != "blocked":
            self.coord.task_manager.update_task_status(
                task_id, TaskState.COMPLETED, ActorRole.WORKER
            )
            self.coord.audit_logger.log_event(
                "worker_completed",
                task_id=task_id,
                workflow_id=task["workflow_id"],
                run_id=run_id,
                details={"exit_code": 0, "status": exec_res.status},
            )
        else:
            self.coord.task_manager.update_task_status(
                task_id, TaskState.FAILED, ActorRole.WORKER
            )
            self.coord.audit_logger.log_event(
                "failed",
                task_id=task_id,
                workflow_id=task["workflow_id"],
                run_id=run_id,
                details={"exit_code": exec_res.exit_code, "status": exec_res.status},
            )

        # 4. Post-run diff verification (snapshot captured prior to verification commands)
        diff = self.coord.scope_checker.compute_diff(baseline)
        scope_res = self.coord.scope_checker.verify_scope(
            diff,
            allowed_paths=task.get("allowed_paths", []),
            protected_paths=task.get("protected_paths", []),
        )
        if scope_res.get("in_scope", False):
            quarantined_files: list[str] = []
            self.coord.audit_logger.log_event(
                "scope_verified",
                task_id=task_id,
                workflow_id=task["workflow_id"],
                run_id=run_id,
                details={"in_scope": True},
            )
        else:
            quarantined_files = self.coord.quarantine.quarantine_and_rollback(
                run_id=run_id,
                diff=diff,
                allowed_paths=task.get("allowed_paths", []),
                protected_paths=task.get("protected_paths", []),
                backup=backup,
            )
            self.coord.audit_logger.log_event(
                "blocked",
                task_id=task_id,
                workflow_id=task["workflow_id"],
                run_id=run_id,
                details={
                    "reason": "scope_or_monolith_violation",
                    "violations": scope_res.get("violations", []),
                    "quarantined_files": quarantined_files,
                },
            )

        # 5. Verification commands execution with Policy Bridge validation
        command_results: list[dict[str, Any]] = []
        all_passed = True

        if exec_res.exit_code == 0 and exec_res.status != "blocked" and scope_res.get("in_scope", False):
            sec_config = self._get_security_config()
            allowed_ver_cmds = sec_config.get("allowed_verification_commands")

            ver_commands = task.get("verification_commands") or []
            for cmd in ver_commands:
                cmd_repr = cmd if isinstance(cmd, str) else " ".join(cmd)

                # Validate against allowed_verification_commands if configured
                if allowed_ver_cmds:
                    if not self._is_verification_command_allowed(cmd_repr, allowed_ver_cmds):
                        all_passed = False
                        msg = (
                            f"Verification command '{cmd_repr}' is not allowed by "
                            f"security.allowed_verification_commands: {allowed_ver_cmds}"
                        )
                        command_results.append({
                            "command": cmd_repr, "exit_code": 1, "passed": False,
                            "output_snippet": msg,
                        })
                        break

                # Validate command through PolicyBridge first
                is_valid, policy_msg = self.coord.policy_bridge.validate_verification_command(cmd)
                if not is_valid:
                    all_passed = False
                    command_results.append({
                        "command": cmd_repr, "exit_code": 1, "passed": False,
                        "output_snippet": policy_msg,
                    })
                    break

                cmd_list = self._format_command(cmd)
                v_res = self.runner.run(
                    command=cmd_list, cwd=self.coord.root_dir, timeout_seconds=60,
                )
                passed = (v_res.exit_code == 0)
                snippet = (v_res.stdout + "\n" + v_res.stderr).strip()[:500]
                command_results.append({
                    "command": cmd_repr, "exit_code": v_res.exit_code, "passed": passed,
                    "output_snippet": snippet or ("Passed" if passed else "Failed"),
                })
                if not passed:
                    all_passed = False
                    break

            if all_passed and ver_commands:
                # Ensure file modifications or new files created by verification_commands
                # are also checked against allowed_paths / allowed_files (and rolled back if rogue)
                allowed_paths = task.get("allowed_paths", []) or task.get("allowed_files", [])
                protected_paths = task.get("protected_paths", [])
                diff_post_ver = self.coord.scope_checker.compute_diff(baseline)
                scope_post_ver = self.coord.scope_checker.verify_scope(
                    diff_post_ver,
                    allowed_paths=allowed_paths,
                    protected_paths=protected_paths,
                )
                if not scope_post_ver.get("in_scope", False):
                    all_passed = False
                    quarantined = self.coord.quarantine.quarantine_and_rollback(
                        run_id=run_id,
                        diff=diff_post_ver,
                        allowed_paths=allowed_paths,
                        protected_paths=protected_paths,
                        backup=backup,
                    )
                    quarantined_files.extend(quarantined)
                    scope_res = scope_post_ver
                    diff = self.coord.scope_checker.compute_diff(baseline)
                    self.coord.audit_logger.log_event(
                        "blocked",
                        task_id=task_id,
                        workflow_id=task["workflow_id"],
                        run_id=run_id,
                        details={
                            "reason": "verification_mutated_out_of_scope",
                            "violations": scope_post_ver.get("violations", []),
                            "quarantined_files": quarantined,
                        },
                    )
                else:
                    diff = diff_post_ver
                    scope_res = scope_post_ver
                    self.coord.audit_logger.log_event(
                        "verification_passed",
                        task_id=task_id,
                        workflow_id=task["workflow_id"],
                        run_id=run_id,
                        details={"commands": [cr["command"] for cr in command_results]},
                    )
            elif not all_passed:
                self.coord.audit_logger.log_event(
                    "blocked",
                    task_id=task_id,
                    workflow_id=task["workflow_id"],
                    run_id=run_id,
                    details={"reason": "verification_failed"},
                )
        else:
            all_passed = False

        # 6. Final governance transition
        if exec_res.exit_code == 0 and exec_res.status != "blocked":
            if scope_res.get("in_scope", False) and all_passed:
                self.coord.task_manager.update_task_status(
                    task_id, TaskState.VERIFIED, ActorRole.GOVERNANCE
                )
                final_status = TaskState.VERIFIED.value
            else:
                self.coord.task_manager.update_task_status(
                    task_id, TaskState.BLOCKED, ActorRole.GOVERNANCE
                )
                final_status = TaskState.BLOCKED.value
        else:
            final_status = TaskState.BLOCKED.value if exec_res.status == "blocked" else TaskState.FAILED.value

        # 7. Release advisory lock
        self.coord.lock_manager.release(force=True)
        self.coord.audit_logger.log_event(
            "lock_released",
            task_id=task_id,
            workflow_id=task["workflow_id"],
            run_id=run_id,
        )

        # 8. Human approval handling
        plan_doc = self.coord.storage.load_plan(task["workflow_id"]) or {}
        needs_approval = task.get(
            "approval_required", plan_doc.get("approval_required", True)
        )
        if final_status == TaskState.VERIFIED.value and needs_approval:
            self.coord.approval_manager.request_approval(
                task_id,
                context={
                    "workflow_id": task["workflow_id"],
                    "diff": scope_res,
                    "verification_passed": all_passed,
                },
            )
            approval_record = {"required": True, "status": "pending"}
        else:
            approval_record = {"required": False, "status": "not_required"}

        # 9. Result record conforming to contracts/result.schema.json
        resolved_rt = adapter.runtime if runtime == "auto" else task.get("runtime", runtime)
        result_record = {
            "schema_version": "1.0",
            "task_id": task_id,
            "workflow_id": task["workflow_id"],
            "runtime": resolved_rt,
            "execution": {
                "exit_code": exec_res.exit_code,
                "status": exec_res.status,
                "duration_ms": exec_res.duration_ms,
                "stdout_ref": stdout_ref,
                "stderr_ref": stderr_ref,
                "session_id": exec_res.session_id or "",
                "permission_denials": list(exec_res.permission_denials),
            },
            "diff": {
                "changed_files": diff.get("changed_files", []),
                "staged_files": diff.get("staged_files", []),
                "untracked_files": diff.get("untracked_files", []),
                "in_scope": bool(scope_res.get("in_scope", False)),
                "violations": list(scope_res.get("violations", [])),
            },
            "verification": {
                "verified": (final_status == TaskState.VERIFIED.value),
                "commands_executed": [cr["command"] for cr in command_results],
                "all_passed": all_passed if command_results else (exec_res.exit_code == 0 and scope_res.get("in_scope", False)),
                "command_results": command_results,
            },
            "approval": approval_record,
        }

        self.coord.storage.write_result(run_id, result_record)

        # 10. Run summary record conforming to contracts/run.schema.json
        run_status = (
            "completed"
            if final_status in (TaskState.VERIFIED.value, TaskState.COMPLETED.value)
            else ("blocked" if final_status == TaskState.BLOCKED.value else "failed")
        )
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        intent_info = prep.get("intent_record", {})
        run_summary = {
            "schema_version": "1.0",
            "run_id": run_id,
            "workflow_id": task["workflow_id"],
            "status": run_status,
            "host": intent_info.get("host") or get_host_tuple(),
            "intent": intent_info.get("intent") or {
                "target_state": run_status,
                "action": "execute_task",
                "timestamp": now_iso,
            },
            "workspace_baseline": {
                "git_commit": "untracked",
                "clean": True,
                "snapshot_hash": baseline["snapshot_hash"],
                "timestamp": prep.get("created_at", now_iso),
            },
            "active_task_id": task_id,
            "created_at": prep.get("created_at", now_iso),
            "updated_at": now_iso,
            "completed_at": now_iso,
        }
        self.coord.audit_logger.record_run_summary(run_summary)
        self.coord.telemetry.record_run_metrics(
            run_id=run_id,
            task_id=task_id,
            workflow_id=task["workflow_id"],
            runtime=resolved_rt,
            role=role,
            duration_ms=exec_res.duration_ms,
            prompt_text=handoff.get("prompt", ""),
            stdout_text=exec_res.stdout or "",
            stderr_text=exec_res.stderr or "",
            status=run_status,
            verified=(final_status == TaskState.VERIFIED.value),
            quarantined_files_count=len(quarantined_files),
        )

        # 11. Refresh workflow status and update CURRENT_OPS.md projection
        self.coord._refresh_workflow_status(task["workflow_id"])
        self.coord.projector.project(self.coord.task_manager.list_tasks())

        return result_record

    def run_workflow(
        self,
        workflow_id: str,
        *,
        max_tasks: int = 10,
    ) -> dict[str, Any]:
        """Execute eligible ready tasks sequentially in the shared workspace."""
        wf = self.coord.storage.load_workflow(workflow_id)
        if not wf:
            raise ValueError(f"Workflow '{workflow_id}' not found")

        self.coord._advance_ready_tasks(workflow_id)

        executed: list[dict[str, Any]] = []
        count = 0

        while count < max_tasks:
            tasks = self.coord.task_manager.list_tasks(workflow_id=workflow_id)
            ready_tasks = [t for t in tasks if t.get("status") == TaskState.READY.value]
            if not ready_tasks:
                break

            task_to_run = ready_tasks[0]
            task_id = task_to_run["task_id"]
            res = self.run_task(task_id)
            executed.append(res)
            count += 1

            if not res.get("verification", {}).get("verified", False):
                break

        updated_wf = self.coord.storage.load_workflow(workflow_id) or {}
        return {
            "workflow_id": workflow_id,
            "tasks_executed": len(executed),
            "results": executed,
            "workflow_status": updated_wf.get("status", wf.get("status")),
            "success": all(
                r.get("verification", {}).get("verified", False) for r in executed
            ) if executed else True,
        }

    @staticmethod
    def _format_command(cmd: str | list[str]) -> list[str]:
        if isinstance(cmd, list):
            return cmd
        if sys.platform == "win32":
            cmd_str = cmd.strip()
            if cmd_str.startswith('"') or cmd_str.startswith("'"):
                return ["powershell", "-NoProfile", "-Command", f"& {cmd_str}"]
            return ["powershell", "-NoProfile", "-Command", cmd_str]
        return ["/bin/sh", "-c", cmd]

    def _get_security_config(self) -> dict[str, Any]:
        """Read project-level security configuration from .agentic/config.json if present."""
        cfg_path = self.coord.root_dir / ".agentic" / "config.json"
        if cfg_path.is_file():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("security", {})
            except Exception:
                return {}
        return {}

    @staticmethod
    def _is_verification_command_allowed(cmd_repr: str, allowed_commands: list[str]) -> bool:
        """Check if verification command matches configured allowed_verification_commands."""
        clean = cmd_repr.strip()
        for allowed in allowed_commands:
            al = allowed.strip()
            if clean == al or clean.startswith(al + " "):
                return True
            tokens = clean.split()
            if tokens and tokens[0].lower() == al.lower():
                return True
            if al in tokens:
                return True
        return False
