"""Tests for orchestrator/governance/scope_check.py and protected_paths.py.

Verifies:
- Baseline filesystem snapshotting
- Diff computation (modified, added, deleted files)
- Allowed paths scoping
- Built-in non-overridable protected paths enforcement
- Directory traversal rejection
"""
import tempfile
import unittest
from pathlib import Path

from orchestrator.governance.protected_paths import (
    canonicalize_path,
    check_path_overlap_with_protected,
    is_protected_path,
)
from orchestrator.governance.scope_check import ScopeChecker


class TestScopeCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.checker = ScopeChecker(self.root)

        # Seed files
        (self.root / "src").mkdir(parents=True)
        (self.root / "src" / "app.py").write_text("print('app')", encoding="utf-8")
        (self.root / "README.md").write_text("# Title", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=123", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_canonicalize_and_traversal(self) -> None:
        p = canonicalize_path("src/app.py", self.root)
        self.assertEqual(p, "src/app.py")

        with self.assertRaises(ValueError):
            canonicalize_path("../escape.txt", self.root)

    def test_protected_paths_detection(self) -> None:
        is_prot, name = is_protected_path(".git/HEAD")
        self.assertTrue(is_prot)
        self.assertEqual(name, ".git")

        is_prot, name = is_protected_path("RULES.md")
        self.assertTrue(is_prot)

        is_prot, name = is_protected_path("kit/core/policy.py")
        self.assertTrue(is_prot)

        is_prot, _ = is_protected_path("src/index.ts")
        self.assertFalse(is_prot)

    def test_protected_overlap_rejection(self) -> None:
        conflicts = check_path_overlap_with_protected(["/"])
        self.assertTrue(len(conflicts) > 0)

        conflicts = check_path_overlap_with_protected(["RULES.md"])
        self.assertTrue(len(conflicts) > 0)

        conflicts = check_path_overlap_with_protected(["kit/new_file.py"])
        self.assertTrue(len(conflicts) > 0)

        clean = check_path_overlap_with_protected(["src/", "docs/notes.md"])
        self.assertEqual(len(clean), 0)

    def test_baseline_and_diff(self) -> None:
        baseline = self.checker.capture_snapshot()
        self.assertIn("snapshot_hash", baseline)
        self.assertEqual(baseline["file_count"], 3)  # src/app.py, README.md, .env

        # Mutate workspace: modify app.py, add src/utils.py, delete README.md
        (self.root / "src" / "app.py").write_text("print('modified')", encoding="utf-8")
        (self.root / "src" / "utils.py").write_text("def util(): pass", encoding="utf-8")
        (self.root / "README.md").unlink()

        diff = self.checker.compute_diff(baseline)
        self.assertIn("src/app.py", diff["changed_files"])
        self.assertIn("src/utils.py", diff["added_files"])
        self.assertIn("README.md", diff["deleted_files"])

    def test_scope_verification_in_scope(self) -> None:
        baseline = self.checker.capture_snapshot()
        (self.root / "src" / "app.py").write_text("v2", encoding="utf-8")

        diff = self.checker.compute_diff(baseline)
        res = self.checker.verify_scope(diff, allowed_paths=["src/"])
        self.assertTrue(res["in_scope"])
        self.assertEqual(len(res["violations"]), 0)

    def test_scope_verification_out_of_scope(self) -> None:
        baseline = self.checker.capture_snapshot()
        (self.root / "src" / "app.py").write_text("v2", encoding="utf-8")
        (self.root / "unauthorized.txt").write_text("bad", encoding="utf-8")

        diff = self.checker.compute_diff(baseline)
        res = self.checker.verify_scope(diff, allowed_paths=["src/"])
        self.assertFalse(res["in_scope"])
        self.assertTrue(any("unauthorized.txt" in v for v in res["violations"]))

    def test_scope_verification_protected_path_violation(self) -> None:
        baseline = self.checker.capture_snapshot()
        (self.root / "RULES.md").write_text("# Malicious overwrite", encoding="utf-8")

        diff = self.checker.compute_diff(baseline)
        res = self.checker.verify_scope(diff, allowed_paths=["RULES.md"])
        self.assertFalse(res["in_scope"])
        self.assertTrue(any("Protected path modified" in v for v in res["violations"]))


if __name__ == "__main__":
    unittest.main()
