"""Tests for orchestrator/storage/filesystem.py.

Verifies:
- Atomic write-replace semantics
- Write-ahead intent logging and result matching
- Crash recovery detection of unmatched intents
- Workflow, Task, Plan, and Run CRUD
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from orchestrator.storage.filesystem import FileSystemStorage


class TestFileSystemStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.storage = FileSystemStorage(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_ensure_layout(self) -> None:
        self.assertTrue(self.storage.agentic_dir.is_dir())
        self.assertTrue(self.storage.state_dir.is_dir())
        self.assertTrue(self.storage.workflows_dir.is_dir())
        self.assertTrue(self.storage.tasks_dir.is_dir())
        self.assertTrue(self.storage.plans_dir.is_dir())
        self.assertTrue(self.storage.runs_dir.is_dir())
        self.assertTrue(self.storage.locks_dir.is_dir())

    def test_atomic_write_and_read(self) -> None:
        target = self.root / "test.json"
        data = {"hello": "world", "num": 42}
        self.storage.atomic_write_json(target, data)
        self.assertTrue(target.is_file())

        read_back = self.storage.read_json(target)
        self.assertEqual(read_back, data)

        # Overwrite atomically
        updated = {"hello": "updated"}
        self.storage.atomic_write_json(target, updated)
        self.assertEqual(self.storage.read_json(target), updated)

        # Ensure no temp files linger
        tmps = list(self.root.glob("*.tmp.*"))
        self.assertEqual(len(tmps), 0)

    def test_write_ahead_intent_and_result(self) -> None:
        run_id = "run-001"
        intent_data = {"task_id": "task-01", "action": "spawn"}
        result_data = {"exit_code": 0, "status": "completed"}

        self.storage.write_intent(run_id, intent_data)
        self.assertEqual(self.storage.load_intent(run_id), intent_data)

        # Initially unmatched intent -> crash detection finds it
        orphaned = self.storage.detect_orphaned_intents()
        self.assertEqual(len(orphaned), 1)
        self.assertEqual(orphaned[0]["run_id"], run_id)

        # After writing result, no longer orphaned
        self.storage.write_result(run_id, result_data)
        self.assertEqual(self.storage.load_result(run_id), result_data)
        self.assertEqual(len(self.storage.detect_orphaned_intents()), 0)

    def test_task_and_workflow_crud(self) -> None:
        wf = {"workflow_id": "wf-1", "title": "Test WF", "status": "running"}
        self.storage.save_workflow(wf)
        self.assertEqual(self.storage.load_workflow("wf-1"), wf)
        self.assertEqual(len(self.storage.list_workflows()), 1)

        t1 = {"task_id": "task-1", "workflow_id": "wf-1", "status": "pending"}
        t2 = {"task_id": "task-2", "workflow_id": "wf-1", "status": "ready"}
        self.storage.save_task(t1)
        self.storage.save_task(t2)

        self.assertEqual(self.storage.load_task("task-1"), t1)
        all_tasks = self.storage.list_tasks(workflow_id="wf-1")
        self.assertEqual(len(all_tasks), 2)

        ready_tasks = self.storage.list_tasks(workflow_id="wf-1", status="ready")
        self.assertEqual(len(ready_tasks), 1)
        self.assertEqual(ready_tasks[0]["task_id"], "task-2")

    def test_run_save_and_load_no_double_prefix(self) -> None:
        run_data = {"status": "completed", "exit_code": 0}
        # 1. run_id already starting with "run-"
        p1 = self.storage.save_run("run-abc12345", run_data)
        self.assertEqual(p1.name, "run-abc12345.json")
        loaded1 = self.storage.load_run("run-abc12345")
        self.assertEqual(loaded1, run_data)

        # 2. run_id without "run-" prefix
        p2 = self.storage.save_run("def67890", run_data)
        self.assertEqual(p2.name, "run-def67890.json")
        loaded2 = self.storage.load_run("def67890")
        self.assertEqual(loaded2, run_data)


if __name__ == "__main__":
    unittest.main()
