"""Tests for orchestrator/governance/approval.py and CLI approval commands.

Verifies:
- Cryptographic one-time token issuance
- Token persistence in .agentic/approvals/<task_id>.json
- Validation of valid token and transition to approved
- Rejection of missing/empty token
- Rejection of forged/invalid token
- Single-use consumption preventing replay
- Denial with reason
- CLI commands: agentic approval show, grant, deny
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from orchestrator.cli.main import main
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.governance.approval import ApprovalManager

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
VALID_PLAN_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.valid.json"


class TestApproval(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)
        self.approval_mgr = self.coord.approval_manager

        with open(VALID_PLAN_FIXTURE, "r", encoding="utf-8") as f:
            self.plan = json.load(f)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_request_and_grant_approval(self) -> None:
        task_id = "task-001"
        req = self.approval_mgr.request_approval(task_id, context={"test": True})
        self.assertEqual(req["task_id"], task_id)
        self.assertEqual(req["status"], "pending")
        token = req["token"]
        self.assertTrue(len(token) > 20)
        self.assertTrue(self.approval_mgr.has_pending_approval(task_id))

        # Check approval file exists on disk
        appr_file = self.approval_mgr._approval_file(task_id)
        self.assertTrue(appr_file.is_file())

        # Grant approval with valid token
        res = self.approval_mgr.grant_approval(task_id, token, approver="alice")
        self.assertEqual(res["status"], "granted")
        self.assertEqual(res["granted_by"], "alice")
        self.assertTrue(res["consumed"])
        self.assertIsNone(res["token"])
        self.assertFalse(self.approval_mgr.has_pending_approval(task_id))

    def test_rejection_of_missing_or_forged_token(self) -> None:
        task_id = "task-002"
        req = self.approval_mgr.request_approval(task_id)
        real_token = req["token"]

        # Missing token
        with self.assertRaises(ValueError) as ctx:
            self.approval_mgr.grant_approval(task_id, "")
        self.assertIn("required", str(ctx.exception))

        # Forged / incorrect token
        with self.assertRaises(ValueError) as ctx:
            self.approval_mgr.grant_approval(task_id, "forged-token-abc-123")
        self.assertIn("Invalid approval token", str(ctx.exception))

        # Ensure task is still pending after rejected attempt
        self.assertTrue(self.approval_mgr.has_pending_approval(task_id))

        # Now grant with legitimate token
        res = self.approval_mgr.grant_approval(task_id, real_token)
        self.assertEqual(res["status"], "granted")

    def test_token_cannot_be_reused(self) -> None:
        task_id = "task-003"
        req = self.approval_mgr.request_approval(task_id)
        token = req["token"]

        # First grant succeeds
        self.approval_mgr.grant_approval(task_id, token)

        # Second grant with same token must fail
        with self.assertRaises(ValueError) as ctx:
            self.approval_mgr.grant_approval(task_id, token)
        self.assertIn("already 'granted'", str(ctx.exception))

    def test_deny_approval(self) -> None:
        task_id = "task-004"
        req = self.approval_mgr.request_approval(task_id)
        token = req["token"]

        res = self.approval_mgr.deny_approval(task_id, token, reason="Unsafe changes")
        self.assertEqual(res["status"], "denied")
        self.assertEqual(res["reason"], "Unsafe changes")
        self.assertTrue(res["consumed"])

    def test_cli_approval_show_and_grant(self) -> None:
        from orchestrator.core.state_machine import ActorRole, TaskState

        self.coord.submit_plan(self.plan)
        t_id = self.plan["tasks"][0]["task_id"]

        # Advance task to VERIFIED so it is ready for approval
        self.coord.task_manager.update_task_status(t_id, TaskState.READY, ActorRole.ORCHESTRATOR)
        self.coord.task_manager.update_task_status(t_id, TaskState.RUNNING, ActorRole.ORCHESTRATOR)
        self.coord.task_manager.update_task_status(t_id, TaskState.COMPLETED, ActorRole.WORKER)
        self.coord.task_manager.update_task_status(t_id, TaskState.VERIFIED, ActorRole.GOVERNANCE)

        req = self.coord.approval_manager.request_approval(t_id, context={"diff": "small"})
        token = req["token"]

        # 1. CLI approval show
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                main(["--root", str(self.root), "approval", "show", t_id])
            except SystemExit:
                pass
        show_env = json.loads(buf.getvalue())
        self.assertTrue(show_env["ok"])
        self.assertEqual(show_env["data"]["approval"]["status"], "pending")

        # 2. CLI approval grant with wrong token fails
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                main(["--root", str(self.root), "approval", "grant", t_id, "--token", "wrong-token"])
            except SystemExit:
                pass
        err_env = json.loads(buf.getvalue())
        self.assertFalse(err_env["ok"])
        self.assertEqual(err_env["error"]["code"], "APPROVAL_INVALID")

        # 3. CLI approval grant with correct token succeeds
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                main(["--root", str(self.root), "approval", "grant", t_id, "--token", token, "--approver", "sam"])
            except SystemExit:
                pass
        grant_env = json.loads(buf.getvalue())
        self.assertTrue(grant_env["ok"])
        self.assertEqual(grant_env["data"]["status"], "approved")


if __name__ == "__main__":
    unittest.main()
