"""Gemini CLI active lock guard to prevent host edits during active worker execution.

Mitigates multi-agent write collisions:
Inspects .agentic/locks/active.json before tool calls. If an active lock is
held and the target path falls within the worker's claimed scope, rejects the tool call
with decision 'deny' and explanatory reason.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

MUTATING_SHELL_RE = re.compile(
    r"\bgit\s+(?:reset|checkout|clean|restore|stash|merge|rebase|cherry-pick)\b"
    r"|\b(?:rm|mv|sed\s+-i|Remove-Item|Move-Item|Set-Content|Out-File)\b"
)


def _extract_command(payload: dict[str, Any]) -> str:
    """Extract shell command string across Gemini CLI and generic tool inputs."""
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("command", "CommandLine", "cmd"):
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    tool_call = payload.get("toolCall")
    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if isinstance(args, dict):
            for key in ("CommandLine", "command", "cmd"):
                val = args.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return ""



def _find_repo_root() -> Path:
    """Locate repository root containing .agentic or .git."""
    curr = Path.cwd().resolve()
    for parent in [curr] + list(curr.parents):
        if (parent / ".agentic").exists() or (parent / ".git").exists():
            return parent
    return curr


def _extract_tool_name(payload: dict[str, Any]) -> str:
    """Extract tool identifier across Gemini CLI and generic hook payloads."""
    if "tool_name" in payload:
        return str(payload.get("tool_name", ""))
    tool_call = payload.get("toolCall")
    if isinstance(tool_call, dict):
        return str(tool_call.get("name", ""))
    return ""


def _extract_target_path(payload: dict[str, Any]) -> str:
    """Extract target file path across Gemini CLI and generic tool inputs."""
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("file_path", "filePath", "path", "Path", "file", "target"):
            val = tool_input.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    tool_call = payload.get("toolCall")
    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if isinstance(args, dict):
            for key in ("Path", "path", "file_path", "filePath", "file"):
                val = args.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()

    args = payload.get("args")
    if isinstance(args, dict):
        for key in ("Path", "path", "file_path"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    return ""


def _is_path_locked(target_path_str: str, allowed_paths: list[str], root_dir: Path) -> bool:
    """Check if target_path falls within the claimed allowed_paths scope."""
    if not allowed_paths:
        return True

    root_resolved = root_dir.resolve()
    try:
        target = Path(target_path_str)
        if not target.is_absolute():
            target = (root_dir / target).resolve()
        else:
            target = target.resolve()
        try:
            rel_target = target.relative_to(root_resolved).as_posix()
        except ValueError:
            rel_target = target_path_str.replace("\\", "/").strip("/")
    except Exception:
        rel_target = target_path_str.replace("\\", "/").strip("/")

    is_win = sys.platform == "win32"
    rel_norm = rel_target.lower() if is_win else rel_target

    for p in allowed_paths:
        p_clean = p.replace("\\", "/").strip("/")
        p_norm = p_clean.lower() if is_win else p_clean

        # Exact match or directory prefix
        if rel_norm == p_norm or rel_norm.startswith(p_norm + "/"):
            return True

        # Standard fnmatch pattern matching (e.g. *.pem, src/*.py)
        if fnmatch.fnmatchcase(rel_norm, p_norm):
            return True
        if "/" not in p_norm and fnmatch.fnmatchcase(rel_norm.split("/")[-1], p_norm):
            return True

        # Directory wildcards like docs/** or docs/*
        if p_norm.endswith("/**"):
            prefix = p_norm[:-3].rstrip("/")
            if rel_norm == prefix or rel_norm.startswith(prefix + "/"):
                return True
        elif p_norm.endswith("/*"):
            prefix = p_norm[:-2].rstrip("/")
            if rel_norm == prefix or rel_norm.startswith(prefix + "/"):
                return True

        # Fallback for filesystem path parents if not a glob
        if not any(c in p for c in ("*", "?", "[", "]")):
            try:
                allowed = (root_dir / p).resolve()
                if target == allowed or allowed in target.parents or target in allowed.parents:
                    return True
            except Exception:
                continue

    return False


def evaluate_tool_call(payload: dict[str, Any], root_dir: Path | None = None) -> tuple[str, str]:
    """Evaluate whether tool call is permitted against active lock state."""
    tool_name = _extract_tool_name(payload).strip().lower()
    is_file_edit = tool_name in ("edit", "write", "edit_file", "write_file", "multi_edit")
    is_shell = tool_name in ("run_command", "bash", "shell", "execute_command")
    if not is_file_edit and not is_shell:
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

    if is_shell:
        cmd_str = _extract_command(payload)
        if cmd_str and (
            MUTATING_SHELL_RE.search(cmd_str)
            or any(p.strip("./") and p.strip("./") in cmd_str for p in allowed_paths)
        ):
            reason = (
                f"Mutating shell command rejected while worker task '{task_id}' holds active lock "
                f"over {allowed_paths}. Wait for worker completion or release lock."
            )
            return "deny", reason
        return "allow", ""

    target_path = _extract_target_path(payload)

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
        out = {
            "decision": decision,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            },
        }
        if reason:
            out["reason"] = reason
            sys.stderr.write(reason + "\n")
        sys.stdout.write(json.dumps(out))
    except Exception:
        sys.stdout.write(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
