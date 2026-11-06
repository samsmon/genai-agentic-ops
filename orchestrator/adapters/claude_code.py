"""Claude Code CLI runtime adapter.

Implements AgentAdapter for Claude Code (`claude` CLI):
- Detects binary via PATH and Windows WinGet link location.
- Non-interactive headless execution via `claude -p` with stdin.
- Output format `--output-format json` with structured and fallback parsing.
- Enforces role-based restrictions (disallows Edit/Write for reviewer role).
- Detects permission denials and maps execution status to 'blocked'.
- Strips ANTHROPIC_API_KEY by default to prevent unintended subscription-to-paid switch.
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


class ClaudeCodeAdapter:
    """Runtime adapter for Anthropic Claude Code CLI."""

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()

    @property
    def name(self) -> str:
        return "claude-code"

    @property
    def runtime(self) -> str:
        return "claude-code"

    @property
    def command(self) -> str:
        return "claude"

    @property
    def maturity(self) -> MaturityLevel:
        return MaturityLevel.LIVE_TESTED if self.detect() else MaturityLevel.FIXTURE_TESTED

    def find_binary(self) -> str | None:
        """Find executable path for claude CLI."""
        for candidate in ["claude", "claude.exe"]:
            found = shutil.which(candidate)
            if found:
                return found

        if sys.platform == "win32":
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            if local_appdata:
                winget_path = Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "claude.exe"
                if winget_path.is_file() and os.access(winget_path, os.X_OK):
                    return str(winget_path)

        return None

    def detect(self) -> bool:
        """Check if claude binary is installed and executable."""
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
        """Execute task headless via claude CLI."""
        bin_path = self.find_binary() or "claude"
        prompt_text = (
            task.get("prompt")
            or handoff.get("prompt")
            or task.get("description")
            or handoff.get("task_description")
            or ""
        )

        role = task.get("role") or handoff.get("role", "developer")
        cmd = [bin_path, "-p", "--output-format", "json"]

        # Enforce role restrictions
        if role == "reviewer":
            cmd.extend(["--disallowedTools", "Edit,Write"])

        permission_mode = task.get("permission_mode") or handoff.get("permission_mode")
        if permission_mode == "dangerously-skip-permissions":
            cmd.append("--dangerously-skip-permissions")

        env_overrides = task.get("env_overrides") or handoff.get("env_overrides")

        result = self.runner.run(
            command=cmd,
            stdin_input=prompt_text,
            env_overrides=env_overrides,
            strip_anthropic_api_key=True,
            timeout_seconds=timeout_seconds,
            run_handle=run_handle,
        )

        # Parse output and detect permission denials
        self._parse_claude_output(result)
        return result

    def resume(self, run_handle: str, message: str) -> ExecutionResult:
        """Resume session using --resume flag."""
        bin_path = self.find_binary() or "claude"
        cmd = [bin_path, "-p", "--output-format", "json", "--resume", run_handle]
        result = self.runner.run(command=cmd, stdin_input=message, strip_anthropic_api_key=True)
        self._parse_claude_output(result)
        return result

    def interrupt(self, run_handle: str) -> None:
        """Interrupt active process tree."""
        self.runner.interrupt(run_handle)

    def _parse_claude_output(self, result: ExecutionResult) -> None:
        """Parse JSON stdout or fallback text and extract metadata and permission denials."""
        stdout = result.stdout.strip()
        parsed_json: dict[str, Any] | None = None

        if stdout:
            try:
                parsed_json = json.loads(stdout)
                result.raw_output = parsed_json
            except json.JSONDecodeError:
                # Attempt to extract embedded JSON block if mixed output
                match = re.search(r"\{.*\}", stdout, re.DOTALL)
                if match:
                    try:
                        parsed_json = json.loads(match.group(0))
                        result.raw_output = parsed_json
                    except json.JSONDecodeError:
                        result.raw_output = stdout
                else:
                    result.raw_output = stdout

        # Extract session_id if available
        if isinstance(parsed_json, dict):
            if "session_id" in parsed_json:
                result.session_id = str(parsed_json["session_id"])
            elif "conversation_id" in parsed_json:
                result.session_id = str(parsed_json["conversation_id"])

            if "permission_denials" in parsed_json and isinstance(
                parsed_json["permission_denials"], list
            ):
                result.permission_denials.extend(str(d) for d in parsed_json["permission_denials"])

        # Check stdout and stderr for permission denial markers
        combined_text = f"{result.stdout}\n{result.stderr}".lower()
        if (
            "permission denied" in combined_text
            or "disallowed tool" in combined_text
            or "tool use rejected" in combined_text
        ):
            if not result.permission_denials:
                result.permission_denials.append("Permission denied or tool call disallowed")
            result.status = "blocked"
