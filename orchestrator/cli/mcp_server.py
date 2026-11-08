"""Zero-dependency Model Context Protocol (MCP) stdio JSON-RPC 2.0 server.

Implements Phase 3 Native MCP Integration (`agentic mcp`):
Exposes deterministic orchestrator capabilities as native MCP tools for
Antigravity, Claude Code, Cursor, Codex, and Gemini CLI:
- agentic_status
- agentic_doctor
- agentic_plan_validate
- agentic_plan_submit
- agentic_task_list
- agentic_task_run
- agentic_workflow_run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import TaskRunner

MCP_PROTOCOL_VERSION = "2024-11-05"

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "agentic_status",
        "description": "Get orchestrator workflow status, active lock state, and telemetry summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "Optional workflow ID filter"}
            },
        },
    },
    {
        "name": "agentic_doctor",
        "description": "Verify orchestrator storage, advisory lock health, and crash recovery state.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agentic_plan_validate",
        "description": "Validate a workflow plan JSON file against schema, DAG acyclicity, and protected paths.",
        "inputSchema": {
            "type": "object",
            "required": ["plan_file"],
            "properties": {
                "plan_file": {"type": "string", "description": "Path to plan JSON file"}
            },
        },
    },
    {
        "name": "agentic_plan_submit",
        "description": "Submit a validated workflow plan JSON file for orchestration.",
        "inputSchema": {
            "type": "object",
            "required": ["plan_file"],
            "properties": {
                "plan_file": {"type": "string", "description": "Path to plan JSON file"}
            },
        },
    },
    {
        "name": "agentic_task_list",
        "description": "List registered tasks with optional workflow_id and status filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "status": {"type": "string"},
            },
        },
    },
    {
        "name": "agentic_task_run",
        "description": "Execute a ready task through its runtime adapter with baseline snapshot and scope check.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            },
        },
    },
    {
        "name": "agentic_workflow_run",
        "description": "Execute eligible ready tasks in a workflow.",
        "inputSchema": {
            "type": "object",
            "required": ["workflow_id"],
            "properties": {
                "workflow_id": {"type": "string"},
                "max_tasks": {"type": "integer", "default": 10},
            },
        },
    },
]


def execute_mcp_tool(
    coord: OrchestratorCoordinator,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Dispatch an MCP tool call to the deterministic orchestrator core.

    Returns (is_error, payload_dict).
    """
    args = arguments or {}
    try:
        if tool_name == "agentic_status":
            wf_id = args.get("workflow_id")
            stale, reason = coord.lock_manager.is_stale()
            orphans = coord.storage.detect_orphaned_intents()
            data = {
                "workflows": (
                    [coord.storage.load_workflow(wf_id)]
                    if wf_id
                    else coord.storage.list_workflows()
                ),
                "tasks": coord.task_manager.list_tasks(workflow_id=wf_id),
                "active_lock": coord.lock_manager.read_lock(),
                "stale_lock": stale,
                "stale_reason": reason,
                "orphaned_runs_count": len(orphans),
                "telemetry": coord.telemetry.summarize(workflow_id=wf_id),
            }
            return False, data

        if tool_name == "agentic_doctor":
            stale, reason = coord.lock_manager.is_stale()
            orphans = coord.storage.detect_orphaned_intents()
            storage_ok = coord.storage.agentic_dir.is_dir() and os.access(
                coord.storage.agentic_dir, os.W_OK
            )
            checks = [
                {"name": "storage_layout", "ok": storage_ok},
                {"name": "advisory_lock", "ok": not stale, "details": reason},
                {"name": "crash_recovery", "ok": len(orphans) == 0, "orphans": len(orphans)},
            ]
            return False, {"ok": all(c["ok"] for c in checks), "checks": checks}

        if tool_name == "agentic_plan_validate":
            res = coord.validator.validate_plan_file(args["plan_file"])
            return (not res.valid), {
                "valid": res.valid,
                "errors": res.errors,
                "workflow_id": (res.plan_data or {}).get("workflow_id"),
            }

        if tool_name == "agentic_plan_submit":
            sub_res = coord.submit_plan(args["plan_file"])
            return False, sub_res

        if tool_name == "agentic_task_list":
            tasks = coord.task_manager.list_tasks(
                workflow_id=args.get("workflow_id"),
                status=args.get("status"),
            )
            return False, {"count": len(tasks), "tasks": tasks}

        if tool_name == "agentic_task_run":
            runner = TaskRunner(coord)
            run_res = runner.run_task(
                args["task_id"],
                timeout_seconds=args.get("timeout_seconds"),
            )
            verified = run_res.get("verification", {}).get("verified", False)
            return (not verified), run_res

        if tool_name == "agentic_workflow_run":
            runner = TaskRunner(coord)
            wf_res = runner.run_workflow(
                args["workflow_id"],
                max_tasks=int(args.get("max_tasks", 10)),
            )
            return (not wf_res.get("success", True)), wf_res

        return True, {"error": f"Unknown MCP tool: '{tool_name}'"}
    except Exception as exc:
        return True, {"error": str(exc)}


def handle_jsonrpc_message(
    coord: OrchestratorCoordinator,
    msg: dict[str, Any],
) -> dict[str, Any] | None:
    """Process a single JSON-RPC 2.0 request and return response dictionary (or None for notifications)."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if req_id is None:
        return None  # JSON-RPC notification

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "genai-agentic-ops", "version": "2.6.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": MCP_TOOLS}}

    if method == "tools/call":
        t_name = params.get("name", "")
        t_args = params.get("arguments") or {}
        is_err, payload = execute_mcp_tool(coord, t_name, t_args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                "isError": is_err,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def handle_mcp_serve(args: argparse.Namespace, coord: OrchestratorCoordinator) -> None:
    """Run the stdio JSON-RPC 2.0 loop."""
    for line in sys.stdin:
        raw = line.strip()
        if not raw or raw.lower().startswith("content-length:"):
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            continue
        resp = handle_jsonrpc_message(coord, msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def register_mcp_subparser(subparsers: argparse._SubParsersAction[Any]) -> None:
    subparsers.add_parser("mcp", help="Run stdio Model Context Protocol (MCP) server")
