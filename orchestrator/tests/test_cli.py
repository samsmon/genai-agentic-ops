"""Tests for orchestrator/cli/main.py.

Verifies:
- JSON envelope format
- Exit codes (0 for success, 1 for error)
- CLI commands: doctor, plan validate, plan submit, task list, task show, status
"""
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from orchestrator.cli.main import main

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
VALID_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.valid.json"
INVALID_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.invalid.json"


class TestCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run_cli(self, args: list[str]) -> tuple[int, dict]:
        full_args = ["--root", str(self.root)] + args
        buf = io.StringIO()
        exit_code = 0
        try:
            with redirect_stdout(buf):
                main(full_args)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 0

        raw_output = buf.getvalue().strip()
        data = json.loads(raw_output) if raw_output else {}
        return exit_code, data

    def test_cli_doctor(self) -> None:
        code, out = self._run_cli(["doctor"])
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["schema_version"], "1.0")
        self.assertIn("checks", out["data"])

    def test_cli_plan_validate_success(self) -> None:
        code, out = self._run_cli(["plan", "validate", str(VALID_FIXTURE)])
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertTrue(out["data"]["valid"])

    def test_cli_plan_validate_failure(self) -> None:
        code, out = self._run_cli(["plan", "validate", str(INVALID_FIXTURE)])
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "PLAN_INVALID")

    def test_cli_plan_submit_and_task_queries(self) -> None:
        # Submit valid plan
        code, out = self._run_cli(["plan", "submit", str(VALID_FIXTURE)])
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        wf_id = out["data"]["workflow_id"]

        # List tasks
        code, tlist = self._run_cli(["task", "list", "--workflow-id", wf_id])
        self.assertEqual(code, 0)
        self.assertTrue(tlist["ok"])
        self.assertGreater(tlist["data"]["count"], 0)

        # Show task
        first_task_id = tlist["data"]["tasks"][0]["task_id"]
        code, tshow = self._run_cli(["task", "show", first_task_id])
        self.assertEqual(code, 0)
        self.assertTrue(tshow["ok"])
        self.assertEqual(tshow["data"]["task_id"], first_task_id)

        # Status
        code, stat = self._run_cli(["status", "--workflow-id", wf_id])
        self.assertEqual(code, 0)
        self.assertTrue(stat["ok"])
        self.assertEqual(stat["data"]["workflow"]["workflow_id"], wf_id)


if __name__ == "__main__":
    unittest.main()
