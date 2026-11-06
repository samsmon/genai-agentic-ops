"""CLI handlers for audit record and append-only event trail.

Implements CLI commands:
- agentic audit show [--limit <n>] [--event <type>] [--task-id <id>] [--workflow-id <id>]
"""
from __future__ import annotations

import argparse
from typing import Any

from orchestrator.cli.envelope import EXIT_OK, emit_envelope
from orchestrator.core.coordinator import OrchestratorCoordinator


def handle_audit_show(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    events = coord.audit_logger.get_events(
        limit=getattr(args, "limit", None),
        event_type=getattr(args, "event", None),
        task_id=getattr(args, "task_id", None),
        workflow_id=getattr(args, "workflow_id", None),
    )
    emit_envelope(
        ok=True,
        data={"count": len(events), "events": events},
        exit_code=EXIT_OK,
    )


def register_audit_subparser(subparsers: argparse._SubParsersAction[Any]) -> None:
    p_aud = subparsers.add_parser("audit", help="Audit records and append-only event trail")
    aud_subs = p_aud.add_subparsers(dest="audit_action", required=True)

    p_show = aud_subs.add_parser("show", help="Show audit events")
    p_show.add_argument("--limit", type=int, default=50, help="Maximum number of events to show")
    p_show.add_argument("--event", help="Filter by event type")
    p_show.add_argument("--task-id", help="Filter by task ID")
    p_show.add_argument("--workflow-id", help="Filter by workflow ID")
