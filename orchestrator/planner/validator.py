"""Plan schema validation, path safety checks, and DAG verification.

Validates plans against contracts/plan.schema.json, verifies that allowed_paths
do not collide with built-in protected paths, and checks DAG acyclicity.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from orchestrator.core.workflow_engine import WorkflowEngine, WorkflowGraphError
from orchestrator.governance.protected_paths import check_path_overlap_with_protected


@dataclass
class PlanValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    plan_data: dict[str, Any] | None = None


class PlanValidator:
    """Validates execution plans for schema compliance, path safety, and DAG integrity."""

    def __init__(self, schema_path: str | Path | None = None) -> None:
        if schema_path is None:
            # Default to contracts/plan.schema.json relative to repository root
            here = Path(__file__).resolve().parent
            repo_root = here.parent.parent
            schema_path = repo_root / "contracts" / "plan.schema.json"

        self.schema_path = Path(schema_path).resolve()
        if not self.schema_path.is_file():
            raise FileNotFoundError(f"Plan schema not found at: {self.schema_path}")

        with open(self.schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)
        self.validator = Draft7Validator(self.schema)

    def validate_plan_dict(self, plan_data: dict[str, Any]) -> PlanValidationResult:
        """Validate an in-memory plan dictionary."""
        errors: list[str] = []

        # 1. JSON Schema validation
        schema_errors = list(self.validator.iter_errors(plan_data))
        for err in schema_errors:
            loc = ".".join(str(p) for p in err.path) if err.path else "root"
            errors.append(f"Schema violation at {loc}: {err.message}")

        if errors:
            return PlanValidationResult(valid=False, errors=errors, plan_data=plan_data)

        # 2. Path safety and protected path collision checks
        tasks = plan_data.get("tasks", [])
        for task in tasks:
            task_id = task.get("task_id", "unknown")
            allowed = task.get("allowed_paths", [])
            conflicts = check_path_overlap_with_protected(allowed)
            for c in conflicts:
                errors.append(f"Task '{task_id}' path violation: {c}")

            # Check for path traversal attempts
            for p in allowed:
                if ".." in p.replace("\\", "/").split("/"):
                    errors.append(
                        f"Task '{task_id}' path violation: traversal ('..') forbidden in '{p}'"
                    )

        # 3. DAG acyclicity check
        try:
            WorkflowEngine.validate_dag(tasks)
        except WorkflowGraphError as e:
            errors.append(f"Workflow dependency error: {e}")

        is_valid = len(errors) == 0
        return PlanValidationResult(valid=is_valid, errors=errors, plan_data=plan_data)

    def validate_plan_file(self, plan_file: str | Path) -> PlanValidationResult:
        """Read and validate a plan JSON file from disk."""
        target = Path(plan_file).resolve()
        if not target.is_file():
            return PlanValidationResult(
                valid=False, errors=[f"Plan file not found: {plan_file}"]
            )

        try:
            with open(target, "r", encoding="utf-8") as f:
                plan_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return PlanValidationResult(
                valid=False, errors=[f"Failed to parse plan JSON: {e}"]
            )

        return self.validate_plan_dict(plan_data)
