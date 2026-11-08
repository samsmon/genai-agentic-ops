"""Cross-platform subprocess runner with environment sanitization and process-tree termination.

Implements ADR-005 requirements:
- Explicit ANTHROPIC_API_KEY environment sanitization.
- Clean process tree termination on timeout or interrupt (taskkill /T /F on Windows,
  process group kill on POSIX) to prevent orphan child processes.
- Stdin piping, stdout/stderr capture with size caps, and duration measurement.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from orchestrator.adapters.base import ExecutionResult

DEFAULT_MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MB


def sanitize_environment(
    env_overrides: dict[str, str] | None = None,
    strip_anthropic_api_key: bool = True,
) -> dict[str, str]:
    """Sanitize environment variables for child processes.

    Protects user from accidental subscription-to-paid API switch by stripping
    ANTHROPIC_API_KEY by default unless explicitly configured in env_overrides.
    """
    env = os.environ.copy()
    if strip_anthropic_api_key and (not env_overrides or "ANTHROPIC_API_KEY" not in env_overrides):
        env.pop("ANTHROPIC_API_KEY", None)

    env["AGENTIC_NON_INTERACTIVE"] = "1"
    if env_overrides:
        env.update(env_overrides)
    return env


def terminate_process_tree(pid: int, timeout_sec: float = 3.0) -> None:
    """Terminate a process and all descendant processes cross-platform."""
    if pid <= 0:
        return

    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout_sec,
            )
        except Exception:
            pass
    else:
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def cap_output_string(output: str, max_bytes: int = DEFAULT_MAX_OUTPUT_BYTES) -> str:
    """Cap output string to prevent unbounded memory growth."""
    encoded = output.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return output

    capped = encoded[:max_bytes].decode("utf-8", errors="replace")
    return f"{capped}\n[output truncated at {max_bytes} bytes]"


class ProcessRunner:
    """Subprocess runner managing environment, piping, timeouts, and process trees."""

    def __init__(self) -> None:
        self._active_processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | str | None = None,
        stdin_input: str | None = None,
        env_overrides: dict[str, str] | None = None,
        strip_anthropic_api_key: bool = True,
        timeout_seconds: float | None = None,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        run_handle: str | None = None,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> ExecutionResult:
        """Run command synchronously with environment sanitization and process-tree supervision."""
        handle = run_handle or f"run-{uuid.uuid4().hex[:8]}"
        env = sanitize_environment(
            env_overrides=env_overrides,
            strip_anthropic_api_key=strip_anthropic_api_key,
        )

        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE if stdin_input is not None else None,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": str(cwd) if cwd else None,
            "env": env,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }

        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        start_time = time.monotonic()
        timed_out = False
        stdout_str = ""
        stderr_str = ""
        exit_code = -1

        try:
            proc = subprocess.Popen(command, **popen_kwargs)
            with self._lock:
                self._active_processes[handle] = proc

            try:
                stdout_str, stderr_str = proc.communicate(
                    input=stdin_input, timeout=timeout_seconds
                )
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                terminate_process_tree(proc.pid)
                # Read partial output if any
                try:
                    stdout_str, stderr_str = proc.communicate(timeout=1.0)
                except Exception:
                    pass
                exit_code = -1
        except FileNotFoundError as err:
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=127,
                status="failed",
                stdout="",
                stderr=f"Executable not found: {err}",
                duration_seconds=duration,
            )
        except Exception as err:
            duration = time.monotonic() - start_time
            return ExecutionResult(
                exit_code=1,
                status="failed",
                stdout="",
                stderr=f"Subprocess spawn error: {err}",
                duration_seconds=duration,
            )
        finally:
            with self._lock:
                self._active_processes.pop(handle, None)

        duration = time.monotonic() - start_time
        stdout_capped = cap_output_string(stdout_str or "", max_bytes=max_output_bytes)
        stderr_capped = cap_output_string(stderr_str or "", max_bytes=max_output_bytes)

        stdout_ref = None
        stderr_ref = None
        if stdout_path:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_path.write_text(stdout_capped, encoding="utf-8")
            stdout_ref = str(stdout_path)

        if stderr_path:
            stderr_path.parent.mkdir(parents=True, exist_ok=True)
            stderr_path.write_text(stderr_capped, encoding="utf-8")
            stderr_ref = str(stderr_path)

        if timed_out:
            status = "timed_out"
        elif exit_code == 0:
            status = "completed"
        else:
            status = "failed"

        return ExecutionResult(
            exit_code=exit_code,
            status=status,
            stdout=stdout_capped,
            stderr=stderr_capped,
            stdout_ref=stdout_ref,
            stderr_ref=stderr_ref,
            duration_seconds=duration,
        )

    def interrupt(self, run_handle: str) -> bool:
        """Interrupt active process tree registered under run_handle."""
        with self._lock:
            proc = self._active_processes.get(run_handle)

        if proc and proc.pid:
            terminate_process_tree(proc.pid)
            return True
        return False
