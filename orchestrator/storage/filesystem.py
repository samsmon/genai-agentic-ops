"""Filesystem-based atomic persistence and write-ahead intent logging.

Implements ADR-006:
- Project-local state under .agentic/
- Atomic write-replace using temp files and os.replace
- Write-ahead intent logging (.agentic/runs/intent-<id>.json -> result-<id>.json)
- Crash recovery detection
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any


class FileSystemStorage:
    """Manages atomic file persistence under .agentic/ storage layout."""

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.agentic_dir = self.root_dir / ".agentic"
        self.state_dir = self.agentic_dir / "state"
        self.workflows_dir = self.state_dir / "workflows"
        self.tasks_dir = self.state_dir / "tasks"
        self.plans_dir = self.agentic_dir / "plans"
        self.runs_dir = self.agentic_dir / "runs"
        self.locks_dir = self.agentic_dir / "locks"
        self.ensure_layout()

    def ensure_layout(self) -> None:
        """Create necessary subdirectories if they do not exist."""
        for path in (
            self.workflows_dir,
            self.tasks_dir,
            self.plans_dir,
            self.runs_dir,
            self.locks_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def atomic_write_json(self, target_path: Path | str, data: Any) -> None:
        """Atomically write JSON data to target_path via temp file and os.replace."""
        target = Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        unique_suffix = f"{os.getpid()}.{uuid.uuid4().hex}"
        temp_file = target.parent / f"{target.name}.tmp.{unique_suffix}"

        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, target)
        finally:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def read_json(self, target_path: Path | str) -> Any | None:
        """Safely read and parse a JSON file, returning None if not found."""
        target = Path(target_path)
        if not target.is_file():
            return None
        with open(target, "r", encoding="utf-8") as f:
            return json.load(f)

    # --- Write-Ahead Intent Logging & Crash Detection ---

    def write_intent(self, run_id: str, intent_data: dict[str, Any]) -> Path:
        """Write an intent record before starting execution."""
        path = self.runs_dir / f"intent-{run_id}.json"
        self.atomic_write_json(path, intent_data)
        return path

    def write_result(self, run_id: str, result_data: dict[str, Any]) -> Path:
        """Write execution result record upon process completion."""
        path = self.runs_dir / f"result-{run_id}.json"
        self.atomic_write_json(path, result_data)
        return path

    def load_intent(self, run_id: str) -> dict[str, Any] | None:
        return self.read_json(self.runs_dir / f"intent-{run_id}.json")

    def load_result(self, run_id: str) -> dict[str, Any] | None:
        return self.read_json(self.runs_dir / f"result-{run_id}.json")

    def detect_orphaned_intents(self) -> list[dict[str, Any]]:
        """Return all intents that do not have a matching result.json."""
        orphaned: list[dict[str, Any]] = []
        if not self.runs_dir.is_dir():
            return orphaned

        for intent_file in self.runs_dir.glob("intent-*.json"):
            run_id = intent_file.stem.removeprefix("intent-")
            result_file = self.runs_dir / f"result-{run_id}.json"
            if not result_file.is_file():
                intent_data = self.read_json(intent_file)
                if intent_data:
                    orphaned.append({"run_id": run_id, "intent": intent_data})
        return orphaned

    # --- Workflows, Tasks, Plans, Runs CRUD ---

    def save_workflow(self, workflow_data: dict[str, Any]) -> Path:
        wf_id = workflow_data["workflow_id"]
        path = self.workflows_dir / f"{wf_id}.json"
        self.atomic_write_json(path, workflow_data)
        return path

    def load_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        return self.read_json(self.workflows_dir / f"{workflow_id}.json")

    def list_workflows(self) -> list[dict[str, Any]]:
        workflows: list[dict[str, Any]] = []
        for file in sorted(self.workflows_dir.glob("*.json")):
            data = self.read_json(file)
            if data and isinstance(data, dict):
                workflows.append(data)
        return workflows

    def save_task(self, task_data: dict[str, Any]) -> Path:
        task_id = task_data["task_id"]
        path = self.tasks_dir / f"{task_id}.json"
        self.atomic_write_json(path, task_data)
        return path

    def load_task(self, task_id: str) -> dict[str, Any] | None:
        return self.read_json(self.tasks_dir / f"{task_id}.json")

    def list_tasks(
        self,
        workflow_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for file in sorted(self.tasks_dir.glob("*.json")):
            data = self.read_json(file)
            if not data or not isinstance(data, dict):
                continue
            if workflow_id and data.get("workflow_id") != workflow_id:
                continue
            if status and data.get("status") != status:
                continue
            tasks.append(data)
        return tasks

    def save_plan(self, workflow_id: str, plan_data: dict[str, Any]) -> Path:
        path = self.plans_dir / f"{workflow_id}.json"
        self.atomic_write_json(path, plan_data)
        return path

    def load_plan(self, workflow_id: str) -> dict[str, Any] | None:
        return self.read_json(self.plans_dir / f"{workflow_id}.json")

    def save_run(self, run_id: str, run_data: dict[str, Any]) -> Path:
        filename = f"{run_id}.json" if run_id.startswith("run-") else f"run-{run_id}.json"
        path = self.runs_dir / filename
        self.atomic_write_json(path, run_data)
        return path

    def load_run(self, run_id: str) -> dict[str, Any] | None:
        filename = f"{run_id}.json" if run_id.startswith("run-") else f"run-{run_id}.json"
        res = self.read_json(self.runs_dir / filename)
        if res is not None:
            return res
        if run_id.startswith("run-"):
            return self.read_json(self.runs_dir / f"run-{run_id}.json")
        return None
