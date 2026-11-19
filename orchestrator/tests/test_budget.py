"""Tests for the budget guard (orchestrator/governance/budget.py).

Verifies:
- A reached limit blocks the next task, leaves it READY and logs budget_exceeded
- A zero budget blocks the first task
- Workflow spend accumulates across tasks and runs
- Missing provider usage is charged as a labelled estimate, never mixed
- Without a configured budget nothing is checked, logged or added
- Human override lifts the block and is refused for non-interactive workers
- Telemetry makes cost per accepted change computable
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from orchestrator.adapters.base import ExecutionResult
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import TaskRunner
from orchestrator.governance.budget import BudgetExceededError, validate_budget_config
from orchestrator.tests.test_runner import MockAdapter, VALID_PLAN_FIXTURE


class UsageAdapter(MockAdapter):
    """Mock adapter whose result carries a configurable raw usage object."""

    def __init__(self) -> None:
        super().__init__()
        self.raw_output: Any = None

    def execute(self, task, handoff, *, run_handle=None, timeout_seconds=None):
        res = super().execute(task, handoff, run_handle=run_handle, timeout_seconds=timeout_seconds)
        return ExecutionResult(
            exit_code=res.exit_code, status=res.status, stdout=res.stdout, stderr=res.stderr,
            session_id=res.session_id, duration_seconds=0.05, raw_output=self.raw_output,
        )


def usage(tokens_in: int, tokens_out: int, cost: float | None = None) -> dict[str, Any]:
    raw: dict[str, Any] = {"usage": {"input_tokens": tokens_in, "output_tokens": tokens_out}}
    if cost is not None:
        raw["total_cost_usd"] = cost
    return raw


class TestBudgetGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)
        self.adapter = UsageAdapter()
        self.coord.registry.register(self.adapter)
        self.runner = TaskRunner(self.coord)
        with open(VALID_PLAN_FIXTURE, "r", encoding="utf-8") as f:
            plan = json.load(f)
        plan["approval_required"] = False
        tmpl = plan["tasks"][0]
        tmpl.update(allowed_paths=["src/"], verification_commands=[], timeout_seconds=30)
        plan["tasks"] = []
        for i in (1, 2, 3):
            t = copy.deepcopy(tmpl)
            t.update(task_id=f"task-00{i}", title=f"Task {i}",
                     depends_on=[f"task-00{i - 1}"] if i > 1 else [])
            plan["tasks"].append(t)
        self.wf = plan["workflow_id"]
        self.coord.submit_plan(plan)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def set_budget(self, **budget: Any) -> None:
        agentic = self.root / ".agentic"
        agentic.mkdir(exist_ok=True)
        (agentic / "config.json").write_text(json.dumps({"budget": budget}), encoding="utf-8")

    def events(self, name: str) -> list[dict[str, Any]]:
        return self.coord.audit_logger.get_events(event_type=name)

    def run_and_approve(self, task_id: str) -> None:
        self.runner.run_task(task_id)
        self.coord.approve_task(task_id)

    def test_exhausted_budget_blocks_next_task(self) -> None:
        self.set_budget(max_workflow_tokens=1000)
        self.adapter.raw_output = usage(900, 300)  # 1200 tokens: overshoots the cap
        self.run_and_approve("task-001")
        self.assertEqual(self.events("budget_exceeded")[0]["details"]["decision"], "overrun_recorded")
        with self.assertRaises(BudgetExceededError) as ctx:
            self.runner.run_task("task-002")
        self.assertEqual(ctx.exception.decision["scope"], "workflow")
        self.assertEqual(ctx.exception.decision["spent"], 1200)
        self.assertEqual(self.coord.task_manager.get_task("task-002")["status"], "ready")
        blocked = [e for e in self.events("budget_exceeded")
                   if e["details"]["decision"] == "blocked_admission"]
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0]["details"]["token_sources"]["provider_tokens"], 1200)
        self.assertEqual(len(self.adapter.executed), 1)

    def test_zero_budget_blocks_first_task(self) -> None:
        self.set_budget(max_workflow_tokens=0)
        with self.assertRaises(BudgetExceededError):
            self.runner.run_task("task-001")
        self.assertEqual(self.adapter.executed, [])
        self.assertEqual(self.coord.telemetry.list_entries(), [])
        self.assertEqual(self.coord.task_manager.get_task("task-001")["status"], "ready")

    def test_workflow_spend_accumulates_across_tasks(self) -> None:
        self.set_budget(max_workflow_tokens=800)
        self.adapter.raw_output = usage(300, 100)  # 400 per task
        self.run_and_approve("task-001")
        self.run_and_approve("task-002")
        self.assertEqual(self.coord.budget.status(self.wf)["spent"]["provider_tokens"], 800)
        with self.assertRaises(BudgetExceededError) as ctx:
            self.runner.run_task("task-003")
        self.assertEqual(ctx.exception.decision["spent"], 800)

    def test_run_workflow_reports_budget_block(self) -> None:
        self.set_budget(max_workflow_tokens=0)
        res = self.runner.run_workflow(self.wf)
        self.assertEqual(res["tasks_executed"], 0)
        self.assertFalse(res["success"])
        self.assertEqual(res["budget_blocked"]["decision"], "blocked_admission")

    def test_per_run_limit_scopes_to_one_workflow_call(self) -> None:
        self.set_budget(max_run_tokens=300)
        self.adapter.raw_output = usage(200, 200)  # 400, overshoots the run cap
        res = self.runner.run_workflow(self.wf)
        self.assertEqual(res["tasks_executed"], 1)
        scopes = {e["details"]["scope"] for e in self.events("budget_exceeded")}
        self.assertEqual(scopes, {"run"})
        self.coord.approve_task("task-001")
        # a new call has an empty run scope; the history-based estimate (400)
        # still exceeds the 300 cap, so admission refuses before any spend
        res = self.runner.run_workflow(self.wf)
        self.assertEqual(res["tasks_executed"], 0)
        self.assertEqual(res["budget_blocked"]["estimate_tokens"], 400)
        self.assertEqual(res["budget_blocked"]["scope"], "run")

    def test_missing_provider_usage_is_labelled_estimate(self) -> None:
        self.set_budget(max_workflow_tokens=10_000)
        self.adapter.raw_output = None
        self.runner.run_task("task-001")
        entry = self.coord.telemetry.list_entries()[0]
        self.assertEqual(entry["token_source"], "estimated")
        spend = self.coord.budget.status(self.wf)["spent"]
        self.assertEqual(spend["estimated_tokens"], entry["estimated_tokens"])
        self.assertEqual(spend["provider_tokens"], 0)
        self.assertEqual(spend["estimated_runs"], 1)

    def test_estimate_and_provider_spend_stay_separate(self) -> None:
        self.set_budget(max_workflow_tokens=100_000)
        self.adapter.raw_output = None
        self.run_and_approve("task-001")
        self.adapter.raw_output = usage(500, 100, cost=0.02)
        self.runner.run_task("task-002")
        spend = self.coord.budget.status(self.wf)["spent"]
        self.assertEqual(spend["provider_tokens"], 600)
        self.assertGreater(spend["estimated_tokens"], 0)
        self.assertEqual(spend["provider_usd"], 0.02)
        self.assertEqual(spend["usd_unmeasured_runs"], 1)

    def test_estimate_only_block_policy(self) -> None:
        self.set_budget(max_workflow_tokens=100_000, on_estimate_only="block")
        self.run_and_approve("task-001")
        with self.assertRaises(BudgetExceededError) as ctx:
            self.runner.run_task("task-002")
        self.assertEqual(ctx.exception.decision["reason"], "estimate_only_spend")

    def test_task_cap_is_reserved_at_admission(self) -> None:
        self.set_budget(max_workflow_tokens=500)
        task = self.coord.task_manager.get_task("task-001")
        task["max_task_tokens"] = 600
        self.coord.storage.save_task(task)
        with self.assertRaises(BudgetExceededError) as ctx:
            self.runner.run_task("task-001")
        self.assertEqual(ctx.exception.decision["estimate_tokens"], 600)

    def test_usd_limit_uses_provider_cost(self) -> None:
        self.set_budget(max_workflow_usd=0.05)
        self.adapter.raw_output = usage(10, 10, cost=0.06)
        self.run_and_approve("task-001")
        with self.assertRaises(BudgetExceededError) as ctx:
            self.runner.run_task("task-002")
        self.assertEqual(ctx.exception.decision["unit"], "usd")

    def test_no_budget_configured_changes_nothing(self) -> None:
        self.adapter.raw_output = usage(10 ** 6, 10 ** 6)
        for tid in ("task-001", "task-002", "task-003"):
            self.run_and_approve(tid)
        names = {e["event"] for e in self.coord.audit_logger.get_events()}
        self.assertFalse({"budget_exceeded", "budget_warning", "budget_override"} & names)
        self.assertEqual(len(self.coord.telemetry.list_entries()), 3)
        self.assertFalse((self.root / ".agentic" / "budget").exists())
        res = self.runner.run_workflow(self.wf)
        self.assertNotIn("budget_blocked", res)
        self.assertEqual(self.coord.budget.status(self.wf), {"enabled": False})

    def test_override_lifts_block_and_is_audited(self) -> None:
        self.set_budget(max_workflow_tokens=0)
        with self.assertRaises(BudgetExceededError):
            self.runner.run_task("task-001")
        with mock.patch.dict(os.environ, {"AGENTIC_NON_INTERACTIVE": "1"}):
            with self.assertRaises(ValueError):
                self.coord.budget.grant_override(self.wf, extra_tokens=5000)
        self.coord.budget.grant_override(self.wf, extra_tokens=5000, reason="approved by owner")
        self.adapter.raw_output = usage(10, 10)
        self.runner.run_task("task-001")
        self.assertEqual(self.events("budget_override")[0]["details"]["reason"], "approved by owner")

    def test_invalid_config_fails_closed(self) -> None:
        self.set_budget(max_workflow_tokens=-1)
        with self.assertRaises(ValueError):
            self.runner.run_task("task-001")
        self.assertEqual(self.adapter.executed, [])
        with self.assertRaises(ValueError):
            validate_budget_config({"bogus": 1})

    def test_cost_per_accepted_change_is_computable(self) -> None:
        self.set_budget(max_workflow_tokens=100_000)
        self.adapter.raw_output = usage(300, 100, cost=0.01)
        self.run_and_approve("task-001")
        self.adapter.raw_output = usage(200, 100, cost=0.01)
        self.runner.run_task("task-002")  # verified, not approved: spend without acceptance
        summary = self.coord.telemetry_summary(self.wf)
        self.assertEqual(summary["accepted_changes"], 1)
        per = summary["cost_per_accepted_change"]
        self.assertEqual(per["provider_tokens"], 700)
        self.assertEqual(per["provider_usd"], 0.02)
        self.assertEqual(per["estimated_tokens"], 0)
        outcomes = {r["task_id"]: r for r in summary["runs"]}
        self.assertTrue(outcomes["task-001"]["approved"] and outcomes["task-001"]["verified"])
        self.assertFalse(outcomes["task-002"]["approved"])
        self.assertTrue(outcomes["task-002"]["verified"])
        self.assertEqual(outcomes["task-001"]["token_source"], "provider")

    def test_cost_per_accepted_change_null_without_acceptance(self) -> None:
        self.runner.run_task("task-001")
        summary = self.coord.telemetry_summary(self.wf)
        self.assertEqual(summary["accepted_changes"], 0)
        self.assertIsNone(summary["cost_per_accepted_change"])


if __name__ == "__main__":
    unittest.main()
