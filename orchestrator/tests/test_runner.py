"""Tests for orchestrator/core/runner.py.

Verifies:
- End-to-end task execution with mock runtime adapter
- Full state transitions: ready -> running -> completed -> verified
- Result record conformance to contracts/result.schema.json
- Out-of-scope diff detection triggering BLOCKED status
- Verification command failure triggering BLOCKED status
- Worker failure (non-zero exit code) triggering FAILED status
- Sequential workflow execution across shared workspace
- Human approval granting task completion and unlocking downstream tasks
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from orchestrator.adapters.base import ExecutionResult, MaturityLevel
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import TaskRunner
from orchestrator.core.state_machine import TaskState

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
VALID_PLAN_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.valid.json"
RESULT_SCHEMA_FILE = REPO_ROOT / "contracts" / "result.schema.json"


class MockAdapter:
    """Mock runtime adapter for testing TaskRunner without external CLI dependencies."""

    def __init__(self, name: str = "antigravity", runtime: str = "antigravity") -> None:
        self._name = name
        self._runtime = runtime
        self.executed: list[dict[str, Any]] = []
        self.exit_code: int = 0
        self.status: str = "completed"
        self.stdout: str = "Mock worker output"
        self.stderr: str = ""
        self.side_effect: Any = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def runtime(self) -> str:
        return self._runtime

    @property
    def command(self) -> str:
        return "mock"

    @property
    def maturity(self) -> MaturityLevel:
        return MaturityLevel.FIXTURE_TESTED

    def detect(self) -> bool:
        return True

    def capabilities(self) -> dict[str, Any]:
        return {"streaming": False, "resume": "verified", "output_format": "json"}

    def execute(
        self,
        task: dict[str, Any],
        handoff: dict[str, Any],
        *,
        run_handle: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        self.executed.append(task)
        if callable(self.side_effect):
            self.side_effect(task, handoff)
        return ExecutionResult(
            exit_code=self.exit_code,
            status=self.status,
            stdout=self.stdout,
            stderr=self.stderr,
            session_id="mock-session-001",
            duration_seconds=0.05,
        )


class TestRunner(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)
        self.mock_adapter = MockAdapter()
        self.coord.registry.register(self.mock_adapter)
        self.runner = TaskRunner(self.coord)

        with open(VALID_PLAN_FIXTURE, "r", encoding="utf-8") as f:
            self.plan = json.load(f)

        with open(RESULT_SCHEMA_FILE, "r", encoding="utf-8") as f:
            self.result_schema = json.load(f)
        self.result_validator = Draft7Validator(self.result_schema)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_run_task_success_lifecycle(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        t_spec["verification_commands"] = [
            f'"{sys.executable}" -c "exit(0)"'
        ]

        def worker_effect(task: dict[str, Any], handoff: dict[str, Any]) -> None:
            # Worker creates in-scope file
            src_dir = self.root / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "app.py").write_text("print('hello')", encoding="utf-8")

        self.mock_adapter.side_effect = worker_effect
        self.coord.submit_plan(p)

        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        # 1. Validate result matches result.schema.json
        errors = list(self.result_validator.iter_errors(res))
        self.assertEqual(errors, [], msg=f"Result schema validation errors: {errors}")

        # 2. Verify state transitions to verified
        task = self.coord.task_manager.get_task(t_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], TaskState.VERIFIED.value)
        self.assertTrue(res["verification"]["verified"])
        self.assertTrue(res["diff"]["in_scope"])
        self.assertFalse(self.coord.lock_manager.lock_file.exists())
        self.assertFalse(self.coord.lock_manager.active_file.exists())

    def test_out_of_scope_diff_blocks_task(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]

        def bad_worker_effect(task: dict[str, Any], handoff: dict[str, Any]) -> None:
            # Worker touches unauthorized out-of-scope path
            out_dir = self.root / "unauthorized"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "leak.txt").write_text("rogue", encoding="utf-8")

        self.mock_adapter.side_effect = bad_worker_effect
        self.coord.submit_plan(p)

        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        self.assertFalse(res["diff"]["in_scope"])
        self.assertFalse(res["verification"]["verified"])
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.BLOCKED.value)
        self.assertFalse(self.coord.lock_manager.lock_file.exists())

    def test_verification_command_failure_blocks_task(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        t_spec["verification_commands"] = [
            f'"{sys.executable}" -c "import sys; sys.exit(1)"'
        ]

        self.coord.submit_plan(p)
        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        self.assertFalse(res["verification"]["verified"])
        self.assertFalse(res["verification"]["all_passed"])
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.BLOCKED.value)

    def test_worker_failure_transitions_to_failed(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_id = p["tasks"][0]["task_id"]
        self.coord.submit_plan(p)

        self.mock_adapter.exit_code = 1
        self.mock_adapter.status = "failed"
        self.mock_adapter.stderr = "Fatal compilation error"

        res = self.runner.run_task(t_id)
        self.assertEqual(res["execution"]["status"], "failed")
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.FAILED.value)

    def test_run_workflow_sequential_and_approval(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t1 = p["tasks"][0]
        t1["allowed_paths"] = ["src/"]
        t1["verification_commands"] = [f'"{sys.executable}" -c "exit(0)"']

        t2 = copy.deepcopy(t1)
        t2["task_id"] = "task-002"
        t2["depends_on"] = [t1["task_id"]]
        p["tasks"] = [t1, t2]

        self.coord.submit_plan(p)
        wf_id = p["workflow_id"]

        # Run first task
        wf_res = self.runner.run_workflow(wf_id, max_tasks=1)
        self.assertEqual(wf_res["tasks_executed"], 1)
        self.assertTrue(wf_res["results"][0]["verification"]["verified"])

        # Second task remains pending until task 1 is approved
        t2_loaded = self.coord.task_manager.get_task("task-002")
        self.assertEqual(t2_loaded["status"], TaskState.PENDING.value)

        # Human approves task 1
        self.coord.approve_task(t1["task_id"])
        t2_loaded = self.coord.task_manager.get_task("task-002")
        self.assertEqual(t2_loaded["status"], TaskState.READY.value)

        # Run workflow again, task 2 executes
        wf_res2 = self.runner.run_workflow(wf_id, max_tasks=1)
        self.assertEqual(wf_res2["tasks_executed"], 1)
        t2_loaded = self.coord.task_manager.get_task("task-002")
        self.assertEqual(t2_loaded["status"], TaskState.VERIFIED.value)

    def test_destructive_verification_command_blocked_by_policy(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        # Verification command contains a destructive action that PolicyBridge must block
        t_spec["verification_commands"] = ["git push --force origin main"]

        self.coord.submit_plan(p)
        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        self.assertFalse(res["verification"]["verified"])
        self.assertFalse(res["verification"]["all_passed"])
        cr = res["verification"]["command_results"][0]
        self.assertIn("Destructive verification command blocked", cr["output_snippet"])
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.BLOCKED.value)

    def test_anti_monolith_violation_in_worker_diff_blocks_task(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        t_spec["verification_commands"] = [f'"{sys.executable}" -c "exit(0)"']

        def bloated_worker_effect(task: dict[str, Any], handoff: dict[str, Any]) -> None:
            src_dir = self.root / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            big_code = "\n".join([f"# line {i}" for i in range(520)])
            (src_dir / "bloated.py").write_text(big_code, encoding="utf-8")

        self.mock_adapter.side_effect = bloated_worker_effect
        self.coord.submit_plan(p)
        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        self.assertFalse(res["diff"]["in_scope"])
        self.assertTrue(any("Anti-monolith violation" in v for v in res["diff"]["violations"]))
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.BLOCKED.value)

    def test_approval_gate_with_one_time_token(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = True  # requires human approval
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        t_spec["verification_commands"] = [f'"{sys.executable}" -c "exit(0)"']

        self.coord.submit_plan(p)
        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        self.assertTrue(res["verification"]["verified"])
        self.assertTrue(res["approval"]["required"])
        self.assertEqual(res["approval"]["status"], "pending")

        # Approval token was generated in .agentic/approvals/<t_id>.json
        appr_req = self.coord.approval_manager.get_approval(t_id)
        self.assertIsNotNone(appr_req)
        self.assertEqual(appr_req["status"], "pending")
        token = appr_req["token"]

        # Grant approval using ApprovalManager
        appr_res = self.coord.approval_manager.grant_approval(t_id, token, approver="alice")
        self.assertEqual(appr_res["status"], "granted")

        # Task transitions to APPROVED
        self.coord.approve_task(t_id, token=token, approver="alice")
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.APPROVED.value)

    def test_verification_command_mutating_out_of_scope_blocks_and_rolls_back(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]

        # Verification command creates an out-of-scope file (docs/rogue.txt)
        rogue_file = self.root / "docs" / "rogue.txt"
        t_spec["verification_commands"] = [
            f'"{sys.executable}" -c "import pathlib; pathlib.Path(r\'{rogue_file}\').parent.mkdir(parents=True, exist_ok=True); pathlib.Path(r\'{rogue_file}\').write_text(\'rogue\')"'
        ]

        def worker_effect(task: dict[str, Any], handoff: dict[str, Any]) -> None:
            src_dir = self.root / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / "app.py").write_text("print('hello')", encoding="utf-8")

        self.mock_adapter.side_effect = worker_effect
        self.coord.submit_plan(p)
        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        self.assertFalse(res["verification"]["verified"])
        self.assertFalse(res["verification"]["all_passed"])
        self.assertFalse(res["diff"]["in_scope"])
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.BLOCKED.value)
        # Verify rogue file was rolled back
        self.assertFalse(rogue_file.exists())

    def test_verification_command_blocked_by_security_config(self) -> None:
        # Write .agentic/config.json with allowed_verification_commands restricted to pytest
        config_dir = self.root / ".agentic"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"security": {"allowed_verification_commands": ["pytest", "npm test"]}}),
            encoding="utf-8",
        )

        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        # Verification command is python, not in allowed_verification_commands
        t_spec["verification_commands"] = [f'"{sys.executable}" -c "exit(0)"']

        self.coord.submit_plan(p)
        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        self.assertFalse(res["verification"]["verified"])
        self.assertFalse(res["verification"]["all_passed"])
        cr = res["verification"]["command_results"][0]
        self.assertIn("not allowed by security.allowed_verification_commands", cr["output_snippet"])
        task = self.coord.task_manager.get_task(t_id)
        self.assertEqual(task["status"], TaskState.BLOCKED.value)


if __name__ == "__main__":
    unittest.main()
