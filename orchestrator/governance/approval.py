"""Human Approval Hardening and Cryptographic One-Time Authorization Tokens.

Implements M4 human approval gates:
- Cryptographically secure one-time tokens stored under .agentic/approvals/<task_id>.json
- Prevents autonomous agent self-approval (Claude Sonnet architectural review vulnerability)
- Timing-safe token validation and atomic consumption
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any


def _hash_token(token: str) -> str:
    """Compute SHA-256 hex digest of an approval token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_interactive_environment() -> None:
    """Reject approval operations when invoked from a headless worker environment."""
    if os.environ.get("AGENTIC_NON_INTERACTIVE") == "1":
        raise ValueError(
            "Approval operations are forbidden in non-interactive worker sessions (AGENTIC_NON_INTERACTIVE=1)"
        )



class ApprovalManager:
    """Manages human approval tokens, authorization requests, and verification."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.approvals_dir = self.root_dir / ".agentic" / "approvals"
        self.approvals_dir.mkdir(parents=True, exist_ok=True)

    def _approval_file(self, task_id: str) -> Path:
        return self.approvals_dir / f"{task_id}.json"

    def has_pending_approval(self, task_id: str) -> bool:
        """Check if an approval request is pending for task_id."""
        record = self.get_approval(task_id)
        return bool(record and record.get("status") == "pending")

    def get_approval(self, task_id: str) -> dict[str, Any] | None:
        """Load approval record for task_id if present."""
        path = self._approval_file(task_id)
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def request_approval(
        self,
        task_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate a cryptographically secure one-time token and write approval request."""
        token = secrets.token_urlsafe(32)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "schema_version": "1.0",
            "task_id": task_id,
            "token": token,
            "token_hash": _hash_token(token),
            "status": "pending",
            "created_at": now,
            "context": context or {},
            "prompt": (
                f"Human approval required for task '{task_id}'. "
                f"To grant approval, run: agentic approval grant {task_id} --token {token}"
            ),
        }

        path = self._approval_file(task_id)
        self._atomic_write(path, record)
        return record

    def grant_approval(
        self,
        task_id: str,
        token: str,
        approver: str = "human",
    ) -> dict[str, Any]:
        """Validate one-time token, atomically consume it, and record approval.

        Raises ValueError if approval is missing, not pending, or token is invalid.
        """
        ensure_interactive_environment()
        if not token or not isinstance(token, str):
            raise ValueError(f"Approval token is required to grant approval for task '{task_id}'")

        record = self.get_approval(task_id)
        if not record:
            raise ValueError(f"No approval request found for task '{task_id}'")

        if record.get("status") != "pending":
            raise ValueError(
                f"Cannot grant approval for task '{task_id}': status is already '{record.get('status')}'"
            )

        stored_hash = record.get("token_hash")
        stored_token = record.get("token") or ""
        # Timing-safe token comparison (supports both token_hash and legacy token)
        if stored_hash:
            valid = hmac.compare_digest(stored_hash, _hash_token(token))
        else:
            valid = hmac.compare_digest(stored_token, token)

        if not valid:
            raise ValueError(
                f"Invalid approval token for task '{task_id}': token does not match active authorization request"
            )

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record["status"] = "granted"
        record["granted_by"] = approver
        record["granted_at"] = now
        record["consumed"] = True
        record["token"] = None  # Consume token so it cannot be reused
        record["token_hash"] = None

        path = self._approval_file(task_id)
        self._atomic_write(path, record)
        return record

    def deny_approval(
        self,
        task_id: str,
        token: str,
        reason: str = "",
        approver: str = "human",
    ) -> dict[str, Any]:
        """Deny approval using one-time token."""
        ensure_interactive_environment()
        if not token or not isinstance(token, str):
            raise ValueError(f"Approval token is required to deny approval for task '{task_id}'")

        record = self.get_approval(task_id)
        if not record:
            raise ValueError(f"No approval request found for task '{task_id}'")

        if record.get("status") != "pending":
            raise ValueError(
                f"Cannot deny approval for task '{task_id}': status is already '{record.get('status')}'"
            )

        stored_hash = record.get("token_hash")
        stored_token = record.get("token") or ""
        if stored_hash:
            valid = hmac.compare_digest(stored_hash, _hash_token(token))
        else:
            valid = hmac.compare_digest(stored_token, token)

        if not valid:
            raise ValueError(
                f"Invalid approval token for task '{task_id}': token does not match active authorization request"
            )

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record["status"] = "denied"
        record["denied_by"] = approver
        record["denied_at"] = now
        record["reason"] = reason
        record["consumed"] = True
        record["token"] = None
        record["token_hash"] = None

        path = self._approval_file(task_id)
        self._atomic_write(path, record)
        return record

    def list_approvals(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all approval requests matching optional status filter."""
        results: list[dict[str, Any]] = []
        for file in sorted(self.approvals_dir.glob("*.json")):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    rec = json.load(f)
                    if status is None or rec.get("status") == status:
                        results.append(rec)
            except (OSError, json.JSONDecodeError):
                continue
        return results

    def _atomic_write(self, target_path: Path, data: Any) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = target_path.parent / f"{target_path.name}.tmp.{os.getpid()}"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target_path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
