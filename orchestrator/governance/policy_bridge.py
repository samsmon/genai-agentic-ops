"""Policy Engine Bridge linking orchestrator to kit.core.policy.

Implements M4 policy verification:
- Direct library integration with kit.core.policy (check_command, evaluate)
- Validates declared verification commands before execution
- Rejects destructive commands (git push --force, rm -rf, reset --hard, clean -f, branch -D)
- Rejects security violations (sleep loops, identity changes, agent trailers, hook bypasses)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def _ensure_kit_import(root_dir: Path | None = None) -> None:
    """Ensure that the kit package or module can be imported cleanly."""
    if "kit.core.policy" in sys.modules:
        return
    candidates: list[Path] = []
    if root_dir:
        candidates.append(root_dir)
    curr = Path(__file__).resolve().parent
    for parent in [curr] + list(curr.parents):
        if (parent / "kit" / "core" / "policy.py").is_file():
            candidates.append(parent)
            break
    for c in candidates:
        c_str = str(c)
        if c_str not in sys.path:
            sys.path.insert(0, c_str)


_ensure_kit_import()

try:
    from kit.core.policy import ALLOW, ASK, DENY, check_command, evaluate
except ImportError:
    try:
        from scripts.agentic_ops.core.policy import (  # type: ignore
            ALLOW,
            ASK,
            DENY,
            check_command,
            evaluate,
        )
    except ImportError:
        import importlib.util

        policy_path = (
            Path(__file__).resolve().parents[2] / "kit" / "core" / "policy.py"
        )
        spec = importlib.util.spec_from_file_location("policy", policy_path)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ALLOW, ASK, DENY = mod.ALLOW, mod.ASK, mod.DENY
            check_command = mod.check_command
            evaluate = mod.evaluate
        else:
            raise


class PolicyBridge:
    """Bridges orchestrator governance directly to kit.core.policy without code duplication."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = Path(root_dir).resolve() if root_dir else None
        if self.root_dir:
            _ensure_kit_import(self.root_dir)

    def evaluate_command(self, command: str) -> tuple[str, str]:
        """Evaluate a shell command string against safety policy rules.

        Returns (decision, message) where decision is 'allow', 'ask', or 'deny'.
        """
        return check_command(command)

    def evaluate_read(
        self,
        path: str | Path,
        size: int | None = None,
        limited: bool = False,
    ) -> tuple[str, str]:
        """Evaluate a file read action against size and path rules."""
        return evaluate(read_path=str(path), read_size=size, read_limited=limited)

    def validate_verification_command(self, cmd: str | list[str]) -> tuple[bool, str]:
        """Validate an autonomous verification command before execution.

        Rejects commands that are denied (e.g. sleep loop, identity tampering)
        or that require interactive confirmation (destructive commands).
        """
        if isinstance(cmd, list):
            cmd_str = " ".join(cmd)
        else:
            cmd_str = str(cmd)

        decision, message = self.evaluate_command(cmd_str)
        if decision == ALLOW:
            return True, ""
        elif decision == DENY:
            return False, f"Verification command denied by policy: {message}"
        elif decision == ASK:
            return (
                False,
                f"Destructive verification command blocked by policy (requires interactive approval): {message}",
            )
        return False, f"Command rejected with unknown policy decision '{decision}': {message}"

    def validate_verification_commands(
        self, commands: list[str | list[str]]
    ) -> tuple[bool, list[str]]:
        """Validate a list of declared verification commands."""
        errors: list[str] = []
        for cmd in commands:
            valid, msg = self.validate_verification_command(cmd)
            if not valid:
                errors.append(msg)
        return len(errors) == 0, errors
