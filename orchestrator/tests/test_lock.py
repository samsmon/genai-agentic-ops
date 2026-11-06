"""Tests for orchestrator/governance/lock.py.

Verifies:
- Advisory lock acquisition via atomic creation
- Lock rejection when actively held
- Lock release and owner validation
- Stale lock diagnosis (dead PID and TTL expiration)
- Safe stale lock breaking
"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.governance.lock import (
    LockAcquisitionError,
    LockManager,
    LockReleaseError,
)
from orchestrator.governance.process_info import get_hostname, get_host_tuple


class TestLockManager(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.locks_dir = Path(self.temp_dir.name)
        self.lock_mgr = LockManager(self.locks_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_acquire_and_release(self) -> None:
        lock_data = self.lock_mgr.acquire(task_id="task-101", workflow_id="wf-01")
        self.assertTrue(self.lock_mgr.lock_file.is_file())
        self.assertEqual(lock_data["task_id"], "task-101")
        self.assertEqual(lock_data["workflow_id"], "wf-01")
        self.assertIn("process_start_time", lock_data["host"])

        # Release as owner
        self.lock_mgr.release()
        self.assertFalse(self.lock_mgr.lock_file.exists())

    def test_double_acquire_fails(self) -> None:
        self.lock_mgr.acquire(task_id="task-1", workflow_id="wf-1")
        with self.assertRaises(LockAcquisitionError):
            self.lock_mgr.acquire(task_id="task-2", workflow_id="wf-1")

    def test_unauthorized_release_fails(self) -> None:
        # Create a lock owned by a different process
        foreign_lock = {
            "schema_version": "1.0",
            "lock_id": "lock-foreign",
            "task_id": "task-99",
            "workflow_id": "wf-99",
            "host": {
                "hostname": get_hostname(),
                "pid": 999999,
                "process_start_time": "bogus-start-time",
            },
            "acquired_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ttl_seconds": 7200,
        }
        with open(self.lock_mgr.lock_file, "w", encoding="utf-8") as f:
            json.dump(foreign_lock, f)

        with self.assertRaises(LockReleaseError):
            self.lock_mgr.release(force=False)

        # Force release should succeed
        self.lock_mgr.release(force=True)
        self.assertFalse(self.lock_mgr.lock_file.exists())

    def test_stale_lock_detection_dead_pid(self) -> None:
        # Lock held by non-existent PID
        dead_lock = {
            "schema_version": "1.0",
            "lock_id": "lock-dead",
            "task_id": "task-dead",
            "workflow_id": "wf-dead",
            "host": {
                "hostname": get_hostname(),
                "pid": 999999,
                "process_start_time": "12345",
            },
            "acquired_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "ttl_seconds": 7200,
        }
        with open(self.lock_mgr.lock_file, "w", encoding="utf-8") as f:
            json.dump(dead_lock, f)

        stale, reason = self.lock_mgr.is_stale()
        self.assertTrue(stale)
        self.assertIn("terminated", reason)

        # Breaking stale lock removes it
        broken = self.lock_mgr.break_stale_lock()
        self.assertTrue(broken)
        self.assertFalse(self.lock_mgr.lock_file.exists())

    def test_stale_lock_detection_expired_ttl(self) -> None:
        # Lock held by current process but expired TTL
        host_info = get_host_tuple()
        past = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=500)
        ).isoformat()
        expired_lock = {
            "schema_version": "1.0",
            "lock_id": "lock-exp",
            "task_id": "task-exp",
            "workflow_id": "wf-exp",
            "host": host_info,
            "acquired_at": past,
            "ttl_seconds": 100,  # Expired
        }
        with open(self.lock_mgr.lock_file, "w", encoding="utf-8") as f:
            json.dump(expired_lock, f)

        stale, reason = self.lock_mgr.is_stale()
        self.assertTrue(stale)
        self.assertIn("TTL exceeded", reason)


if __name__ == "__main__":
    unittest.main()
