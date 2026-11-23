"""Tests for the operator cancel command and the timeout on verification commands.

Verifies:
- A verification command is limited by the task timeout, never above the fixed cap
- A verification command that runs too long is stopped and the task is blocked
- cancel_task moves a ready or running task to cancelled and writes an audit event
- A running task whose lock names another live process has that process tree stopped
- A finished (approved or cancelled) or unknown task cannot be cancelled
- `agentic task cancel` returns a JSON envelope
"""
import copy
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from orchestrator.cli.main import main
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import VERIFICATION_TIMEOUT_CAP_SECONDS, TaskRunner
from orchestrator.core.state_machine import ActorRole, TaskState
from orchestrator.governance.process_info import get_hostname, get_process_start_time
from orchestrator.tests.test_runner import MockAdapter, VALID_PLAN_FIXTURE


class TestVerificationTimeout(unittest.TestCase):
    def test_limit_is_task_timeout_capped(self) -> None:
        limit = TaskRunner._verification_timeout
        self.assertEqual(limit({"timeout_seconds": 10}), 10.0)
        self.assertEqual(limit({"timeout_seconds": 30}), 30.0)
        self.assertEqual(limit({"timeout_seconds": 300}), VERIFICATION_TIMEOUT_CAP_SECONDS)
        self.assertEqual(limit({}), VERIFICATION_TIMEOUT_CAP_SECONDS)
        self.assertEqual(limit({"timeout_seconds": None}), VERIFICATION_TIMEOUT_CAP_SECONDS)
        self.assertEqual(limit({"timeout_seconds": "bad"}), VERIFICATION_TIMEOUT_CAP_SECONDS)

    def test_slow_verification_command_is_stopped_and_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            coord = OrchestratorCoordinator(Path(tmp))
            coord.registry.register(MockAdapter())
            with open(VALID_PLAN_FIXTURE, "r", encoding="utf-8") as f:
                plan = json.load(f)
            plan["approval_required"] = False
            spec = plan["tasks"][0]
            spec["allowed_paths"] = ["src/"]
            spec["timeout_seconds"] = 10
            spec["verification_commands"] = [f'"{sys.executable}" -c "import time; time.sleep(30)"']
            coord.submit_plan(plan)
            started = time.monotonic()
            with mock.patch("orchestrator.core.runner.VERIFICATION_TIMEOUT_CAP_SECONDS", 2.0):
                res = TaskRunner(coord).run_task(spec["task_id"])
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 20)
            self.assertFalse(res["verification"]["verified"])
            self.assertEqual(coord.task_manager.get_task(spec["task_id"])["status"], TaskState.BLOCKED.value)
            snippet = res["verification"]["command_results"][0]["output_snippet"]
            self.assertIn("Timed out", snippet)
            self.assertFalse(coord.lock_manager.lock_file.exists())


class TestCancelTask(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)
        with open(VALID_PLAN_FIXTURE, "r", encoding="utf-8") as f:
            plan = json.load(f)
        plan = copy.deepcopy(plan)
        plan["approval_required"] = False
        self.coord.submit_plan(plan)
        self.task_id = plan["tasks"][0]["task_id"]
        self.wf_id = plan["workflow_id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _status(self) -> str:
        return self.coord.task_manager.get_task(self.task_id)["status"]

    def _events(self) -> list[str]:
        f = self.root / ".agentic" / "audit" / "events.jsonl"
        lines = f.read_text(encoding="utf-8").splitlines() if f.is_file() else []
        return [json.loads(x).get("event", "") for x in lines if x.strip()]

    def _make_running(self) -> None:
        self.coord.task_manager.update_task_status(self.task_id, TaskState.RUNNING, ActorRole.ORCHESTRATOR)
        self.coord.lock_manager.acquire(self.task_id, self.wf_id)

    def test_cancel_ready_task(self) -> None:
        self.assertEqual(self._status(), TaskState.READY.value)
        res = self.coord.cancel_task(self.task_id, reason="not needed")
        self.assertEqual(res["status"], "cancelled")
        self.assertEqual(res["previous_status"], "ready")
        self.assertEqual(self._status(), TaskState.CANCELLED.value)
        self.assertIn("task_cancelled", self._events())

    def test_cancel_running_task_held_by_this_process_releases_lock(self) -> None:
        self._make_running()
        res = self.coord.cancel_task(self.task_id)
        self.assertEqual(self._status(), TaskState.CANCELLED.value)
        self.assertTrue(res["lock_released"])
        self.assertIsNone(res["stopped_pid"])  # never stops its own process
        self.assertFalse(self.coord.lock_manager.lock_file.exists())

    def test_cancel_running_task_stops_other_process_tree(self) -> None:
        self._make_running()
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        try:
            lock_path = self.coord.lock_manager.lock_file
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            data["host"] = {
                "hostname": get_hostname(),
                "pid": child.pid,
                "process_start_time": get_process_start_time(child.pid),
            }
            lock_path.write_text(json.dumps(data), encoding="utf-8")

            res = self.coord.cancel_task(self.task_id)
            self.assertEqual(res["stopped_pid"], child.pid)
            self.assertIsNotNone(child.wait(timeout=10))  # the process was stopped
            self.assertEqual(self._status(), TaskState.CANCELLED.value)
            self.assertFalse(lock_path.exists())
        finally:
            if child.poll() is None:
                child.kill()

    def test_stale_pid_is_not_stopped(self) -> None:
        self._make_running()
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        try:
            lock_path = self.coord.lock_manager.lock_file
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            data["host"] = {"hostname": get_hostname(), "pid": child.pid, "process_start_time": "not-the-start-time"}
            lock_path.write_text(json.dumps(data), encoding="utf-8")

            res = self.coord.cancel_task(self.task_id)
            self.assertIsNone(res["stopped_pid"])  # start time differs, so the pid was reused
            self.assertIsNone(child.poll())  # still running
        finally:
            child.kill()
            child.wait(timeout=10)

    def test_cannot_cancel_finished_or_unknown_task(self) -> None:
        self.coord.cancel_task(self.task_id)
        with self.assertRaises(ValueError):
            self.coord.cancel_task(self.task_id)
        with self.assertRaises(ValueError):
            self.coord.cancel_task("no-such-task")

    def test_cli_task_cancel_envelope(self) -> None:
        buf = io.StringIO()
        code = 0
        try:
            with redirect_stdout(buf):
                main(["--root", str(self.root), "task", "cancel", self.task_id, "--reason", "test"])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 0
        out = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["data"]["status"], "cancelled")
        self.assertEqual(self._status(), TaskState.CANCELLED.value)


if __name__ == "__main__":
    unittest.main()
