"""Regression tests for gaps found by the fault-injection run (genai-ops-research repository).

Verifies:
- A leading dot in an allowed path is kept (``.github/`` is not turned into ``github``)
- Git hooks, git config, the orchestrator config and approval records are watched
  even though their folders are otherwise ignored, and a rollback restores them
- A budget config that is a directory fails closed and the refusal is written to the audit log
- A lock file that is not valid UTF-8 is treated as corrupt (stale), not as a crash
"""
import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.governance.lock import LockManager
from orchestrator.governance.protected_paths import normalize_scope_path
from orchestrator.governance.quarantine import WorkspaceQuarantine
from orchestrator.governance.scope_check import ScopeChecker, descend_dirs, is_watched_internal


class TestNormalizeScopePath(unittest.TestCase):
    def test_keeps_leading_dot_of_names(self) -> None:
        self.assertEqual(normalize_scope_path(".github/"), ".github")
        self.assertEqual(normalize_scope_path("./.github/workflows"), ".github/workflows")
        self.assertEqual(normalize_scope_path(".claude\\settings.json"), ".claude/settings.json")

    def test_root_forms_become_empty(self) -> None:
        for p in (".", "./", "/", ""):
            self.assertEqual(normalize_scope_path(p), "")

    def test_trailing_and_redundant_parts(self) -> None:
        self.assertEqual(normalize_scope_path("src/."), "src")
        self.assertEqual(normalize_scope_path("./src//"), "src")
        self.assertEqual(normalize_scope_path("src/app.py"), "src/app.py")


class _Workspace(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.files = {
            "src/app.py": "a\n",
            ".github/workflows/ci.yml": "ci\n",
            ".git/config": "[core]\n",
            ".git/hooks/pre-commit": "#!/bin/sh\nexit 0\n",
            ".git/objects/aa/bb": "object\n",
            ".agentic/config.json": "{}\n",
            ".agentic/approvals/t1.json": "{}\n",
            ".agentic/runs/r1/log.txt": "log\n",
        }
        for rel, text in self.files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self.checker = ScopeChecker(self.root)
        self.base = self.checker.capture_snapshot()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def verify(self, allowed: list[str]) -> dict:
        diff = self.checker.compute_diff(self.base)
        return self.checker.verify_scope(diff, allowed_paths=allowed, protected_paths=[])


class TestScope(_Workspace):
    def test_dot_directory_allowed_path_is_not_a_false_block(self) -> None:
        (self.root / ".github/workflows/ci.yml").write_text("changed\n", encoding="utf-8")
        self.assertTrue(self.verify([".github/workflows/"])["in_scope"])

    def test_change_outside_dot_directory_is_still_blocked(self) -> None:
        (self.root / "src/app.py").write_text("changed\n", encoding="utf-8")
        self.assertFalse(self.verify([".github/"])["in_scope"])

    def test_watched_internal_files_are_in_the_snapshot(self) -> None:
        files = set(self.base["files"])
        self.assertIn(".git/hooks/pre-commit", files)
        self.assertIn(".git/config", files)
        self.assertIn(".agentic/config.json", files)
        self.assertIn(".agentic/approvals/t1.json", files)
        self.assertNotIn(".git/objects/aa/bb", files)
        self.assertNotIn(".agentic/runs/r1/log.txt", files)

    def test_hook_change_is_a_violation_even_if_src_is_allowed(self) -> None:
        (self.root / ".git/hooks/pre-commit").write_text("#!/bin/sh\nrm -rf x\n", encoding="utf-8")
        res = self.verify(["src/"])
        self.assertFalse(res["in_scope"])
        self.assertTrue(any(".git/hooks/pre-commit" in v for v in res["violations"]))

    def test_new_hook_and_config_changes_are_violations(self) -> None:
        (self.root / ".git/hooks/post-commit").write_text("x\n", encoding="utf-8")
        (self.root / ".agentic/config.json").write_text('{"budget": null}\n', encoding="utf-8")
        res = self.verify(["src/"])
        self.assertFalse(res["in_scope"])
        self.assertGreaterEqual(len(res["violations"]), 2)

    def test_internal_noise_is_still_ignored(self) -> None:
        (self.root / ".git/objects/aa/bb").write_text("other\n", encoding="utf-8")
        (self.root / ".agentic/runs/r1/log.txt").write_text("more\n", encoding="utf-8")
        self.assertTrue(self.verify(["src/"])["in_scope"])

    def test_helpers(self) -> None:
        self.assertTrue(is_watched_internal(".git/hooks/x"))
        self.assertFalse(is_watched_internal(".git/objects/x"))
        self.assertEqual(descend_dirs("", [".git", "src", "__pycache__", ".tmp.x"]), [".git", "src"])
        self.assertEqual(descend_dirs(".git", ["hooks", "objects", "refs"]), ["hooks"])
        self.assertEqual(descend_dirs(".agentic", ["approvals", "runs"]), ["approvals"])


class TestQuarantineRestoresWatchedFiles(_Workspace):
    def test_rollback_restores_a_tampered_hook(self) -> None:
        quarantine = WorkspaceQuarantine(self.root)
        backup = quarantine.capture_backup()
        self.assertIn(".git/hooks/pre-commit", backup)
        hook = self.root / ".git/hooks/pre-commit"
        original = hook.read_text(encoding="utf-8")
        hook.write_text("#!/bin/sh\nevil\n", encoding="utf-8")
        diff = self.checker.compute_diff(self.base)
        quarantine.quarantine_and_rollback(
            run_id="r-test", diff=diff, allowed_paths=["src/"], protected_paths=[], backup=backup,
        )
        self.assertEqual(hook.read_text(encoding="utf-8"), original)


class TestBudgetConfigDirectory(unittest.TestCase):
    def test_directory_config_fails_closed_and_is_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coord = OrchestratorCoordinator(root)
            (root / ".agentic" / "config.json").mkdir(parents=True, exist_ok=True)
            task = {"task_id": "t1", "workflow_id": "w1", "role": "developer"}
            with self.assertRaises(ValueError):
                coord.budget.admit(task)
            events = (root / ".agentic" / "audit" / "events.jsonl").read_text(encoding="utf-8").splitlines()
            names = [json.loads(line)["event"] for line in events if line.strip()]
            self.assertIn("budget_config_invalid", names)


class TestCorruptLock(unittest.TestCase):
    def test_non_utf8_lock_is_stale_not_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lm = LockManager(Path(tmp))
            lm.lock_file.write_bytes(b"\xff\xfe\x00bad")
            self.assertIsNone(lm.read_lock())
            stale, _reason = lm.is_stale()
            self.assertTrue(stale)
            self.assertTrue(lm.break_stale_lock())
            lm.acquire("t1", "w1")
            lm.release()


if __name__ == "__main__":
    unittest.main()
