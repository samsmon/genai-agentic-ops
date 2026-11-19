"""CLI handlers for the budget guard.

- agentic budget status --workflow-id <id>
- agentic budget approve --workflow-id <id> [--extra-tokens N] [--extra-usd X] [--reason T]

``approve`` raises a workflow's limits and is human only: it is refused when
AGENTIC_NON_INTERACTIVE=1, and no MCP tool exposes it.
"""
from __future__ import annotations

import argparse
from typing import Any

from orchestrator.cli.envelope import EXIT_ERROR, EXIT_OK, emit_envelope
from orchestrator.core.coordinator import OrchestratorCoordinator


def register_budget_subparser(subparsers: argparse._SubParsersAction[Any]) -> None:
    p_bud = subparsers.add_parser("budget", help="Budget guard status and human override")
    subs = p_bud.add_subparsers(dest="budget_action", required=True)
    p_stat = subs.add_parser("status", help="Show limits, overrides and spend for a workflow")
    p_stat.add_argument("--workflow-id", required=True)
    p_app = subs.add_parser("approve", help="Raise a workflow's budget (human only)")
    p_app.add_argument("--workflow-id", required=True)
    p_app.add_argument("--extra-tokens", type=int, default=0)
    p_app.add_argument("--extra-usd", type=float, default=0.0)
    p_app.add_argument("--approver", default="human")
    p_app.add_argument("--reason", default="")


def handle_budget(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    try:
        if args.budget_action == "status":
            data = coord.budget.status(args.workflow_id)
        else:
            data = coord.budget.grant_override(
                args.workflow_id,
                extra_tokens=args.extra_tokens,
                extra_usd=args.extra_usd,
                approver=args.approver,
                reason=args.reason,
            )
    except ValueError as exc:
        emit_envelope(ok=False, error={"code": "BUDGET_ERROR", "message": str(exc)}, exit_code=EXIT_ERROR)
    emit_envelope(ok=True, data=data, exit_code=EXIT_OK)
