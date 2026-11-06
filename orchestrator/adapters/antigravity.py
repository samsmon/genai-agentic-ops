"""Antigravity CLI runtime adapter.

Implements AgentAdapter for Antigravity (`agy` CLI):
- Detects binary in PATH and %LOCALAPPDATA%\\agy\\bin\\agy.exe.
- Non-interactive headless execution via `agy -p ...` with `--output-format json`.
- Resume support via `--conversation <id>`.
- Mode setting (--mode plan) for reviewer roles.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from orchestrator.adapters.base import AgentAdapter, ExecutionResult, MaturityLevel
from orchestrator.adapters.process_runner import ProcessRunner


class AntigravityAdapter:
    """Runtime adapter for Google Antigravity CLI."""

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()

    @property
    def name(self) -> str:
        return "antigravity"

    @property
    def runtime(self) -> str:
        return "antigravity"

    @property
    def command(self) -> str:
        return "agy"

    @property
    def maturity(self) -> MaturityLevel:
        return MaturityLevel.LIVE_TESTED if self.detect() else MaturityLevel.FIXTURE_TESTED

    def find_binary(self) -> str | None:
        """Find executable path for agy CLI."""
        for candidate in ["agy", "agy.exe"]:
            found = shutil.which(candidate)
            if found:
                return found

        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            if local_appdata:
                candidate = Path(local_appdata) / "agy" / "bin" / "agy.exe"
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return str(candidate)

        return None

    def detect(self) -> bool:
        """Check if agy binary is available and executable."""
        return self.find_binary() is not None

    def capabilities(self) -> dict[str, Any]:
        """Return capabilities matching agent-registry.schema.json."""
        return {
            "streaming": False,
            "resume": "verified",
            "interrupt": "process_group",
            "permission_modes": ["default", "dangerously-skip-permissions"],
            "output_format": "json",
        }

    def execute(
        self,
        task: dict[str, Any],
        handoff: dict[str, Any],
        *,
        run_handle: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Execute task headless via agy CLI."""
        bin_path = self.find_binary() or "agy"
        prompt_text = (
            task.get("prompt")
            or handoff.get("prompt")
            or task.get("description")
            or handoff.get("task_description")
            or ""
        )

        role = task.get("role") or handoff.get("role", "developer")
        cmd = [bin_path, "-p", prompt_text, "--output-format", "json"]

        # Reviewer mode enforcement
        if role == "reviewer":
            cmd.extend(["--mode", "plan"])

        permission_mode = task.get("permission_mode") or handoff.get("permission_mode")
        if permission_mode == "dangerously-skip-permissions":
            cmd.append("--dangerously-skip-permissions")

        env_overrides = task.get("env_overrides") or handoff.get("env_overrides")

        result = self.runner.run(
            command=cmd,
            env_overrides=env_overrides,
            timeout_seconds=timeout_seconds,
            run_handle=run_handle,
        )

        self._parse_agy_output(result)
        return result

    def resume(self, run_handle: str, message: str) -> ExecutionResult:
        """Resume conversation via --conversation flag."""
        bin_path = self.find_binary() or "agy"
        cmd = [bin_path, "-p", message, "--conversation", run_handle, "--output-format", "json"]
        result = self.runner.run(command=cmd)
        self._parse_agy_output(result)
        return result

    def interrupt(self, run_handle: str) -> None:
        """Interrupt active execution."""
        self.runner.interrupt(run_handle)

    def _parse_agy_output(self, result: ExecutionResult) -> None:
        """Parse JSON stdout and extract conversation id / session metadata."""
        stdout = result.stdout.strip()
        parsed: dict[str, Any] | None = None

        if stdout:
            try:
                parsed = json.loads(stdout)
                result.raw_output = parsed
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", stdout, re.DOTALL)
                if match:
                    try:
                        parsed = json.loads(match.group(0))
                        result.raw_output = parsed
                    except json.JSONDecodeError:
                        result.raw_output = stdout
                else:
                    result.raw_output = stdout

        if isinstance(parsed, dict):
            if "conversation_id" in parsed:
                result.session_id = str(parsed["conversation_id"])
            elif "session_id" in parsed:
                result.session_id = str(parsed["session_id"])

        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "permission denied" in combined or "action rejected" in combined:
            if not result.permission_denials:
                result.permission_denials.append("Action denied by user or security policy")
            result.status = "blocked"
