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

import sys
from pathlib import Path
from typing import Any

from orchestrator.adapters.base import ExecutionResult
from orchestrator.adapters.process_runner import ProcessRunner
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.state_machine import ActorRole, TaskState
from orchestrator.core.workflow_engine import WorkflowEngine


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
        adapter = self.coord.registry.get_adapter(runtime)
        if not adapter:
            raise ValueError(f"No runtime adapter registered for runtime '{runtime}'")

        # 2. Prepare execution (advisory lock, baseline snapshot, intent log)
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
        else:
            self.coord.task_manager.update_task_status(
                task_id, TaskState.FAILED, ActorRole.WORKER
            )

        # 4. Post-run diff verification (snapshot captured prior to verification commands)
        diff = self.coord.scope_checker.compute_diff(baseline)
        scope_res = self.coord.scope_checker.verify_scope(
            diff,
            allowed_paths=task.get("allowed_paths", []),
            protected_paths=task.get("protected_paths", []),
        )

        # 5. Verification commands execution
        command_results: list[dict[str, Any]] = []
        all_passed = True

        if exec_res.exit_code == 0 and exec_res.status != "blocked" and scope_res.get("in_scope", False):
            ver_commands = task.get("verification_commands") or []
            for cmd in ver_commands:
                cmd_list = self._format_command(cmd)
                v_res = self.runner.run(
                    command=cmd_list,
                    cwd=self.coord.root_dir,
                    timeout_seconds=60,
                )
                passed = (v_res.exit_code == 0)
                snippet = (v_res.stdout + "\n" + v_res.stderr).strip()[:500]
                command_results.append({
                    "command": cmd,
                    "exit_code": v_res.exit_code,
                    "passed": passed,
                    "output_snippet": snippet or ("Passed" if passed else "Failed"),
                })
                if not passed:
                    all_passed = False
                    break
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

        # 8. Result record conforming to contracts/result.schema.json
        result_record = {
            "schema_version": "1.0",
            "task_id": task_id,
            "workflow_id": task["workflow_id"],
            "runtime": task.get("runtime", runtime),
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
            "approval": {
                "required": True,
                "status": "pending",
            },
        }

        self.coord.storage.write_result(run_id, result_record)
        self.coord._refresh_workflow_status(task["workflow_id"])
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
