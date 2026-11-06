"""Tests for orchestrator/governance/policy_bridge.py.

Verifies:
- Direct library integration with kit.core.policy
- Rejection of destructive verification commands (git push --force, rm -rf, reset --hard, clean -f, branch -D)
- Rejection of security violations (sleep loops, identity tampering, agent trailers, hook bypasses)
- Acceptance of safe verification commands (pytest, unittest, npm test)
- Batch command validation
"""
import unittest
from pathlib import Path

from orchestrator.governance.policy_bridge import PolicyBridge

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


class TestPolicyBridge(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = PolicyBridge(REPO_ROOT)

    def test_safe_commands_allowed(self) -> None:
        safe_commands = [
            "pytest -v",
            "python -m unittest discover",
            "npm test",
            "cargo test",
            "flake8 src/",
            "mypy orchestrator/",
            "echo 'checks passed'",
        ]
        for cmd in safe_commands:
            valid, msg = self.bridge.validate_verification_command(cmd)
            self.assertTrue(valid, msg=f"Safe command rejected: {cmd} ({msg})")
            self.assertEqual(msg, "")

    def test_destructive_commands_blocked(self) -> None:
        destructive_commands = [
            "git push origin main --force",
            "git push --force-with-lease origin main",
            "git reset --hard HEAD~1",
            "git clean -fd",
            "git branch -D feature",
            "rm -rf /tmp/data",
            "rm -fr test_dir",
            "Remove-Item -Recurse -Force ./build",
        ]
        for cmd in destructive_commands:
            valid, msg = self.bridge.validate_verification_command(cmd)
            self.assertFalse(valid, msg=f"Destructive command should be blocked: {cmd}")
            self.assertIn("Destructive verification command blocked", msg)

    def test_security_violations_denied(self) -> None:
        denied_commands = [
            "while true; do sleep 5; done",
            "until test -f done; do sleep 2; done",
            "sleep 10 && pytest",
            "git commit --no-verify -m 'skip'",
            'git config user.name "malicious-bot"',
            "GIT_AUTHOR_NAME='bot' git commit -m 'tamper'",
            "export ALLOW_AGENT_TRAILER=1; git commit -m 'bypass'",
            '$env:SKIP_COMMIT_FORMAT = "1"; git commit -m "wip"',
        ]
        for cmd in denied_commands:
            valid, msg = self.bridge.validate_verification_command(cmd)
            self.assertFalse(valid, msg=f"Violation command should be denied: {cmd}")
            self.assertIn("denied by policy", msg)

    def test_validate_verification_commands_batch(self) -> None:
        valid_batch = ["pytest -v", "python -m unittest"]
        ok, errors = self.bridge.validate_verification_commands(valid_batch)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

        invalid_batch = ["pytest -v", "git push --force origin main", "sleep 5 && test"]
        ok, errors = self.bridge.validate_verification_commands(invalid_batch)
        self.assertFalse(ok)
        self.assertEqual(len(errors), 2)

    def test_evaluate_read(self) -> None:
        # Large file without offset/limit
        dec, msg = self.bridge.evaluate_read("large_file.json", size=50_000, limited=False)
        self.assertEqual(dec, "deny")

        # Large file with limit
        dec, msg = self.bridge.evaluate_read("large_file.json", size=50_000, limited=True)
        self.assertEqual(dec, "allow")


if __name__ == "__main__":
    unittest.main()
