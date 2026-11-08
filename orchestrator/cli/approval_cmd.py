"""CLI handlers for human approval management.

Implements CLI commands:
- agentic approval show <task-id>
- agentic approval grant <task-id> --token <token> [--approver <name>]
- agentic approval deny <task-id> --token <token> [--reason <reason>]
"""
from __future__ import annotations

import argparse
from typing import Any

from orchestrator.cli.envelope import (
    EXIT_BLOCKED,
    EXIT_ERROR,
    EXIT_OK,
    emit_envelope,
)
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.state_machine import ActorRole, TaskState
from orchestrator.governance.approval import ensure_interactive_environment


def handle_approval_show(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    try:
        ensure_interactive_environment()
    except ValueError as e:
        emit_envelope(
            ok=False,
            error={"code": "APPROVAL_FORBIDDEN", "message": str(e)},
            exit_code=EXIT_ERROR,
        )
    task = coord.task_manager.get_task(args.task_id)
    if not task:
        emit_envelope(
            ok=False,
            error={"code": "TASK_NOT_FOUND", "message": f"Task '{args.task_id}' not found"},
            exit_code=EXIT_ERROR,
        )

    approval = coord.approval_manager.get_approval(args.task_id)
    data = {
        "task_id": args.task_id,
        "title": task.get("title", ""),
        "status": task.get("status", ""),
        "approval": approval or {"status": "none", "required": False},
        "context": (approval or {}).get("context", {}),
    }
    emit_envelope(ok=True, data=data, exit_code=EXIT_OK)


def handle_approval_grant(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    task = coord.task_manager.get_task(args.task_id)
    if not task:
        emit_envelope(
            ok=False,
            error={"code": "TASK_NOT_FOUND", "message": f"Task '{args.task_id}' not found"},
            exit_code=EXIT_ERROR,
        )

    try:
        approver = getattr(args, "approver", None) or "human"
        appr_res = coord.approval_manager.grant_approval(
            task_id=args.task_id,
            token=args.token,
            approver=approver,
        )
        coord.task_manager.update_task_status(
            args.task_id, TaskState.APPROVED, ActorRole.HUMAN
        )
        wf_id = task["workflow_id"]
        advanced = coord._advance_ready_tasks(wf_id)
        coord._refresh_workflow_status(wf_id)

        coord.audit_logger.log_event(
            "approval_granted",
            task_id=args.task_id,
            workflow_id=wf_id,
            details={"approver": approver},
        )
        coord.projector.project(coord.task_manager.list_tasks())

        data = {
            "task_id": args.task_id,
            "status": "approved",
            "approval": appr_res,
            "unlocked_tasks": advanced,
        }
        emit_envelope(ok=True, data=data, exit_code=EXIT_OK)
    except ValueError as e:
        emit_envelope(
            ok=False,
            error={"code": "APPROVAL_INVALID", "message": str(e)},
            exit_code=EXIT_ERROR,
        )


def handle_approval_deny(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    task = coord.task_manager.get_task(args.task_id)
    if not task:
        emit_envelope(
            ok=False,
            error={"code": "TASK_NOT_FOUND", "message": f"Task '{args.task_id}' not found"},
            exit_code=EXIT_ERROR,
        )

    try:
        reason = getattr(args, "reason", "") or "Denied by user"
        approver = getattr(args, "approver", None) or "human"
        appr_res = coord.approval_manager.deny_approval(
            task_id=args.task_id,
            token=args.token,
            reason=reason,
            approver=approver,
        )
        coord.task_manager.update_task_status(
            args.task_id, TaskState.BLOCKED, ActorRole.HUMAN
        )
        wf_id = task["workflow_id"]
        coord._refresh_workflow_status(wf_id)

        coord.audit_logger.log_event(
            "blocked",
            task_id=args.task_id,
            workflow_id=wf_id,
            details={"reason": "approval_denied", "details": reason},
        )
        coord.projector.project(coord.task_manager.list_tasks())

        data = {
            "task_id": args.task_id,
            "status": "blocked",
            "approval": appr_res,
        }
        emit_envelope(ok=True, data=data, exit_code=EXIT_OK)
    except ValueError as e:
        emit_envelope(
            ok=False,
            error={"code": "APPROVAL_INVALID", "message": str(e)},
            exit_code=EXIT_ERROR,
        )


def register_approval_subparser(subparsers: argparse._SubParsersAction[Any]) -> None:
    p_app = subparsers.add_parser("approval", help="Human approval gate management")
    app_subs = p_app.add_subparsers(dest="approval_action", required=True)

    # approval show
    p_show = app_subs.add_parser("show", help="Show task approval status and evidence")
    p_show.add_argument("task_id", help="Task ID")

    # approval grant
    p_grant = app_subs.add_parser("grant", help="Grant approval using one-time token")
    p_grant.add_argument("task_id", help="Task ID")
    p_grant.add_argument("--token", required=True, help="One-time cryptographic approval token")
    p_grant.add_argument("--approver", default="human", help="Approver identity")

    # approval deny
    p_deny = app_subs.add_parser("deny", help="Deny task approval using one-time token")
    p_deny.add_argument("task_id", help="Task ID")
    p_deny.add_argument("--token", required=True, help="One-time cryptographic approval token")
    p_deny.add_argument("--reason", default="", help="Reason for denial")
    p_deny.add_argument("--approver", default="human", help="Approver identity")
