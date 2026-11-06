"""Process-verified advisory locking with atomic creation.

Implements advisory locking with:
- Atomic file creation via os.O_CREAT | os.O_EXCL | os.O_WRONLY
- (host, pid, process_start_time) tuple to prevent PID reuse errors
- Stale lock detection and safe breaking
"""
from __future__ import annotations

import datetime
import json
import os
import uuid
from pathlib import Path
from typing import Any

from orchestrator.governance.process_info import get_host_tuple, is_process_alive

DEFAULT_LOCK_TTL_SECONDS = 7200  # 2 hours per Threat Model & Rule 3


class LockError(Exception):
    """Base exception for lock operations."""


class LockAcquisitionError(LockError):
    """Raised when acquiring a lock fails because it is already held."""


class LockReleaseError(LockError):
    """Raised when releasing a lock fails."""


class LockManager:
    """Manages advisory locks in .agentic/locks/."""

    def __init__(self, locks_dir: str | Path) -> None:
        self.locks_dir = Path(locks_dir).resolve()
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.locks_dir / "lock.json"
        self.active_file = self.locks_dir / "active.json"

    def acquire(
        self,
        task_id: str,
        workflow_id: str,
        ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS,
        allowed_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Attempt to acquire the advisory lock atomically.

        Raises LockAcquisitionError if lock already exists and is not stale.
        """
        host_info = get_host_tuple()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        lock_id = f"lock-{uuid.uuid4().hex[:12]}"

        lock_data = {
            "schema_version": "1.0",
            "lock_id": lock_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "allowed_paths": allowed_paths or [],
            "host": host_info,
            "acquired_at": now,
            "ttl_seconds": ttl_seconds,
        }

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(self.lock_file, flags, 0o644)
        except FileExistsError:
            # Lock file exists; diagnose whether it is stale
            stale, reason = self.is_stale()
            if stale:
                raise LockAcquisitionError(
                    f"Lock is held but stale ({reason}). Break stale lock before acquiring."
                )
            existing = self.read_lock() or {}
            holder = existing.get("host", {})
            raise LockAcquisitionError(
                f"Advisory lock is held by pid {holder.get('pid')} on {holder.get('hostname')}"
            )

        try:
            content = json.dumps(lock_data, indent=2).encode("utf-8")
            os.write(fd, content)
            with open(self.active_file, "wb") as f_act:
                f_act.write(content)
        finally:
            os.close(fd)

        return lock_data

    def read_lock(self) -> dict[str, Any] | None:
        """Read and parse lock file if present."""
        if not self.lock_file.is_file():
            return None
        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def read_active(self) -> dict[str, Any] | None:
        """Read and parse active lock file if present."""
        if not self.active_file.is_file():
            return None
        try:
            with open(self.active_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def release(self, force: bool = False) -> None:
        """Release the advisory lock.

        If force is False, validates that the current process owns the lock.
        """
        if not self.lock_file.exists() and not self.active_file.exists():
            return

        lock_data = self.read_lock()
        if not force and lock_data:
            current_host = get_host_tuple()
            lock_host = lock_data.get("host", {})
            if (
                lock_host.get("hostname") != current_host.get("hostname")
                or lock_host.get("pid") != current_host.get("pid")
                or lock_host.get("process_start_time")
                != current_host.get("process_start_time")
            ):
                raise LockReleaseError(
                    "Cannot release lock owned by different process without force=True"
                )

        try:
            self.lock_file.unlink(missing_ok=True)
            self.active_file.unlink(missing_ok=True)
        except OSError as e:
            raise LockReleaseError(f"Failed to remove lock file: {e}") from e

    def is_stale(self) -> tuple[bool, str]:
        """Diagnose whether the current lock file is stale.

        Returns (is_stale, reason).
        """
        lock_data = self.read_lock()
        if lock_data is None:
            if self.lock_file.exists():
                return True, "Lock file is corrupted or unreadable"
            return False, "No active lock"

        host = lock_data.get("host", {})
        hostname = host.get("hostname", "")
        pid = host.get("pid", 0)
        start_time = host.get("process_start_time", "")

        # 1. Check process aliveness on local host
        alive = is_process_alive(hostname, pid, start_time)
        if alive is False:
            return True, f"Holding process (PID {pid} on {hostname}) is terminated"

        # 2. Check TTL expiration
        acquired_at_str = lock_data.get("acquired_at")
        ttl = lock_data.get("ttl_seconds", DEFAULT_LOCK_TTL_SECONDS)
        if acquired_at_str:
            try:
                acquired_at = datetime.datetime.fromisoformat(acquired_at_str)
                now = datetime.datetime.now(datetime.timezone.utc)
                if (now - acquired_at).total_seconds() > ttl:
                    return True, f"Lock TTL exceeded ({ttl}s elapsed)"
            except ValueError:
                return True, "Invalid acquired_at timestamp"

        return False, "Lock is actively held"

    def break_stale_lock(self) -> bool:
        """Break the lock if stale. Returns True if broken, False if active."""
        stale, reason = self.is_stale()
        if not stale:
            return False
        self.release(force=True)
        return True
