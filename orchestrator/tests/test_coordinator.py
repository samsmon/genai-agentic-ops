"""Tests for orchestrator/core/coordinator.py.

Verifies:
- End-to-end plan submission and task registration
- Task execution preparation (advisory lock, intent log, baseline snapshot)
- Task execution completion (result log, lock release)
- Governance verification (in-scope -> verified, out-of-scope -> blocked)
- Human approval granting downstream DAG task readiness
- Crash recovery detection for orphaned intent logs
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.state_machine import TaskState

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
VALID_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.valid.json"


class TestCoordinator(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)

        with open(VALID_FIXTURE, "r", encoding="utf-8") as f:
            self.plan = json.load(f)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_submit_plan_and_advance(self) -> None:
        # Submit plan with approval_required=False so it automatically approves & readies initial tasks
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        res = self.coord.submit_plan(p)
        self.assertEqual(res["status"], "approved")

        # Check tasks registered
        tasks = self.coord.task_manager.list_tasks(workflow_id=p["workflow_id"])
        self.assertEqual(len(tasks), len(p["tasks"]))

        # First task (no dependencies) should be in READY state
        t1 = self.coord.task_manager.get_task(p["tasks"][0]["task_id"])
        self.assertIsNotNone(t1)
        self.assertEqual(t1["status"], TaskState.READY.value)

    def test_task_lifecycle_flow(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t2 = copy.deepcopy(p["tasks"][0])
        t2["task_id"] = "task-002"
        t2["depends_on"] = [p["tasks"][0]["task_id"]]
        p["tasks"].append(t2)
        self.coord.submit_plan(p)

        t1_id = p["tasks"][0]["task_id"]

        # 1. Prepare execution (acquires lock, logs intent, takes baseline)
        prep = self.coord.prepare_task_execution(t1_id)
        run_id = prep["run_id"]
        self.assertIsNotNone(run_id)
        self.assertTrue(self.coord.lock_manager.lock_file.exists())
        self.assertIsNotNone(self.coord.storage.load_intent(run_id))

        t1 = self.coord.task_manager.get_task(t1_id)
        self.assertEqual(t1["status"], TaskState.RUNNING.value)

        # 2. Worker exits (writes result, releases lock)
        comp = self.coord.complete_task_execution(t1_id, run_id, exit_code=0)
        self.assertEqual(comp["status"], "completed")
        self.assertFalse(self.coord.lock_manager.lock_file.exists())
        self.assertIsNotNone(self.coord.storage.load_result(run_id))

        t1 = self.coord.task_manager.get_task(t1_id)
        self.assertEqual(t1["status"], TaskState.COMPLETED.value)

        # 3. Governance verification
        v_res = self.coord.verify_task(t1_id, prep["baseline"], verification_passed=True)
        self.assertTrue(v_res["in_scope"])
        t1 = self.coord.task_manager.get_task(t1_id)
        self.assertEqual(t1["status"], TaskState.VERIFIED.value)

        # 4. Human approval (unlocks downstream task)
        app_res = self.coord.approve_task(t1_id)
        self.assertEqual(app_res["status"], "approved")
        t1 = self.coord.task_manager.get_task(t1_id)
        self.assertEqual(t1["status"], TaskState.APPROVED.value)

        # Downstream task should now be ready
        t2_id = "task-002"
        t2_loaded = self.coord.task_manager.get_task(t2_id)
        self.assertEqual(t2_loaded["status"], TaskState.READY.value)

    def test_out_of_scope_diff_blocks_task(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        self.coord.submit_plan(p)

        t1_id = p["tasks"][0]["task_id"]
        prep = self.coord.prepare_task_execution(t1_id)

        # Worker writes an out-of-scope file
        (self.root / "malicious.js").write_text("evil()", encoding="utf-8")

        self.coord.complete_task_execution(t1_id, prep["run_id"], exit_code=0)
        v_res = self.coord.verify_task(t1_id, prep["baseline"], verification_passed=True)
        self.assertFalse(v_res["in_scope"])

        t1 = self.coord.task_manager.get_task(t1_id)
        self.assertEqual(t1["status"], TaskState.BLOCKED.value)

    def test_crash_recovery(self) -> None:
        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        self.coord.submit_plan(p)

        t1_id = p["tasks"][0]["task_id"]
        prep = self.coord.prepare_task_execution(t1_id)
        run_id = prep["run_id"]

        # Simulate dead host process in intent file and lock file
        intent = self.coord.storage.load_intent(run_id)
        intent["task_id"] = t1_id
        intent["host"]["pid"] = 999999
        intent["host"]["process_start_time"] = "dead-start-time"
        self.coord.storage.write_intent(run_id, intent)

        # Update lock to reflect dead PID
        lock = self.coord.lock_manager.read_lock()
        lock["host"]["pid"] = 999999
        lock["host"]["process_start_time"] = "dead-start-time"
        with open(self.coord.lock_manager.lock_file, "w", encoding="utf-8") as f:
            json.dump(lock, f)

        # Run crash recovery
        reconciled = self.coord.detect_and_recover_crashes()
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0]["task_id"], t1_id)

        t1 = self.coord.task_manager.get_task(t1_id)
        self.assertEqual(t1["status"], TaskState.NEEDS_RECOVERY.value)
        self.assertFalse(self.coord.lock_manager.lock_file.exists())


if __name__ == "__main__":
    unittest.main()
