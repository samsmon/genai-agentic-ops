"""Tests for orchestrator/governance/projection.py.

Verifies:
- One-way projection from .agentic/state to docs/CURRENT_OPS.md
- Markdown table formatting
- Task state to operational status mapping
- Terminal row archiving when exceeding limit of 5
"""
import tempfile
import unittest
from pathlib import Path

from orchestrator.governance.projection import CurrentOpsProjector


class TestProjection(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.projector = CurrentOpsProjector(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_single_task_projection(self) -> None:
        tasks = [
            {
                "task_id": "task-001",
                "workflow_id": "wf-01",
                "title": "Build Architecture Foundation",
                "status": "running",
                "runtime": "antigravity",
                "allowed_paths": ["orchestrator/"],
                "created_at": "2026-11-06T10:00:00+00:00",
                "updated_at": "2026-11-06T10:15:00+00:00",
            }
        ]

        content = self.projector.project(tasks)
        self.assertTrue(self.projector.current_ops_file.is_file())
        self.assertIn("# CURRENT OPS — Live Task Tracker", content)
        self.assertIn("| 2026-11-06 10:15 | antigravity | task-001 | orchestrator/ | running | Build Architecture Foundation |", content)

    def test_status_mapping(self) -> None:
        tasks = [
            {"task_id": "t1", "status": "running", "title": "Run"},
            {"task_id": "t2", "status": "verified", "title": "Ver"},
            {"task_id": "t3", "status": "blocked", "title": "Blk"},
            {"task_id": "t4", "status": "failed", "title": "Fail"},
        ]
        content = self.projector.project(tasks)
        self.assertIn("| running | Run |", content)
        self.assertIn("| done | Ver |", content)
        self.assertIn("| blocked | Blk |", content)
        self.assertIn("| failed | Fail |", content)

    def test_rotation_of_terminal_rows(self) -> None:
        # Create 7 terminal tasks (status='approved' -> 'done')
        tasks = [
            {
                "task_id": f"t-{i:02d}",
                "status": "approved",
                "title": f"Done Task {i}",
                "created_at": f"2026-11-06T10:{i:02d}:00+00:00",
            }
            for i in range(1, 8)
        ]

        content = self.projector.project(tasks)

        # Main table should keep at most 5 terminal rows
        main_text = self.projector.current_ops_file.read_text(encoding="utf-8")
        done_matches = [line for line in main_text.splitlines() if "| done |" in line]
        self.assertEqual(len(done_matches), 5)

        # Older 2 rows moved to archive
        self.assertTrue(self.projector.archive_file.is_file())
        archive_text = self.projector.archive_file.read_text(encoding="utf-8")
        arch_matches = [line for line in archive_text.splitlines() if "| done |" in line]
        self.assertEqual(len(arch_matches), 2)


if __name__ == "__main__":
    unittest.main()
