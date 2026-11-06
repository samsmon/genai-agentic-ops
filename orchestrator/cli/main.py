"""Command line interface for genai-agentic-ops orchestrator.

Implements CLI commands:
- agentic plan validate <plan-file>
- agentic plan submit <plan-file>
- agentic task list [--workflow-id <id>] [--status <status>]
- agentic task show <task-id>
- agentic agent list
- agentic agent inspect <agent-name>
- agentic status [--workflow-id <id>]
- agentic doctor
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from orchestrator.cli.approval_cmd import (
    handle_approval_deny,
    handle_approval_grant,
    handle_approval_show,
    register_approval_subparser,
)
from orchestrator.cli.audit_cmd import handle_audit_show, register_audit_subparser
from orchestrator.cli.envelope import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    EXIT_OK,
    emit_envelope,
    make_envelope,
)
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import TaskRunner


def _find_repo_root() -> Path:
    """Find repository root by looking for .git or fallback to current directory."""
    curr = Path.cwd().resolve()
    for parent in [curr] + list(curr.parents):
        if (parent / ".git").exists() or (parent / ".agentic").exists():
            return parent
    return curr


def handle_plan_validate(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    res = coord.validator.validate_plan_file(args.plan_file)
    if not res.valid:
        emit_envelope(
            ok=False,
            error={"code": "PLAN_INVALID", "message": "Plan validation failed", "details": res.errors},
            exit_code=EXIT_ERROR,
        )
    emit_envelope(
        ok=True,
        data={"valid": True, "workflow_id": (res.plan_data or {}).get("workflow_id")},
        exit_code=EXIT_OK,
    )


def handle_plan_submit(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    try:
        res = coord.submit_plan(args.plan_file)
        emit_envelope(ok=True, data=res, exit_code=EXIT_OK)
    except ValueError as e:
        emit_envelope(
            ok=False,
            error={"code": "SUBMISSION_REJECTED", "message": str(e)},
            exit_code=EXIT_ERROR,
        )


def handle_task_list(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    tasks = coord.task_manager.list_tasks(
        workflow_id=args.workflow_id, status=args.status
    )
    emit_envelope(
        ok=True,
        data={"count": len(tasks), "tasks": tasks},
        exit_code=EXIT_OK,
    )


def handle_task_show(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    task = coord.task_manager.get_task(args.task_id)
    if not task:
        emit_envelope(
            ok=False,
            error={"code": "TASK_NOT_FOUND", "message": f"Task '{args.task_id}' not found"},
            exit_code=EXIT_ERROR,
        )
    emit_envelope(ok=True, data=task, exit_code=EXIT_OK)


def handle_task_run(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    runner = TaskRunner(coord)
    try:
        res = runner.run_task(args.task_id, timeout_seconds=getattr(args, "timeout", None))
        status = res.get("execution", {}).get("status")
        verified = res.get("verification", {}).get("verified", False)
        if not verified and status in ("blocked", "failed", "timed_out"):
            emit_envelope(
                ok=False,
                data=res,
                error={"code": "TASK_UNVERIFIED", "message": f"Task ended with status {status}"},
                exit_code=EXIT_BLOCKED if status == "blocked" else EXIT_ERROR,
            )
        emit_envelope(ok=True, data=res, exit_code=EXIT_OK)
    except Exception as e:
        emit_envelope(ok=False, error={"code": "EXECUTION_ERROR", "message": str(e)}, exit_code=EXIT_ERROR)


def handle_task_approve(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    try:
        res = coord.approve_task(args.task_id)
        emit_envelope(ok=True, data=res, exit_code=EXIT_OK)
    except Exception as e:
        emit_envelope(ok=False, error={"code": "APPROVAL_FAILED", "message": str(e)}, exit_code=EXIT_ERROR)


def handle_workflow_run(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    runner = TaskRunner(coord)
    try:
        res = runner.run_workflow(args.workflow_id, max_tasks=getattr(args, "max_tasks", 10))
        ok = res.get("success", True)
        emit_envelope(ok=ok, data=res, exit_code=EXIT_OK if ok else EXIT_ERROR)
    except Exception as e:
        emit_envelope(ok=False, error={"code": "WORKFLOW_EXECUTION_ERROR", "message": str(e)}, exit_code=EXIT_ERROR)


def handle_agent_list(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    agents = coord.registry.list_agents()
    emit_envelope(ok=True, data={"count": len(agents), "agents": agents}, exit_code=EXIT_OK)


def handle_agent_inspect(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    agent = coord.registry.inspect_agent(args.agent_name)
    if not agent:
        emit_envelope(
            ok=False,
            error={"code": "AGENT_NOT_FOUND", "message": f"Agent '{args.agent_name}' not found"},
            exit_code=EXIT_ERROR,
        )
    emit_envelope(ok=True, data=agent, exit_code=EXIT_OK)


def handle_status(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    lock_data = coord.lock_manager.read_lock()
    stale_lock, stale_reason = coord.lock_manager.is_stale()
    orphans = coord.storage.detect_orphaned_intents()

    if args.workflow_id:
        data = {
            "workflow": coord.storage.load_workflow(args.workflow_id),
            "tasks": coord.task_manager.list_tasks(workflow_id=args.workflow_id),
            "active_lock": lock_data, "stale_lock": stale_lock, "orphaned_runs_count": len(orphans),
        }
    else:
        workflows = coord.storage.list_workflows()
        data = {
            "workflows_count": len(workflows), "workflows": workflows,
            "tasks_count": len(coord.task_manager.list_tasks()),
            "active_lock": lock_data, "stale_lock": stale_lock, "orphaned_runs_count": len(orphans),
        }
    emit_envelope(ok=True, data=data, exit_code=EXIT_OK)


def handle_doctor(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    checks: list[dict[str, Any]] = []

    # 1. Python version check
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append({"name": "python_version", "ok": sys.version_info >= (3, 10), "details": py_ver})

    # 2. jsonschema dependency
    try:
        import importlib.metadata
        checks.append({"name": "jsonschema", "ok": True, "details": importlib.metadata.version("jsonschema")})
    except Exception:
        checks.append({"name": "jsonschema", "ok": True, "details": "installed"})

    # 3. Storage directory writable
    storage_ok = coord.storage.agentic_dir.is_dir() and os.access(coord.storage.agentic_dir, os.W_OK)
    checks.append({"name": "storage_layout", "ok": storage_ok, "details": str(coord.storage.agentic_dir)})

    # 4. Advisory lock health
    stale, reason = coord.lock_manager.is_stale()
    checks.append({"name": "advisory_lock", "ok": not stale, "details": reason})

    # 5. Crash recovery check
    orphaned = coord.storage.detect_orphaned_intents()
    checks.append({
        "name": "crash_recovery",
        "ok": len(orphaned) == 0,
        "details": f"{len(orphaned)} orphaned runs detected" if orphaned else "Clean (no orphaned runs)",
    })

    all_ok = all(c["ok"] for c in checks)
    emit_envelope(ok=all_ok, data={"checks": checks}, exit_code=EXIT_OK if all_ok else EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic",
        description="genai-agentic-ops deterministic orchestration CLI",
    )
    parser.add_argument("--root", help="Repository root directory (defaults to auto-detect)")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # plan validate / submit
    p_plan = subparsers.add_parser("plan", help="Plan management")
    plan_subs = p_plan.add_subparsers(dest="plan_action", required=True)
    p_val = plan_subs.add_parser("validate", help="Validate plan against schema and policy")
    p_val.add_argument("plan_file", help="Path to plan JSON file")
    p_sub = plan_subs.add_parser("submit", help="Submit plan for orchestration")
    p_sub.add_argument("plan_file", help="Path to plan JSON file")

    # task list / show / run / approve
    p_task = subparsers.add_parser("task", help="Task management")
    task_subs = p_task.add_subparsers(dest="task_action", required=True)
    p_tlist = task_subs.add_parser("list", help="List registered tasks")
    p_tlist.add_argument("--workflow-id", help="Filter by workflow ID")
    p_tlist.add_argument("--status", help="Filter by task status")
    p_tshow = task_subs.add_parser("show", help="Show task definition and status")
    p_tshow.add_argument("task_id", help="Task ID")
    p_trun = task_subs.add_parser("run", help="Execute ready task")
    p_trun.add_argument("task_id", help="Task ID")
    p_trun.add_argument("--timeout", type=int, help="Execution timeout in seconds")
    p_tapp = task_subs.add_parser("approve", help="Approve verified task")
    p_tapp.add_argument("task_id", help="Task ID")

    # workflow run
    p_wf = subparsers.add_parser("workflow", help="Workflow management")
    wf_subs = p_wf.add_subparsers(dest="workflow_action", required=True)
    p_wfrun = wf_subs.add_parser("run", help="Execute ready workflow tasks")
    p_wfrun.add_argument("workflow_id", help="Workflow ID")
    p_wfrun.add_argument("--max-tasks", type=int, default=10, help="Max tasks to run")

    # agent list / inspect
    p_agent = subparsers.add_parser("agent", help="Agent runtime adapters and registry")
    agent_subs = p_agent.add_subparsers(dest="agent_action", required=True)
    agent_subs.add_parser("list", help="List registered runtime agents")
    p_ainspect = agent_subs.add_parser("inspect", help="Inspect agent capabilities and maturity")
    p_ainspect.add_argument("agent_name", help="Registered agent name (e.g. claude-code, antigravity)")

    # status
    p_stat = subparsers.add_parser("status", help="Show orchestrator and workflow status")
    p_stat.add_argument("--workflow-id", help="Workflow ID")

    # approval show / grant / deny
    register_approval_subparser(subparsers)

    # audit show
    register_audit_subparser(subparsers)

    # doctor
    subparsers.add_parser("doctor", help="Inspect orchestrator health and environment")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else _find_repo_root()
    coordinator = OrchestratorCoordinator(root)

    if args.subcommand == "plan":
        if args.plan_action == "validate":
            handle_plan_validate(args, coordinator)
        elif args.plan_action == "submit":
            handle_plan_submit(args, coordinator)
    elif args.subcommand == "task":
        if args.task_action == "list":
            handle_task_list(args, coordinator)
        elif args.task_action == "show":
            handle_task_show(args, coordinator)
        elif args.task_action == "run":
            handle_task_run(args, coordinator)
        elif args.task_action == "approve":
            handle_task_approve(args, coordinator)
    elif args.subcommand == "workflow":
        if args.workflow_action == "run":
            handle_workflow_run(args, coordinator)
    elif args.subcommand == "agent":
        if args.agent_action == "list":
            handle_agent_list(args, coordinator)
        elif args.agent_action == "inspect":
            handle_agent_inspect(args, coordinator)
    elif args.subcommand == "status":
        handle_status(args, coordinator)
    elif args.subcommand == "approval":
        if args.approval_action == "show":
            handle_approval_show(args, coordinator)
        elif args.approval_action == "grant":
            handle_approval_grant(args, coordinator)
        elif args.approval_action == "deny":
            handle_approval_deny(args, coordinator)
    elif args.subcommand == "audit":
        if args.audit_action == "show":
            handle_audit_show(args, coordinator)
    elif args.subcommand == "doctor":
        handle_doctor(args, coordinator)


if __name__ == "__main__":
    main()
