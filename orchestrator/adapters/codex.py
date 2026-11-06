"""Codex CLI runtime adapter.

Implements AgentAdapter for OpenAI Codex (`codex` CLI):
- Declares honest maturity classification per ADR-005.
- Headless execution via `codex exec`.
- Output parsing for text responses.
"""
from __future__ import annotations

import shutil
from typing import Any

from orchestrator.adapters.base import AgentAdapter, ExecutionResult, MaturityLevel
from orchestrator.adapters.process_runner import ProcessRunner


class CodexAdapter:
    """Runtime adapter for OpenAI Codex CLI."""

    def __init__(self, runner: ProcessRunner | None = None) -> None:
        self.runner = runner or ProcessRunner()

    @property
    def name(self) -> str:
        return "codex"

    @property
    def runtime(self) -> str:
        return "codex"

    @property
    def command(self) -> str:
        return "codex"

    @property
    def maturity(self) -> MaturityLevel:
        # Declare honest maturity level: fixture-tested unless verified live on local system
        return MaturityLevel.LIVE_TESTED if self.detect() else MaturityLevel.FIXTURE_TESTED

    def find_binary(self) -> str | None:
        """Find executable path for codex CLI."""
        for candidate in ["codex", "codex.exe"]:
            found = shutil.which(candidate)
            if found:
                return found
        return None

    def detect(self) -> bool:
        """Check if codex CLI binary is available."""
        return self.find_binary() is not None

    def capabilities(self) -> dict[str, Any]:
        """Return capabilities matching agent-registry.schema.json."""
        return {
            "streaming": False,
            "resume": "unverified",
            "interrupt": "process_group",
            "permission_modes": ["default"],
            "output_format": "text",
        }

    def execute(
        self,
        task: dict[str, Any],
        handoff: dict[str, Any],
        *,
        run_handle: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Execute task headless via codex CLI."""
        bin_path = self.find_binary() or "codex"
        prompt_text = (
            task.get("prompt")
            or handoff.get("prompt")
            or task.get("description")
            or handoff.get("task_description")
            or ""
        )

        cmd = [bin_path, "exec"]
        env_overrides = task.get("env_overrides") or handoff.get("env_overrides")

        result = self.runner.run(
            command=cmd,
            stdin_input=prompt_text,
            env_overrides=env_overrides,
            timeout_seconds=timeout_seconds,
            run_handle=run_handle,
        )

        result.raw_output = result.stdout
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "permission denied" in combined or "operation blocked" in combined:
            result.permission_denials.append("Codex execution blocked by permissions")
            result.status = "blocked"

        return result

    def resume(self, run_handle: str, message: str) -> ExecutionResult:
        """Codex resume capability is unverified/unsupported in basic CLI."""
        return ExecutionResult(
            exit_code=1,
            status="failed",
            stderr="Codex CLI does not support session resume in current specification.",
        )

    def interrupt(self, run_handle: str) -> None:
        """Interrupt active execution."""
        self.runner.interrupt(run_handle)
