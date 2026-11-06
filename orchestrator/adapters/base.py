"""Base contracts, protocols, and data structures for runtime adapters.

Defines the standard AgentAdapter Protocol, execution result dataclass,
and honest maturity classification per ADR-005.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class MaturityLevel(str, Enum):
    """Honest maturity classification level per ADR-005.

    - DOCUMENTED: Behavior and flags derived solely from official CLI docs; unverified locally.
    - FIXTURE_TESTED: Adapter output parsing and command construction validated against mock fixtures.
    - LIVE_TESTED: Successfully executed against a genuine, locally installed CLI binary end-to-end.
    """

    DOCUMENTED = "documented"
    FIXTURE_TESTED = "fixture-tested"
    LIVE_TESTED = "live-tested"


@dataclass
class ExecutionResult:
    """Strongly-typed execution result returned by runtime adapters."""

    exit_code: int
    status: str  # completed, failed, blocked, timed_out
    stdout: str = ""
    stderr: str = ""
    stdout_ref: str | None = None
    stderr_ref: str | None = None
    session_id: str | None = None
    permission_denials: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    raw_output: Any = None

    @property
    def duration_ms(self) -> int:
        """Execution duration in integer milliseconds."""
        return int(max(0.0, self.duration_seconds * 1000.0))

    def to_dict(self) -> dict[str, Any]:
        """Convert execution result to dictionary matching result.schema.json execution structure."""
        return {
            "exit_code": self.exit_code,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "stdout_ref": self.stdout_ref or "",
            "stderr_ref": self.stderr_ref or "",
            "session_id": self.session_id or "",
            "permission_denials": list(self.permission_denials),
        }


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol implemented by all CLI runtime adapters."""

    @property
    def name(self) -> str:
        """Registered agent adapter name (e.g. 'claude-code', 'antigravity')."""
        ...

    @property
    def runtime(self) -> str:
        """Runtime identifier matching agent-registry.schema.json enum."""
        ...

    @property
    def command(self) -> str:
        """CLI binary command name (e.g. 'claude', 'agy', 'gemini', 'codex')."""
        ...

    @property
    def maturity(self) -> MaturityLevel:
        """Honest verification maturity level."""
        ...

    def detect(self) -> bool:
        """Return True if the runtime CLI binary is available and executable."""
        ...

    def capabilities(self) -> dict[str, Any]:
        """Return capabilities dictionary matching agent-registry.schema.json."""
        ...

    def execute(
        self,
        task: dict[str, Any],
        handoff: dict[str, Any],
        *,
        run_handle: str | None = None,
        timeout_seconds: float | None = None,
    ) -> ExecutionResult:
        """Execute task headless using this adapter and return ExecutionResult."""
        ...

    def resume(self, run_handle: str, message: str) -> ExecutionResult:
        """Resume a previous session if supported."""
        ...

    def interrupt(self, run_handle: str) -> None:
        """Interrupt an active execution identified by run_handle."""
        ...
