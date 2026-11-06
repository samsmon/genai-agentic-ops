"""Standardized JSON envelope and exit code constants for CLI commands.

Adheres to genai-agentic-ops CLI protocol:
- schema_version: "1.0"
- ok: bool
- error: dict | None
- data: dict | None
- Exit codes: 0 = OK, 1 = Error, 2 = Blocked
"""
from __future__ import annotations

import json
import sys
from typing import Any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2


def make_envelope(
    ok: bool,
    data: dict[str, Any] | list[Any] | None = None,
    error: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Construct standard JSON envelope."""
    err_obj = None
    if error is not None:
        if isinstance(error, dict):
            err_obj = error
        else:
            err_obj = {"code": "ERROR", "message": str(error)}

    return {
        "schema_version": "1.0",
        "ok": ok,
        "error": err_obj,
        "data": data,
    }


def emit_envelope(
    ok: bool,
    data: dict[str, Any] | list[Any] | None = None,
    error: dict[str, Any] | str | None = None,
    exit_code: int = EXIT_OK,
) -> None:
    """Print JSON envelope to stdout and exit with exit_code."""
    payload = make_envelope(ok=ok, data=data, error=error)
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    sys.exit(exit_code)
