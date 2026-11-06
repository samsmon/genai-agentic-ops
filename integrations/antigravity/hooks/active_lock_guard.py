"""Antigravity PreToolUse hook to prevent host edits during active worker execution.

Mitigates Claude Code architectural review finding:
Inspects .agentic/locks/active.json before file writes or edits. If an active lock is
held and the target path falls within the worker's claimed scope, rejects the tool call
with {"decision": "deny", "reason": "..."}.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _find_repo_root() -> Path:
    """Locate repository root containing .agentic or .git."""
    curr = Path.cwd().resolve()
    for parent in [curr] + list(curr.parents):
        if (parent / ".agentic").exists() or (parent / ".git").exists():
            return parent
    return curr


def _is_path_locked(target_path_str: str, allowed_paths: list[str], root_dir: Path) -> bool:
    """Check if target_path falls within the claimed allowed_paths scope."""
    if not allowed_paths:
        return True

    try:
        target = Path(target_path_str)
        if not target.is_absolute():
            target = (root_dir / target).resolve()
        else:
            target = target.resolve()
    except Exception:
        return True

    for p in allowed_paths:
        try:
            allowed = (root_dir / p).resolve()
            if target == allowed or allowed in target.parents or target in allowed.parents:
                return True
        except Exception:
            continue
    return False


def evaluate_tool_call(payload: dict[str, Any], root_dir: Path | None = None) -> tuple[str, str]:
    """Evaluate whether tool call is permitted against active lock state."""
    tool_call = payload.get("toolCall") or {}
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args") or {}

    if tool_name not in ("write_file", "edit_file"):
        return "allow", ""

    root = root_dir or _find_repo_root()
    active_lock_file = root / ".agentic" / "locks" / "active.json"
    if not active_lock_file.is_file():
        active_lock_file = root / ".agentic" / "locks" / "lock.json"
        if not active_lock_file.is_file():
            return "allow", ""

    try:
        with open(active_lock_file, "r", encoding="utf-8") as f:
            lock_data = json.load(f)
    except Exception:
        return "allow", ""

    task_id = lock_data.get("task_id", "unknown-task")
    allowed_paths = lock_data.get("allowed_paths", [])
    target_path = args.get("Path", "")

    if target_path and _is_path_locked(target_path, allowed_paths, root):
        reason = (
            f"Modification to '{target_path}' rejected: actively claimed by worker "
            f"task '{task_id}'. Wait for worker completion or release lock."
        )
        return "deny", reason

    return "allow", ""


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            sys.stdout.write(json.dumps({"decision": "allow"}))
            return

        payload = json.loads(raw_input)
        decision, reason = evaluate_tool_call(payload)
        out = {"decision": decision}
        if reason:
            out["reason"] = reason
        sys.stdout.write(json.dumps(out))
    except Exception:
        sys.stdout.write(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
