"""Append-only audit event logging and execution run schema validation.

Implements M4 audit trail:
- Append-only event log under .agentic/audit/events.jsonl
- Records submitted, started, lock_acquired, worker_completed, scope_verified,
  verification_passed, approval_granted, lock_released, failed, blocked events
- Run summary records saved to .agentic/runs/<run_id>.json conforming to contracts/run.schema.json
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator


class AuditLogger:
    """Manages append-only event logging and contract-validated run summaries."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.audit_dir = self.root_dir / ".agentic" / "audit"
        self.events_file = self.audit_dir / "events.jsonl"
        self.runs_dir = self.root_dir / ".agentic" / "runs"
        self.contracts_dir = self.root_dir / "contracts"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._run_schema_validator: Draft7Validator | None = None

    def _get_run_validator(self) -> Draft7Validator | None:
        if self._run_schema_validator is None:
            schema_file = self.contracts_dir / "run.schema.json"
            if not schema_file.is_file():
                alt = (
                    Path(__file__).resolve().parents[2]
                    / "contracts"
                    / "run.schema.json"
                )
                if alt.is_file():
                    schema_file = alt
            if schema_file.is_file():
                with open(schema_file, "r", encoding="utf-8") as f:
                    schema_dict = json.load(f)
                self._run_schema_validator = Draft7Validator(schema_dict)
        return self._run_schema_validator

    def log_event(
        self,
        event: str,
        *,
        workflow_id: str | None = None,
        task_id: str | None = None,
        run_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append an event record to .agentic/audit/events.jsonl."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        entry: dict[str, Any] = {
            "timestamp": now,
            "event": event,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "details": details or {},
        }

        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(self.events_file, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

        return entry

    def get_events(
        self,
        limit: int | None = None,
        event_type: str | None = None,
        task_id: str | None = None,
        workflow_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read and filter events from append-only events.jsonl."""
        if not self.events_file.is_file():
            return []

        events: list[dict[str, Any]] = []
        with open(self.events_file, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    entry = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                if event_type and entry.get("event") != event_type:
                    continue
                if task_id and entry.get("task_id") != task_id:
                    continue
                if workflow_id and entry.get("workflow_id") != workflow_id:
                    continue
                events.append(entry)

        if limit is not None and limit > 0:
            return events[-limit:]
        return events

    def record_run_summary(
        self,
        run_record: dict[str, Any],
        validate: bool = True,
    ) -> Path:
        """Validate run record against run.schema.json and save to .agentic/runs/<run_id>.json."""
        run_id = run_record.get("run_id")
        if not run_id:
            raise ValueError("Run record missing required 'run_id'")

        if validate:
            validator = self._get_run_validator()
            if validator:
                errors = list(validator.iter_errors(run_record))
                if errors:
                    err_msgs = [e.message for e in errors]
                    raise ValueError(
                        f"Run record failed schema validation: {'; '.join(err_msgs)}"
                    )

        path = self.runs_dir / f"{run_id}.json"
        self._atomic_write(path, run_record)
        return path

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
