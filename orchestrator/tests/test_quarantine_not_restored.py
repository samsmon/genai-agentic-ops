"""Tests that WorkspaceQuarantine reports what it could not put back.

A rollback that silently fails leaves out-of-scope changes in the working
tree while the run record says they were quarantined. The manifest must name
every such path.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.governance.quarantine import WorkspaceQuarantine


class TestQuarantineNotRestored(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.quarantine = WorkspaceQuarantine(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _manifest(self, run_id: str) -> dict:
        path = self.root / ".agentic" / "runs" / run_id / "quarantine" / "manifest.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_modified_file_without_backup_is_reported(self) -> None:
        # Stands for a file over MAX_BACKUP_FILE_BYTES: present before the
        # run, absent from the backup, then modified out of scope.
        big = self.root / "big.bin"
        big.write_text("changed by worker\n", encoding="utf-8")

        quarantined = self.quarantine.quarantine_and_rollback(
            run_id="run-1",
            diff={"all_modified": ["big.bin"], "added_files": []},
            allowed_paths=["src/"],
            protected_paths=None,
            backup={},
        )

        self.assertEqual(quarantined, ["big.bin"])
        self.assertEqual(big.read_text(encoding="utf-8"), "changed by worker\n")
        self.assertEqual(self._manifest("run-1")["not_restored"], {"big.bin": "no baseline backup"})

    def test_successful_rollback_reports_nothing(self) -> None:
        readme = self.root / "README.md"
        readme.write_text("changed by worker\n", encoding="utf-8")
        (self.root / "rogue.txt").write_text("unwanted\n", encoding="utf-8")

        quarantined = self.quarantine.quarantine_and_rollback(
            run_id="run-2",
            diff={"all_modified": ["README.md", "rogue.txt"], "added_files": ["rogue.txt"]},
            allowed_paths=["src/"],
            protected_paths=None,
            backup={"README.md": b"original\n"},
        )

        self.assertEqual(quarantined, ["README.md", "rogue.txt"])
        self.assertEqual(readme.read_bytes(), b"original\n")
        self.assertFalse((self.root / "rogue.txt").exists())
        self.assertEqual(self._manifest("run-2")["not_restored"], {})


if __name__ == "__main__":
    unittest.main()
