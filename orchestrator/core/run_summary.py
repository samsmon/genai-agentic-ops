"""Run summary record builder conforming to contracts/run.schema.json."""
from __future__ import annotations

from typing import Any

from orchestrator.governance.process_info import get_host_tuple


def build_run_summary(
    *,
    run_id: str,
    task: dict[str, Any],
    run_status: str,
    intent_info: dict[str, Any],
    baseline: dict[str, Any],
    prep: dict[str, Any],
    now_iso: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "workflow_id": task["workflow_id"],
        "status": run_status,
        "host": intent_info.get("host") or get_host_tuple(),
        "intent": intent_info.get("intent") or {
            "target_state": run_status,
            "action": "execute_task",
            "timestamp": now_iso,
        },
        "workspace_baseline": {
            "git_commit": "untracked",
            "clean": True,
            "snapshot_hash": baseline["snapshot_hash"],
            "timestamp": prep.get("created_at", now_iso),
        },
        "active_task_id": task["task_id"],
        "created_at": prep.get("created_at", now_iso),
        "updated_at": now_iso,
        "completed_at": now_iso,
    }
