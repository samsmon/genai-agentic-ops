"""Smart cost, duration, and token telemetry ledger for multi-agent runs.

Implements Phase 2 Telemetry & Cost Calibration:
- Appends structured per-run metrics to .agentic/runs/metrics.jsonl
- Records provider-reported token usage when the runtime returns it
- Estimates token usage from prompt and output byte sizes otherwise, and labels
  every entry with its token source so the two are never mixed up
- Computes aggregate statistics per runtime and role for Chief cost calibration
"""
from __future__ import annotations

import datetime
import json
import sys
import threading
from pathlib import Path
from typing import Any


_THREAD_LOCK = threading.Lock()


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


_INPUT_KEYS = ("input_tokens", "prompt_tokens")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens")
_CACHE_READ_KEYS = ("cache_read_input_tokens", "cached_tokens")


def _first_int(source: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def extract_provider_usage(raw_output: Any) -> dict[str, Any] | None:
    """Pull provider-reported token usage out of a parsed CLI result.

    Reads a top-level ``usage`` object with Anthropic-style keys
    (``input_tokens``, ``output_tokens``, ``cache_read_input_tokens``,
    ``cache_creation_input_tokens``) or OpenAI-style keys (``prompt_tokens``,
    ``completion_tokens``), plus ``total_cost_usd`` and ``model`` when present.
    Returns None for any other shape, so the caller falls back to the estimate.
    Parsing is covered by fixtures only; no runtime's live output has been
    checked against it yet.
    """
    if not isinstance(raw_output, dict):
        return None
    usage = raw_output.get("usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = _first_int(usage, _INPUT_KEYS)
    output_tokens = _first_int(usage, _OUTPUT_KEYS)
    if input_tokens is None and output_tokens is None:
        return None
    result: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": _first_int(usage, _CACHE_READ_KEYS),
        "cache_creation_input_tokens": _first_int(usage, ("cache_creation_input_tokens",)),
    }
    cost = raw_output.get("total_cost_usd")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        result["cost_usd"] = float(cost)
    model = raw_output.get("model")
    if isinstance(model, str) and model:
        result["model"] = model
    return result


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
        provider_usage: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a single task execution telemetry entry to metrics.jsonl."""
        stdout_bytes = len((stdout_text or "").encode("utf-8", errors="replace"))
        stderr_bytes = len((stderr_text or "").encode("utf-8", errors="replace"))
        est_tokens = self.estimate_tokens(prompt_text, stdout_text, stderr_text)

        entry = {
            "schema_version": "1.1",
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
            "token_source": "provider" if provider_usage else "estimated",
            "provider_usage": provider_usage,
            "status": status,
            "verified": bool(verified),
            "quarantined_files_count": int(quarantined_files_count),
        }

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        # Serialize writers with a thread lock (same process) plus a lock on a
        # dedicated lock file (other processes). Locking the data file itself
        # fails on Windows: a locked byte also blocks other handles' writes.
        lock_path = self.metrics_file.with_name(self.metrics_file.name + ".lock")
        with _THREAD_LOCK:
            with open(lock_path, "a+", encoding="utf-8") as lock_f:
                _lock_file(lock_f)
                try:
                    with open(self.metrics_file, "a", encoding="utf-8") as f:
                        f.write(line)
                        f.flush()
                finally:
                    _unlock_file(lock_f)

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
                "runs_with_provider_usage": 0,
                "total_provider_input_tokens": 0,
                "total_provider_output_tokens": 0,
                "by_runtime": {},
            }

        total = len(entries)
        verified_count = sum(1 for e in entries if e.get("verified"))
        total_dur = sum(int(e.get("duration_ms", 0)) for e in entries)
        total_tokens = sum(int(e.get("estimated_tokens", 0)) for e in entries)

        usages = [e["provider_usage"] for e in entries if isinstance(e.get("provider_usage"), dict)]
        provider_in = sum(int(u.get("input_tokens") or 0) for u in usages)
        provider_out = sum(int(u.get("output_tokens") or 0) for u in usages)

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
            "runs_with_provider_usage": len(usages),
            "total_provider_input_tokens": provider_in,
            "total_provider_output_tokens": provider_out,
            "by_runtime": by_runtime,
        }
