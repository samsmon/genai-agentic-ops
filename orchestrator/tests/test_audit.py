"""Tests for orchestrator/governance/audit.py and contracts/run.schema.json.

Verifies:
- Append-only event logging under .agentic/audit/events.jsonl
- Querying and filtering events (event_type, task_id, limit)
- Full lifecycle event coverage
- Run record schema validation against contracts/run.schema.json
- CLI audit show command
"""
import datetime
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jsonschema import Draft7Validator

from orchestrator.cli.main import main
from orchestrator.governance.audit import AuditLogger
from orchestrator.governance.process_info import get_host_tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
RUN_SCHEMA_FILE = REPO_ROOT / "contracts" / "run.schema.json"


class TestAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.audit_logger = AuditLogger(self.root)

        with open(RUN_SCHEMA_FILE, "r", encoding="utf-8") as f:
            self.run_schema = json.load(f)
        self.run_validator = Draft7Validator(self.run_schema)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_log_events_and_retrieve(self) -> None:
        events = [
            ("submitted", "wf-01", None, None),
            ("started", "wf-01", "task-01", "run-001"),
            ("lock_acquired", "wf-01", "task-01", "run-001"),
            ("worker_completed", "wf-01", "task-01", "run-001"),
            ("scope_verified", "wf-01", "task-01", "run-001"),
            ("verification_passed", "wf-01", "task-01", "run-001"),
            ("approval_granted", "wf-01", "task-01", None),
            ("lock_released", "wf-01", "task-01", "run-001"),
        ]

        for ev, wf, t, r in events:
            self.audit_logger.log_event(
                ev, workflow_id=wf, task_id=t, run_id=r, details={"test": True}
            )

        # Check append-only file exists
        self.assertTrue(self.audit_logger.events_file.is_file())

        # Retrieve all events
        all_events = self.audit_logger.get_events()
        self.assertEqual(len(all_events), 8)
        self.assertEqual(all_events[0]["event"], "submitted")
        self.assertEqual(all_events[-1]["event"], "lock_released")

        # Filter by event type
        started = self.audit_logger.get_events(event_type="started")
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["task_id"], "task-01")

        # Limit
        last_three = self.audit_logger.get_events(limit=3)
        self.assertEqual(len(last_three), 3)
        self.assertEqual(last_three[-1]["event"], "lock_released")

    def test_run_summary_validation_and_persistence(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        valid_run_record = {
            "schema_version": "1.0",
            "run_id": "run-abc123456789",
            "workflow_id": "wf-arch-bootstrap",
            "status": "completed",
            "host": get_host_tuple(),
            "intent": {
                "target_state": "completed",
                "action": "execute_task",
                "timestamp": now,
            },
            "workspace_baseline": {
                "git_commit": "untracked",
                "clean": True,
                "snapshot_hash": "a" * 64,
                "timestamp": now,
            },
            "active_task_id": "task-001",
            "created_at": now,
            "updated_at": now,
            "completed_at": now,
        }

        # Validate against schema
        errors = list(self.run_validator.iter_errors(valid_run_record))
        self.assertEqual(errors, [], msg=f"Schema validation failed: {errors}")

        # Save via AuditLogger
        path = self.audit_logger.record_run_summary(valid_run_record)
        self.assertTrue(path.is_file())

        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["run_id"], "run-abc123456789")

    def test_invalid_run_summary_rejected(self) -> None:
        invalid_run_record = {
            "schema_version": "1.0",
            "run_id": "invalid-run-name!",  # violates pattern
            "workflow_id": "wf-01",
            "status": "unknown_status",    # violates enum
        }
        with self.assertRaises(ValueError):
            self.audit_logger.record_run_summary(invalid_run_record)

    def test_cli_audit_show(self) -> None:
        self.audit_logger.log_event("submitted", workflow_id="wf-01")
        self.audit_logger.log_event("started", workflow_id="wf-01", task_id="task-01")

        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                main(["--root", str(self.root), "audit", "show", "--limit", "10"])
            except SystemExit:
                pass
        env = json.loads(buf.getvalue())
        self.assertTrue(env["ok"])
        self.assertEqual(env["data"]["count"], 2)


if __name__ == "__main__":
    unittest.main()
