"""Smart cost, duration, and token telemetry ledger for multi-agent runs.

Implements Phase 2 Telemetry & Cost Calibration:
- Appends structured per-run metrics to .agentic/runs/metrics.jsonl
- Estimates token usage from prompt and output byte sizes when CLI telemetry is absent
- Computes aggregate statistics per runtime and role for Chief cost calibration
"""
from __future__ import annotations

import datetime
import json
import sys
import time
from pathlib import Path
from typing import Any


def _lock_file(f: Any) -> None:
    if sys.platform == "win32":
        import msvcrt
        try:
            f.seek(0, 0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _unlock_file(f: Any) -> None:
    if sys.platform == "win32":
        import msvcrt
        try:
            f.seek(0, 0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


class TelemetryLedger:
    """Records and summarizes execution metrics across agent runtimes."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.runs_dir = self.root_dir / ".agentic" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_file = self.runs_dir / "metrics.jsonl"

    @staticmethod
    def estimate_tokens(prompt_text: str, stdout_text: str, stderr_text: str) -> int:
        """Estimate token usage (~4 chars per token heuristic) from input/output streams."""
        total_chars = len(prompt_text or "") + len(stdout_text or "") + len(stderr_text or "")
        return max(1, total_chars // 4)

    def record_run_metrics(
        self,
        *,
        run_id: str,
        task_id: str,
        workflow_id: str,
        runtime: str,
        role: str,
        duration_ms: int,
        prompt_text: str = "",
        stdout_text: str = "",
        stderr_text: str = "",
        status: str = "completed",
        verified: bool = False,
        quarantined_files_count: int = 0,
    ) -> dict[str, Any]:
        """Append a single task execution telemetry entry to metrics.jsonl."""
        stdout_bytes = len((stdout_text or "").encode("utf-8", errors="replace"))
        stderr_bytes = len((stderr_text or "").encode("utf-8", errors="replace"))
        est_tokens = self.estimate_tokens(prompt_text, stdout_text, stderr_text)

        entry = {
            "schema_version": "1.0",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "run_id": run_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "runtime": runtime,
            "role": role,
            "duration_ms": int(duration_ms),
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "estimated_tokens": est_tokens,
            "status": status,
            "verified": bool(verified),
            "quarantined_files_count": int(quarantined_files_count),
        }

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        max_retries = 10
        delay = 0.05
        for attempt in range(max_retries):
            try:
                with open(self.metrics_file, "a+", encoding="utf-8") as f:
                    _lock_file(f)
                    try:
                        f.seek(0, 2)
                        f.write(line)
                        f.flush()
                    finally:
                        _unlock_file(f)
                break
            except OSError:
                if attempt == max_retries - 1:
                    with open(self.metrics_file, "a", encoding="utf-8") as f:
                        f.write(line)
                        f.flush()
                else:
                    time.sleep(delay)

        return entry

    def list_entries(self, workflow_id: str | None = None) -> list[dict[str, Any]]:
        """Read all telemetry entries, optionally filtered by workflow_id."""
        if not self.metrics_file.is_file():
            return []
        entries: list[dict[str, Any]] = []
        try:
            with open(self.metrics_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        if workflow_id and item.get("workflow_id") != workflow_id:
                            continue
                        entries.append(item)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return entries

    def summarize(self, workflow_id: str | None = None) -> dict[str, Any]:
        """Compute aggregate calibration statistics across recorded runs."""
        entries = self.list_entries(workflow_id=workflow_id)
        if not entries:
            return {
                "total_runs": 0,
                "verified_runs": 0,
                "verification_rate": 0.0,
                "total_duration_ms": 0,
                "avg_duration_ms": 0,
                "total_estimated_tokens": 0,
                "by_runtime": {},
            }

        total = len(entries)
        verified_count = sum(1 for e in entries if e.get("verified"))
        total_dur = sum(int(e.get("duration_ms", 0)) for e in entries)
        total_tokens = sum(int(e.get("estimated_tokens", 0)) for e in entries)

        by_runtime: dict[str, dict[str, Any]] = {}
        for e in entries:
            rt = e.get("runtime", "unknown")
            bucket = by_runtime.setdefault(
                rt,
                {"runs": 0, "verified": 0, "total_duration_ms": 0, "estimated_tokens": 0},
            )
            bucket["runs"] += 1
            if e.get("verified"):
                bucket["verified"] += 1
            bucket["total_duration_ms"] += int(e.get("duration_ms", 0))
            bucket["estimated_tokens"] += int(e.get("estimated_tokens", 0))

        return {
            "total_runs": total,
            "verified_runs": verified_count,
            "verification_rate": round(verified_count / total, 4),
            "total_duration_ms": total_dur,
            "avg_duration_ms": total_dur // total,
            "total_estimated_tokens": total_tokens,
            "by_runtime": by_runtime,
        }
