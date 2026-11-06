"""Tests for orchestrator/planner/validator.py.

Verifies:
- Plan validation against plan.schema.json
- Rejection of schema violations
- Rejection of plans with protected path collisions
- Rejection of traversal attempts in allowed_paths
- Rejection of cyclic task graphs
"""
import copy
import json
import unittest
from pathlib import Path

from orchestrator.planner.validator import PlanValidator

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
VALID_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.valid.json"
INVALID_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.invalid.json"


class TestPlanValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = PlanValidator()
        with open(VALID_FIXTURE, "r", encoding="utf-8") as f:
            self.valid_plan = json.load(f)

    def test_valid_fixture_passes(self) -> None:
        res = self.validator.validate_plan_dict(self.valid_plan)
        self.assertTrue(res.valid)
        self.assertEqual(len(res.errors), 0)

    def test_invalid_fixture_fails(self) -> None:
        res = self.validator.validate_plan_file(INVALID_FIXTURE)
        self.assertFalse(res.valid)
        self.assertTrue(len(res.errors) > 0)

    def test_protected_path_collision_rejected(self) -> None:
        # Task attempting to modify RULES.md
        bad_plan = copy.deepcopy(self.valid_plan)
        bad_plan["tasks"][0]["allowed_paths"] = ["RULES.md"]
        res = self.validator.validate_plan_dict(bad_plan)
        self.assertFalse(res.valid)
        self.assertTrue(any("overlaps protected path" in e for e in res.errors))

        # Task attempting root path '/'
        bad_plan2 = copy.deepcopy(self.valid_plan)
        bad_plan2["tasks"][0]["allowed_paths"] = ["/"]
        res2 = self.validator.validate_plan_dict(bad_plan2)
        self.assertFalse(res2.valid)
        self.assertTrue(any("forbidden" in e for e in res2.errors))

    def test_traversal_in_allowed_paths_rejected(self) -> None:
        bad_plan = copy.deepcopy(self.valid_plan)
        bad_plan["tasks"][0]["allowed_paths"] = ["src/../../secret.txt"]
        res = self.validator.validate_plan_dict(bad_plan)
        self.assertFalse(res.valid)
        self.assertTrue(any("traversal" in e for e in res.errors))

    def test_cyclic_dag_in_plan_rejected(self) -> None:
        bad_plan = copy.deepcopy(self.valid_plan)
        t2 = copy.deepcopy(bad_plan["tasks"][0])
        t2["task_id"] = "task-002"
        t2["depends_on"] = [bad_plan["tasks"][0]["task_id"]]
        bad_plan["tasks"][0]["depends_on"] = ["task-002"]
        bad_plan["tasks"].append(t2)
        res = self.validator.validate_plan_dict(bad_plan)
        self.assertFalse(res.valid)
        self.assertTrue(any("Cyclic dependency" in e for e in res.errors))


if __name__ == "__main__":
    unittest.main()
