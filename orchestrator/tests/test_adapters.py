"""Tests for runtime adapters, process runner, environment sanitization, and role restrictions."""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from orchestrator.adapters.antigravity import AntigravityAdapter
from orchestrator.adapters.base import AgentAdapter, ExecutionResult, MaturityLevel
from orchestrator.adapters.claude_code import ClaudeCodeAdapter
from orchestrator.adapters.codex import CodexAdapter
from orchestrator.adapters.gemini_cli import GeminiCliAdapter
from orchestrator.adapters.process_runner import (
    DEFAULT_MAX_OUTPUT_BYTES,
    ProcessRunner,
    cap_output_string,
    sanitize_environment,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "adapters"


class TestProcessRunner(unittest.TestCase):
    """Test process execution, environment sanitization, timeout, and output capping."""

    def setUp(self) -> None:
        self.runner = ProcessRunner()

    def test_basic_execution(self) -> None:
        cmd = [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('out'); sys.stderr.write('err')",
        ]
        res = self.runner.run(cmd)
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(res.status, "completed")
        self.assertEqual(res.stdout, "out")
        self.assertEqual(res.stderr, "err")
        self.assertGreater(res.duration_seconds, 0.0)
        self.assertGreater(res.duration_ms, 0)

    def test_environment_sanitization_strips_anthropic_api_key(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-leaked-key"}):
            # 1. Default should strip ANTHROPIC_API_KEY
            sanitized = sanitize_environment()
            self.assertNotIn("ANTHROPIC_API_KEY", sanitized)

            # 2. ProcessRunner should not leak ANTHROPIC_API_KEY to child
            cmd = [
                sys.executable,
                "-c",
                "import os; print(os.environ.get('ANTHROPIC_API_KEY', 'NONE'))",
            ]
            res = self.runner.run(cmd)
            self.assertEqual(res.stdout.strip(), "NONE")

            # 3. Explicit override should be preserved
            override = sanitize_environment(env_overrides={"ANTHROPIC_API_KEY": "sk-ant-explicit"})
            self.assertEqual(override.get("ANTHROPIC_API_KEY"), "sk-ant-explicit")

    def test_output_capping(self) -> None:
        long_str = "A" * 100
        capped = cap_output_string(long_str, max_bytes=30)
        self.assertTrue(capped.startswith("A" * 30))
        self.assertIn("[output truncated at 30 bytes]", capped)

    def test_timeout_and_process_cleanup(self) -> None:
        cmd = [
            sys.executable,
            "-c",
            "import time; time.sleep(10)",
        ]
        res = self.runner.run(cmd, timeout_seconds=0.2)
        self.assertEqual(res.status, "timed_out")
        self.assertEqual(res.exit_code, -1)


class TestAdapters(unittest.TestCase):
    """Test concrete adapters, protocol adherence, command generation, and role restrictions."""

    def test_protocol_compliance(self) -> None:
        adapters = [
            ClaudeCodeAdapter(),
            AntigravityAdapter(),
            GeminiCliAdapter(),
            CodexAdapter(),
        ]
        for adapter in adapters:
            self.assertIsInstance(adapter, AgentAdapter)
            self.assertTrue(len(adapter.name) > 0)
            self.assertTrue(len(adapter.runtime) > 0)
            self.assertTrue(len(adapter.command) > 0)
            self.assertIsInstance(adapter.maturity, MaturityLevel)
            caps = adapter.capabilities()
            self.assertIn("streaming", caps)
            self.assertIn("resume", caps)
            self.assertIn("interrupt", caps)
            self.assertIn("permission_modes", caps)
            self.assertIn("output_format", caps)

    def test_claude_reviewer_restrictions_and_fixtures(self) -> None:
        mock_runner = MagicMock(spec=ProcessRunner)
        success_content = (FIXTURES_DIR / "claude_success.json").read_text(encoding="utf-8")
        mock_runner.run.return_value = ExecutionResult(
            exit_code=0, status="completed", stdout=success_content
        )

        adapter = ClaudeCodeAdapter(runner=mock_runner)

        # 1. Reviewer role enforces --disallowedTools Edit,Write
        task_rev = {"role": "reviewer", "prompt": "Review this PR"}
        res = adapter.execute(task_rev, {})
        call_kwargs = mock_runner.run.call_args[1]
        cmd = call_kwargs["command"]
        self.assertIn("--disallowedTools", cmd)
        idx = cmd.index("--disallowedTools")
        self.assertEqual(cmd[idx + 1], "Edit,Write")
        self.assertEqual(res.session_id, "claude-sess-test-001")
        self.assertEqual(res.status, "completed")

        # 2. Developer role does NOT pass disallowedTools
        task_dev = {"role": "developer", "prompt": "Write code"}
        adapter.execute(task_dev, {})
        cmd2 = mock_runner.run.call_args[1]["command"]
        self.assertNotIn("--disallowedTools", cmd2)

        # 3. Blocked permission fixture maps status to blocked
        blocked_content = (FIXTURES_DIR / "claude_blocked_permission.json").read_text(encoding="utf-8")
        mock_runner.run.return_value = ExecutionResult(
            exit_code=1, status="failed", stdout=blocked_content
        )
        res_blocked = adapter.execute(task_dev, {})
        self.assertEqual(res_blocked.status, "blocked")
        self.assertIn("Edit(docs/CURRENT_OPS.md) denied by user", res_blocked.permission_denials)

    def test_antigravity_adapter(self) -> None:
        mock_runner = MagicMock(spec=ProcessRunner)
        agy_content = (FIXTURES_DIR / "agy_success.json").read_text(encoding="utf-8")
        mock_runner.run.return_value = ExecutionResult(
            exit_code=0, status="completed", stdout=agy_content
        )

        adapter = AntigravityAdapter(runner=mock_runner)

        # Reviewer mode enforces --mode plan
        task_rev = {"role": "reviewer", "prompt": "Verify plan"}
        res = adapter.execute(task_rev, {})
        cmd = mock_runner.run.call_args[1]["command"]
        self.assertIn("--mode", cmd)
        self.assertIn("plan", cmd)
        self.assertEqual(res.session_id, "agy-conv-test-999")

        # Resume support
        adapter.resume("agy-conv-test-999", "Next step")
        cmd_resume = mock_runner.run.call_args[1]["command"]
        self.assertIn("--conversation", cmd_resume)
        self.assertIn("agy-conv-test-999", cmd_resume)

    def test_gemini_adapter(self) -> None:
        mock_runner = MagicMock(spec=ProcessRunner)
        gemini_content = (FIXTURES_DIR / "gemini_success.json").read_text(encoding="utf-8")
        mock_runner.run.return_value = ExecutionResult(
            exit_code=0, status="completed", stdout=gemini_content
        )

        adapter = GeminiCliAdapter(runner=mock_runner)

        # Reviewer mode enforces --approval-mode plan
        task_rev = {"role": "reviewer", "prompt": "Audit"}
        res = adapter.execute(task_rev, {})
        cmd = mock_runner.run.call_args[1]["command"]
        self.assertIn("--approval-mode", cmd)
        self.assertIn("plan", cmd)
        self.assertEqual(res.session_id, "gemini-sess-test-456")

    def test_codex_adapter(self) -> None:
        mock_runner = MagicMock(spec=ProcessRunner)
        codex_content = (FIXTURES_DIR / "codex_success.txt").read_text(encoding="utf-8")
        mock_runner.run.return_value = ExecutionResult(
            exit_code=0, status="completed", stdout=codex_content
        )

        adapter = CodexAdapter(runner=mock_runner)
        self.assertEqual(adapter.maturity, MaturityLevel.FIXTURE_TESTED)
        res = adapter.execute({"prompt": "Hello codex"}, {})
        self.assertEqual(res.status, "completed")
        self.assertIn("Codex execution completed successfully.", res.stdout)

        # Resume should indicate unsupported
        res_resume = adapter.resume("handle", "msg")
        self.assertEqual(res_resume.status, "failed")


if __name__ == "__main__":
    unittest.main()
