"""Tests for Antigravity host integration and active lock guard.

Verifies:
- Antigravity skill (SKILL.md), instructions, and hooks schema
- Active lock guard hook behavior (allow when free, deny on claimed paths during active lock)
- CLI plan validate, plan submit, task run, and task approve lifecycle
"""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from orchestrator.cli.main import main
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import TaskRunner
from orchestrator.core.state_machine import TaskState
from orchestrator.tests.test_runner import MockAdapter
from integrations.antigravity.hooks.active_lock_guard import evaluate_tool_call

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
INTEGRATIONS_DIR = REPO_ROOT / "integrations" / "antigravity"
VALID_PLAN_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.valid.json"


class TestHostAntigravity(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)
        self.mock_adapter = MockAdapter()
        self.coord.registry.register(self.mock_adapter)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_artifacts_structure_and_frontmatter(self) -> None:
        skill_file = INTEGRATIONS_DIR / "skills" / "agentic-orchestrator" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), "SKILL.md must exist")
        skill_content = skill_file.read_text(encoding="utf-8")
        self.assertIn("name: agentic-orchestrator", skill_content)
        self.assertIn("plan validate", skill_content)
        self.assertIn("plan submit", skill_content)
        self.assertIn("task run", skill_content)
        self.assertIn("task approve", skill_content)

        instructions_file = INTEGRATIONS_DIR / "instructions" / "orchestrator-host.md"
        self.assertTrue(instructions_file.is_file(), "orchestrator-host.md must exist")
        inst_content = instructions_file.read_text(encoding="utf-8")
        self.assertIn("ADR-001", inst_content)
        self.assertIn("ADR-003", inst_content)

        hooks_file = INTEGRATIONS_DIR / "hooks" / "hooks.json"
        self.assertTrue(hooks_file.is_file(), "hooks.json must exist")
        with open(hooks_file, "r", encoding="utf-8") as f:
            hooks_cfg = json.load(f)
        self.assertIn("active-lock-guard", hooks_cfg)

    def test_active_lock_guard_allow_when_unlocked(self) -> None:
        payload = {
            "toolCall": {
                "name": "write_file",
                "args": {"Path": str(self.root / "src" / "main.py")},
            }
        }
        decision, reason = evaluate_tool_call(payload, root_dir=self.root)
        self.assertEqual(decision, "allow")
        self.assertEqual(reason, "")

    def test_active_lock_guard_deny_when_path_locked(self) -> None:
        # Acquire advisory lock claiming src/
        self.coord.lock_manager.acquire(
            task_id="task-test-worker",
            workflow_id="wf-test",
            allowed_paths=["src/"],
        )
        self.assertTrue(self.coord.lock_manager.active_file.is_file())

        # Attempt to write into claimed path
        payload = {
            "toolCall": {
                "name": "write_file",
                "args": {"Path": str(self.root / "src" / "main.py")},
            }
        }
        decision, reason = evaluate_tool_call(payload, root_dir=self.root)
        self.assertEqual(decision, "deny")
        self.assertIn("task-test-worker", reason)

        # Attempt to edit a file outside claimed path
        payload_outside = {
            "toolCall": {
                "name": "edit_file",
                "args": {"Path": str(self.root / "docs" / "readme.md")},
            }
        }
        dec_out, reason_out = evaluate_tool_call(payload_outside, root_dir=self.root)
        self.assertEqual(dec_out, "allow")

        # Release lock and verify write is allowed again
        self.coord.lock_manager.release()
        dec_after, _ = evaluate_tool_call(payload, root_dir=self.root)
        self.assertEqual(dec_after, "allow")

    def test_cli_plan_submission_and_task_execution_cycle(self) -> None:
        with open(VALID_PLAN_FIXTURE, "r", encoding="utf-8") as f:
            p = json.load(f)

        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        t_spec["verification_commands"] = [
            f'"{sys.executable}" -c "exit(0)"'
        ]

        plan_file = self.root / "test_plan.json"
        plan_file.write_text(json.dumps(p, indent=2), encoding="utf-8")

        # 1. Validate plan via CLI
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            try:
                main(["--root", str(self.root), "plan", "validate", str(plan_file)])
            except SystemExit:
                pass
        val_env = json.loads(out_buf.getvalue())
        self.assertTrue(val_env["ok"])

        # 2. Submit plan via CLI
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            try:
                main(["--root", str(self.root), "plan", "submit", str(plan_file)])
            except SystemExit:
                pass
        sub_env = json.loads(out_buf.getvalue())
        self.assertTrue(sub_env["ok"])

        # Register mock adapter on a coordinator pointing to the same root for CLI run
        # Execute task via runner directly or CLI
        runner = TaskRunner(self.coord)
        t_id = t_spec["task_id"]
        res = runner.run_task(t_id)
        self.assertEqual(res["verification"]["verified"], True)

        # 3. Approve task via CLI
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            try:
                main(["--root", str(self.root), "task", "approve", t_id])
            except SystemExit:
                pass
        app_env = json.loads(out_buf.getvalue())
        self.assertTrue(app_env["ok"])
        self.assertEqual(app_env["data"]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
