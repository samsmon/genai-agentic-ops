"""Shared host conformance test suite for genai-agentic-ops.

Validates that all host integrations (Antigravity, Claude Code, Codex, Gemini CLI):
1. Contain valid SKILL.md metadata, instructions, and host definitions.
2. Adhere to the same plan submission protocol (plan validate, plan submit).
3. Enforce identical lock guard semantics (denying modifications to claimed paths).
4. Follow the exact same CLI contracts and JSON envelopes.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from orchestrator.cli.main import main
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import TaskRunner
from orchestrator.tests.test_runner import MockAdapter

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
INTEGRATIONS_DIR = REPO_ROOT / "integrations"
HOSTS = ["antigravity", "claude-code", "codex", "gemini-cli"]


def _load_guard_module(host: str) -> Any:
    """Dynamically load active_lock_guard module for a given host."""
    guard_path = INTEGRATIONS_DIR / host / "hooks" / "active_lock_guard.py"
    if not guard_path.is_file():
        raise FileNotFoundError(f"Guard script missing for host {host}: {guard_path}")

    spec = importlib.util.spec_from_file_location(f"{host}_lock_guard", guard_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {guard_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_cli(root: Path, *args: str) -> dict[str, Any]:
    """Execute orchestrator CLI and parse JSON envelope output."""
    out_buf = io.StringIO()
    orig_argv = sys.argv[:]
    try:
        sys.argv = ["agentic", "--root", str(root)] + list(args)
        with redirect_stdout(out_buf):
            try:
                main(["--root", str(root)] + list(args))
            except SystemExit:
                pass
    finally:
        sys.argv = orig_argv

    raw = out_buf.getvalue().strip()
    return json.loads(raw) if raw else {}


class TestHostConformance(unittest.TestCase):
    """Shared conformance test suite across all supported host coding assistants."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)
        self.mock_adapter = MockAdapter()
        self.coord.registry.register(self.mock_adapter)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_host_artifacts_and_metadata_conformance(self) -> None:
        """Every host must define valid SKILL.md, host instructions, and hooks."""
        for host in HOSTS:
            host_dir = INTEGRATIONS_DIR / host
            self.assertTrue(host_dir.is_dir(), f"Host directory missing: {host_dir}")

            # 1. SKILL.md validation
            skill_file = host_dir / "skills" / "agentic-orchestrator" / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"SKILL.md missing for host: {host}")
            skill_text = skill_file.read_text(encoding="utf-8")
            self.assertTrue(skill_text.startswith("---"), f"YAML frontmatter missing in {host}")
            for kw in ("name: agentic-orchestrator", "plan validate", "plan submit", "task run", "task approve"):
                self.assertIn(kw, skill_text)

            # 2. Host instructions validation
            instructions_file = host_dir / "instructions" / "orchestrator-host.md"
            self.assertTrue(instructions_file.is_file(), f"Instructions missing for host: {host}")
            inst_text = instructions_file.read_text(encoding="utf-8")
            self.assertIn("ADR-001", inst_text)
            self.assertIn("ADR-003", inst_text)
            self.assertTrue("ADR-004" in inst_text or "ADR-007" in inst_text)

            # 3. Hooks configuration validation
            hooks_file = host_dir / "hooks" / "hooks.json"
            self.assertTrue(hooks_file.is_file(), f"hooks.json missing for host: {host}")
            with open(hooks_file, "r", encoding="utf-8") as f:
                hooks_cfg = json.load(f)
            self.assertIn("active-lock-guard", hooks_cfg)

            # 4. Gemini CLI specific command definition validation
            if host == "gemini-cli":
                cmd_file = host_dir / "commands" / "agentic.toml"
                self.assertTrue(cmd_file.is_file(), "agentic.toml missing for gemini-cli")
                cmd_text = cmd_file.read_text(encoding="utf-8")
                for cmd_name in ("[commands.plan-validate]", "[commands.plan-submit]", "[commands.task-run]"):
                    self.assertIn(cmd_name, cmd_text)

    def test_host_lock_guard_semantics_conformance(self) -> None:
        """Lock guard hooks across all hosts must enforce identical deny/allow semantics."""
        for host in HOSTS:
            guard_mod = _load_guard_module(host)
            eval_fn = getattr(guard_mod, "evaluate_tool_call", None)
            self.assertTrue(callable(eval_fn), f"evaluate_tool_call missing in {host} lock guard")

            # A. Allow when no active lock exists
            payload_antigravity = {
                "toolCall": {"name": "write_file", "args": {"Path": str(self.root / "src" / "main.py")}}
            }
            payload_claude_edit = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.root / "src" / "main.py")},
            }
            payload_claude_write = {
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / "src" / "main.py")},
            }

            for p in (payload_antigravity, payload_claude_edit, payload_claude_write):
                decision, reason = eval_fn(p, root_dir=self.root)
                self.assertEqual(decision, "allow", f"{host} failed to allow when free")
                self.assertEqual(reason, "")

            # B. Acquire lock claiming src/
            self.coord.lock_manager.acquire(
                task_id=f"task-worker-{host}",
                workflow_id=f"wf-{host}",
                allowed_paths=["src/"],
            )

            # C. Must deny modifications targeting claimed path across all payload formats
            for p in (payload_antigravity, payload_claude_edit, payload_claude_write):
                decision, reason = eval_fn(p, root_dir=self.root)
                self.assertEqual(decision, "deny", f"{host} failed to deny claimed path")
                self.assertIn(f"task-worker-{host}", reason)

            # D. Must allow modifications outside claimed path
            payload_outside = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(self.root / "docs" / "readme.md")},
            }
            decision, reason = eval_fn(payload_outside, root_dir=self.root)
            self.assertEqual(decision, "allow", f"{host} failed to allow unclaimed path")
            self.assertEqual(reason, "")

            # E. Release lock and verify write allowed again
            self.coord.lock_manager.release()
            decision_after, _ = eval_fn(payload_antigravity, root_dir=self.root)
            self.assertEqual(decision_after, "allow", f"{host} failed to allow after lock release")

    def test_host_plan_submission_protocol_conformance(self) -> None:
        """Every host integration adheres to identical plan validate and submit CLI contracts."""
        for host in HOSTS:
            plan_obj = {
                "schema_version": "1.0",
                "workflow_id": f"wf-{host}-flow",
                "title": f"Initiative formulated by {host}",
                "description": "Cross-host conformance plan",
                "planner": {"id": host, "runtime": host, "attested": False},
                "execution_mode": "sequential",
                "approval_required": False,
                "tasks": [
                    {
                        "task_id": f"task-{host}-01",
                        "title": f"Task executed by {host}",
                        "description": "Compile and verify",
                        "role": "developer",
                        "runtime": host,
                        "allowed_paths": ["src/"],
                        "acceptance_criteria": ["All tests pass"],
                        "verification_commands": [f'"{sys.executable}" -c "exit(0)"'],
                    }
                ],
            }

            plan_dir = self.root / ".agentic" / "plans"
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_file = plan_dir / f"{plan_obj['workflow_id']}.json"
            plan_file.write_text(json.dumps(plan_obj, indent=2), encoding="utf-8")

            # 1. Test CLI plan validate
            val_env = _run_cli(self.root, "plan", "validate", str(plan_file))
            self.assertEqual(val_env.get("schema_version"), "1.0")
            self.assertTrue(val_env.get("ok"), f"Plan validation failed for host {host}: {val_env}")
            self.assertEqual(val_env["data"]["workflow_id"], plan_obj["workflow_id"])

            # 2. Test CLI plan submit
            sub_env = _run_cli(self.root, "plan", "submit", str(plan_file))
            self.assertEqual(sub_env.get("schema_version"), "1.0")
            self.assertTrue(sub_env.get("ok"), f"Plan submit failed for host {host}: {sub_env}")
            self.assertIn("workflow_id", sub_env["data"])

            # 3. Verify task persisted and in 'ready' state
            t_file = self.root / ".agentic" / "state" / "tasks" / f"task-{host}-01.json"
            self.assertTrue(t_file.is_file(), f"Task state file missing for {host}")
            with open(t_file, "r", encoding="utf-8") as f:
                t_data = json.load(f)
            self.assertEqual(t_data["status"], "ready")

    def test_host_cli_envelope_and_approval_contract(self) -> None:
        """CLI interactions across all hosts conform to uniform JSON envelopes and approval tokens."""
        # A. Validation error envelope check
        bad_plan = self.root / "invalid_plan.json"
        bad_plan.write_text(json.dumps({"invalid": "data"}), encoding="utf-8")
        err_env = _run_cli(self.root, "plan", "validate", str(bad_plan))
        self.assertEqual(err_env.get("schema_version"), "1.0")
        self.assertFalse(err_env.get("ok"))
        self.assertIsNotNone(err_env.get("error"))
        self.assertIn("code", err_env["error"])

        # B. End-to-end task execution and approval cycle
        plan_obj = {
            "schema_version": "1.0",
            "workflow_id": "wf-approval-flow",
            "title": "Approval Lifecycle Test",
            "planner": {"id": "claude-code", "runtime": "claude-code", "attested": False},
            "execution_mode": "sequential",
            "approval_required": True,
            "tasks": [
                {
                    "task_id": "task-app-01",
                    "title": "Approval Gated Task",
                    "role": "developer",
                    "runtime": "antigravity",
                    "allowed_paths": ["src/"],
                    "acceptance_criteria": ["Tests pass"],
                    "verification_commands": [f'"{sys.executable}" -c "exit(0)"'],
                }
            ],
        }
        plan_file = self.root / "app_plan.json"
        plan_file.write_text(json.dumps(plan_obj), encoding="utf-8")

        sub_env = _run_cli(self.root, "plan", "submit", str(plan_file))
        self.assertTrue(sub_env.get("ok"))

        # Execute task using runner
        runner = TaskRunner(self.coord)
        res = runner.run_task("task-app-01")
        self.assertTrue(res["verification"]["verified"])

        # Check approval show envelope
        app_env = _run_cli(self.root, "approval", "show", "task-app-01")
        self.assertTrue(app_env.get("ok"))
        token = app_env["data"]["approval"]["token"]
        self.assertTrue(len(token) > 0)

        # Grant approval with token via CLI
        grant_env = _run_cli(self.root, "approval", "grant", "task-app-01", "--token", token, "--approver", "developer")
        self.assertTrue(grant_env.get("ok"))
        self.assertEqual(grant_env["data"]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
