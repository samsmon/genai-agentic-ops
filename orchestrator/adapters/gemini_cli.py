"""Gemini CLI runtime adapter.

Implements AgentAdapter for Google Gemini CLI (`gemini`):
- Detects binary via PATH and npm global locations.
- Headless execution via `gemini -p ...` with `--output-format json`.
- Enforces approval mode (`--approval-mode plan`) for reviewer roles.
- Resume support via `-r` / `--resume`.
- Extracts session identifiers and checks for permission denial events.
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


class GeminiCliAdapter:
    """Runtime adapter for Google Gemini CLI."""

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()

    @property
    def name(self) -> str:
        return "gemini-cli"

    @property
    def runtime(self) -> str:
        return "gemini-cli"

    @property
    def command(self) -> str:
        return "gemini"

    @property
    def maturity(self) -> MaturityLevel:
        return MaturityLevel.LIVE_TESTED if self.detect() else MaturityLevel.FIXTURE_TESTED

    def find_binary(self) -> str | None:
        """Find executable path for gemini CLI."""
        for candidate in ["gemini", "gemini.cmd", "gemini.exe"]:
            found = shutil.which(candidate)
            if found:
                return found

        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                npm_cmd = Path(appdata) / "npm" / "gemini.cmd"
                if npm_cmd.is_file():
                    return str(npm_cmd)
                npm_ps1 = Path(appdata) / "npm" / "gemini.ps1"
                if npm_ps1.is_file():
                    return str(npm_ps1)

        return None

    def detect(self) -> bool:
        """Check if gemini binary is available and executable."""
        return self.find_binary() is not None

    def capabilities(self) -> dict[str, Any]:
        """Return capabilities matching agent-registry.schema.json."""
        return {
            "streaming": False,
            "resume": "verified",
            "interrupt": "process_group",
            "permission_modes": ["default", "auto_edit", "yolo", "plan"],
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
        """Execute task headless via gemini CLI."""
        bin_path = self.find_binary() or "gemini"
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
            cmd.extend(["--approval-mode", "plan"])
        else:
            approval_mode = task.get("permission_mode") or handoff.get("permission_mode")
            if approval_mode in ["auto_edit", "yolo", "plan"]:
                cmd.extend(["--approval-mode", approval_mode])

        env_overrides = task.get("env_overrides") or handoff.get("env_overrides")

        result = self.runner.run(
            command=cmd,
            env_overrides=env_overrides,
            timeout_seconds=timeout_seconds,
            run_handle=run_handle,
        )

        self._parse_gemini_output(result)
        return result

    def resume(self, run_handle: str, message: str) -> ExecutionResult:
        """Resume session using --resume flag."""
        bin_path = self.find_binary() or "gemini"
        cmd = [bin_path, "-p", message, "--resume", run_handle, "--output-format", "json"]
        result = self.runner.run(command=cmd)
        self._parse_gemini_output(result)
        return result

    def interrupt(self, run_handle: str) -> None:
        """Interrupt active execution."""
        self.runner.interrupt(run_handle)

    def _parse_gemini_output(self, result: ExecutionResult) -> None:
        """Parse JSON stdout or fallback text and extract metadata."""
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
            if "session_id" in parsed:
                result.session_id = str(parsed["session_id"])

        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "permission denied" in combined or "approval denied" in combined:
            if not result.permission_denials:
                result.permission_denials.append("Gemini tool permission denied")
            result.status = "blocked"
