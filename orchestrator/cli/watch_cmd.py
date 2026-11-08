"""Live terminal dashboard for genai-agentic-ops (`agentic watch`).

Implements Phase 3 Live Operational Dashboard:
Renders real-time workflow state, task DAG status, active lock holder,
and telemetry calibration summary without third-party UI dependencies.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from orchestrator.core.coordinator import OrchestratorCoordinator


def render_dashboard(
    coord: OrchestratorCoordinator,
    workflow_id: str | None = None,
) -> str:
    """Render a plain-text / ANSI status snapshot of orchestrator state."""
    workflows = (
        [w for w in [coord.storage.load_workflow(workflow_id)] if w]
        if workflow_id
        else coord.storage.list_workflows()
    )
    tasks = coord.task_manager.list_tasks(workflow_id=workflow_id)
    lock = coord.lock_manager.read_lock()
    stale, stale_reason = coord.lock_manager.is_stale()
    metrics = coord.telemetry.summarize(workflow_id=workflow_id)

    lines: list[str] = [
        "======================================================================",
        f" genai-agentic-ops Live Dashboard | Root: {coord.root_dir.name}",
        "======================================================================",
    ]

    # 1. Lock status
    if lock:
        holder = lock.get("host", {})
        lock_state = f"STALE ({stale_reason})" if stale else "ACTIVE"
        lines.append(
            f"[LOCK]      {lock_state} | task={lock.get('task_id')} | "
            f"pid={holder.get('pid')}@{holder.get('hostname')} | scope={lock.get('allowed_paths')}"
        )
    else:
        lines.append("[LOCK]      IDLE (no active worker lock)")

    # 2. Telemetry summary
    lines.append(
        f"[TELEMETRY] runs={metrics['total_runs']} | verified={metrics['verified_runs']} "
        f"({metrics['verification_rate'] * 100:.0f}%) | avg_ms={metrics['avg_duration_ms']} | "
        f"est_tokens={metrics['total_estimated_tokens']}"
    )
    lines.append("----------------------------------------------------------------------")

    # 3. Workflows
    if not workflows:
        lines.append("Workflows: (none registered)")
    else:
        lines.append(f"Workflows ({len(workflows)}):")
        for wf in workflows:
            lines.append(
                f"  - {wf.get('workflow_id')} [{wf.get('status', 'unknown').upper()}] "
                f"{wf.get('title', '')} ({len(wf.get('tasks', []))} tasks)"
            )

    lines.append("----------------------------------------------------------------------")

    # 4. Tasks table
    if not tasks:
        lines.append("Tasks: (none registered)")
    else:
        lines.append(f"{'TASK ID':<16} {'STATUS':<14} {'RUNTIME':<13} {'ROLE':<10} {'TITLE'}")
        lines.append("-" * 70)
        for t in tasks:
            t_id = str(t.get("task_id", ""))[:15]
            st = str(t.get("status", ""))[:13]
            rt = str(t.get("runtime", ""))[:12]
            role = str(t.get("role", ""))[:9]
            title = str(t.get("title", ""))[:30]
            lines.append(f"{t_id:<16} {st:<14} {rt:<13} {role:<10} {title}")

    lines.append("======================================================================")
    return "\n".join(lines)


def handle_watch(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    """Display the dashboard once or poll at the requested interval."""
    once = getattr(args, "once", False)
    interval = max(0.5, float(getattr(args, "interval", 2.0)))
    wf_id = getattr(args, "workflow_id", None)

    try:
        while True:
            if not once:
                sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(render_dashboard(coord, workflow_id=wf_id) + "\n")
            sys.stdout.flush()
            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def register_watch_subparser(subparsers: argparse._SubParsersAction[Any]) -> None:
    p_watch = subparsers.add_parser("watch", help="Live terminal dashboard of workflows and locks")
    p_watch.add_argument("--workflow-id", help="Optional workflow ID filter")
    p_watch.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds")
    p_watch.add_argument("--once", action="store_true", help="Render snapshot once and exit")
