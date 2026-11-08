"""One-way operational projection from .agentic/state to docs/CURRENT_OPS.md.

Implements M4 single-source-of-truth projection:
- .agentic/state is authoritative
- Emits markdown table conforming to standard CURRENT_OPS.md format
- Rotates completed rows (>5 done/failed/cancelled rows moved to archive)
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any

from orchestrator.core.state_machine import TaskState

CURRENT_OPS_HEADER = """# CURRENT OPS — Live Task Tracker

One row per task. Each agent edits only its own rows.
Status: `running` | `done` | `blocked` | `failed` | `cancelled`.
`running` > 2 hours with no update = stale (ask the user; do not silently take over).
Timestamp format: `YYYY-MM-DD HH:MM` (user's local time).

| Timestamp | Agent | Session/Worker ID | Target File/Dir | Status | Task Description |
|---|---|---|---|---|---|
"""

CURRENT_OPS_FOOTER = """
## Archive
Older `done/failed/cancelled` rows moved to `docs/CURRENT_OPS-archive.md` (newest on top, verbatim). Do not read unless needed.
"""

STATE_TO_OPS_STATUS: dict[str, str] = {
    TaskState.PENDING.value: "ready",
    TaskState.READY.value: "ready",
    TaskState.RUNNING.value: "running",
    TaskState.COMPLETED.value: "done",
    TaskState.VERIFIED.value: "done",
    TaskState.APPROVED.value: "done",
    TaskState.BLOCKED.value: "blocked",
    TaskState.FAILED.value: "failed",
    TaskState.CANCELLED.value: "cancelled",
    TaskState.NEEDS_RECOVERY.value: "blocked",
}

TERMINAL_OPS_STATUSES: set[str] = {"done", "failed", "cancelled"}


def _format_timestamp(iso_str: str | None) -> str:
    if not iso_str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


class CurrentOpsProjector:
    """Projects orchestrator task states to docs/CURRENT_OPS.md with archive rotation."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.docs_dir = self.root_dir / "docs"
        self.current_ops_file = self.docs_dir / "CURRENT_OPS.md"
        self.archive_file = self.docs_dir / "CURRENT_OPS-archive.md"
        self.docs_dir.mkdir(parents=True, exist_ok=True)

    def format_task_row(self, task: dict[str, Any]) -> str:
        """Format a single task dictionary as a markdown table row."""
        ts = _format_timestamp(task.get("updated_at") or task.get("created_at"))
        agent = task.get("runtime") or task.get("role") or "agentic"
        task_id = task.get("task_id", "")
        allowed = task.get("allowed_paths", [])
        if allowed:
            target = allowed[0] if len(allowed) == 1 else ", ".join(allowed[:2])
        else:
            target = "workspace"

        raw_status = task.get("status", "running")
        status = STATE_TO_OPS_STATUS.get(raw_status, "running")
        desc = (task.get("title") or task.get("description") or "").replace("|", "/")
        return f"| {ts} | {agent} | {task_id} | {target} | {status} | {desc} |"

    def project(self, tasks: list[dict[str, Any]]) -> str:
        """Project current active and completed tasks into docs/CURRENT_OPS.md."""
        active_statuses = {
            TaskState.RUNNING.value,
            TaskState.COMPLETED.value,
            TaskState.VERIFIED.value,
            TaskState.APPROVED.value,
            TaskState.BLOCKED.value,
            TaskState.FAILED.value,
            TaskState.CANCELLED.value,
            TaskState.NEEDS_RECOVERY.value,
        }

        projected_tasks = [t for t in tasks if t.get("status") in active_statuses]
        if not projected_tasks:
            projected_tasks = tasks

        rows: list[str] = [self.format_task_row(t) for t in projected_tasks]

        terminal_rows: list[str] = []
        active_rows: list[str] = []
        for r in rows:
            is_terminal = any(f"| {s} |" in r for s in TERMINAL_OPS_STATUSES)
            if is_terminal:
                terminal_rows.append(r)
            else:
                active_rows.append(r)

        kept_terminal = terminal_rows[:5]
        overflow_terminal = terminal_rows[5:]

        if overflow_terminal:
            self._archive_rows(overflow_terminal)

        table_rows = active_rows + kept_terminal
        table_content = "\n".join(table_rows) if table_rows else "| (no active tasks) |"

        full_content = (
            CURRENT_OPS_HEADER.rstrip()
            + "\n"
            + table_content
            + "\n"
            + CURRENT_OPS_FOOTER.lstrip()
        )
        self._atomic_write(self.current_ops_file, full_content)
        return full_content

    def _archive_rows(self, rows: list[str]) -> None:
        """Prepend overflow rows to CURRENT_OPS-archive.md."""
        existing = ""
        if self.archive_file.is_file():
            existing = self.archive_file.read_text(encoding="utf-8")
        new_content = "\n".join(rows) + "\n" + existing
        self._atomic_write(self.archive_file, new_content)

    def _atomic_write(self, target_path: Path, content: str) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = target_path.parent / f"{target_path.name}.tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target_path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
