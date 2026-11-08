"""Tests for Phase 1, 2, and 3 Evolution capabilities.

Verifies:
- Phase 1:
  - Token-enforced coordinator.approve_task when pending approval exists
  - Non-interactive worker protection (AGENTIC_NON_INTERACTIVE=1)
  - .agentic/approvals protected path enforcement
  - Mutating shell command blocking in active_lock_guard across all 4 hosts
- Phase 2:
  - WorkspaceQuarantine automatic out-of-scope file rollback & forensic manifest
  - TelemetryLedger recording and aggregation in .agentic/runs/metrics.jsonl
  - WorkflowEngine.get_parallel_batches disjoint path batching
  - AgentRegistry.resolve_runtime('auto') & cross-model reviewer selection
- Phase 3:
  - MCP Server JSON-RPC 2.0 initialize, tools/list, and tools/call dispatch
  - Live terminal dashboard rendering (`agentic watch --once`)
"""
from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from orchestrator.cli.main import main
from orchestrator.cli.mcp_server import MCPServer, handle_jsonrpc_message
from orchestrator.cli.watch_cmd import render_dashboard
from orchestrator.core.coordinator import OrchestratorCoordinator
from orchestrator.core.runner import TaskRunner
from orchestrator.core.workflow_engine import WorkflowEngine
from orchestrator.governance.protected_paths import is_protected_path
from orchestrator.tests.test_host_conformance import HOSTS, _load_guard_module
from orchestrator.tests.test_runner import MockAdapter

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
VALID_PLAN_FIXTURE = REPO_ROOT / "kit" / "tests" / "fixtures" / "contracts" / "plan.valid.json"


class TestPhase123Evolution(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.coord = OrchestratorCoordinator(self.root)
        self.mock_adapter = MockAdapter()
        self.coord.registry.register(self.mock_adapter)
        self.runner = TaskRunner(self.coord)

        with open(VALID_PLAN_FIXTURE, "r", encoding="utf-8") as f:
            self.plan = json.load(f)

    def tearDown(self) -> None:
        os.environ.pop("AGENTIC_NON_INTERACTIVE", None)
        self.temp_dir.cleanup()

    def test_phase1_approval_token_bypass_blocked_and_non_interactive_guard(self) -> None:
        is_prot, matched = is_protected_path(".agentic/approvals/task-001.json")
        self.assertTrue(is_prot)
        self.assertEqual(matched, ".agentic/approvals")

        p = copy.deepcopy(self.plan)
        p["approval_required"] = True
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]
        t_spec["verification_commands"] = [f'"{sys.executable}" -c "exit(0)"']
        self.coord.submit_plan(p)

        t_id = t_spec["task_id"]
        self.runner.run_task(t_id)

        # 1. Calling approve_task without token when pending approval exists MUST fail
        with self.assertRaises(ValueError) as ctx:
            self.coord.approve_task(t_id, token=None)
        self.assertIn("Approval token is required", str(ctx.exception))

        # 2. Non-interactive worker environment cannot grant or deny approvals
        req = self.coord.approval_manager.get_approval(t_id)
        token = req["token"]
        os.environ["AGENTIC_NON_INTERACTIVE"] = "1"
        try:
            with self.assertRaises(ValueError) as ctx2:
                self.coord.approval_manager.grant_approval(t_id, token)
            self.assertIn("AGENTIC_NON_INTERACTIVE=1", str(ctx2.exception))
        finally:
            os.environ.pop("AGENTIC_NON_INTERACTIVE", None)

        # 3. Interactive human with valid token succeeds
        res = self.coord.approve_task(t_id, token=token, approver="sam")
        self.assertEqual(res["status"], "approved")

    def test_phase1_active_lock_guard_blocks_mutating_shell_commands(self) -> None:
        self.coord.lock_manager.acquire(
            task_id="task-shell-lock",
            workflow_id="wf-shell-lock",
            allowed_paths=["src/"],
        )
        try:
            for host in HOSTS:
                guard_mod = _load_guard_module(host)
                eval_fn = guard_mod.evaluate_tool_call

                # Mutating git command in shell must be denied while lock is active
                shell_payload = {
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "git reset --hard HEAD"},
                    }
                }
                decision, reason = eval_fn(shell_payload, root_dir=self.root)
                self.assertEqual(decision, "deny", f"{host} failed to block mutating shell command")
                self.assertIn("task-shell-lock", reason)

                # Safe read-only shell command outside allowed_paths is allowed
                safe_payload = {
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "git status"},
                    }
                }
                decision_safe, _ = eval_fn(safe_payload, root_dir=self.root)
                self.assertEqual(decision_safe, "allow")
        finally:
            self.coord.lock_manager.release(force=True)

    def test_phase2_quarantine_auto_rollback_and_telemetry(self) -> None:
        # Create an existing baseline file outside worker's scope
        readme_file = self.root / "README.md"
        readme_file.write_text("Original clean content\n", encoding="utf-8")

        p = copy.deepcopy(self.plan)
        p["approval_required"] = False
        t_spec = p["tasks"][0]
        t_spec["allowed_paths"] = ["src/"]

        def rogue_worker(task: dict, handoff: dict) -> None:
            # Worker modifies README.md (out of scope) and creates rogue_file.txt
            readme_file.write_text("CORRUPTED BY WORKER\n", encoding="utf-8")
            (self.root / "rogue_file.txt").write_text("unwanted\n", encoding="utf-8")

        self.mock_adapter.side_effect = rogue_worker
        self.coord.submit_plan(p)

        t_id = t_spec["task_id"]
        res = self.runner.run_task(t_id)

        # Task must be blocked due to out-of-scope modification
        self.assertFalse(res["diff"]["in_scope"])
        self.assertFalse(res["verification"]["verified"])

        # Quarantine must have automatically restored README.md and deleted rogue_file.txt
        self.assertEqual(readme_file.read_text(encoding="utf-8"), "Original clean content\n")
        self.assertFalse((self.root / "rogue_file.txt").exists())

        # Telemetry must have recorded the run and quarantined count
        summary = self.coord.telemetry.summarize()
        self.assertEqual(summary["total_runs"], 1)
        entries = self.coord.telemetry.list_entries()
        self.assertEqual(entries[0]["quarantined_files_count"], 2)

    def test_phase2_parallel_batches_and_auto_runtime_routing(self) -> None:
        tasks = [
            {"task_id": "task-1", "allowed_paths": ["src/frontend/"]},
            {"task_id": "task-2", "allowed_paths": ["src/backend/"]},
            {"task_id": "task-3", "allowed_paths": ["src/frontend/components/"]},
        ]
        batches = WorkflowEngine.get_parallel_batches(tasks)
        # task-1 and task-2 are disjoint (batch 0); task-3 overlaps task-1 (batch 1)
        self.assertEqual(len(batches), 2)
        self.assertEqual([t["task_id"] for t in batches[0]], ["task-1", "task-2"])
        self.assertEqual([t["task_id"] for t in batches[1]], ["task-3"])

        # Auto runtime routing & cross-model reviewer selection
        dev_adapter = self.coord.registry.resolve_runtime("auto", role="developer")
        self.assertIsNotNone(dev_adapter)
        rev_adapter = self.coord.registry.resolve_runtime(
            "auto", role="reviewer", exclude_runtime=dev_adapter.name
        )
        self.assertIsNotNone(rev_adapter)

    def test_phase3_mcp_server_and_watch_dashboard(self) -> None:
        # 1. MCP initialize
        init_resp = handle_jsonrpc_message(
            self.coord, {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
        )
        self.assertIsNotNone(init_resp)
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "genai-agentic-ops")

        # 2. MCP tools/list
        list_resp = handle_jsonrpc_message(
            self.coord, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
        tool_names = [t["name"] for t in list_resp["result"]["tools"]]
        self.assertIn("agentic_status", tool_names)
        self.assertIn("agentic_task_run", tool_names)

        # 3. MCP tools/call agentic_doctor
        call_resp = handle_jsonrpc_message(
            self.coord,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "agentic_doctor", "arguments": {}},
            },
        )
        self.assertFalse(call_resp["result"]["isError"])
        doc_payload = json.loads(call_resp["result"]["content"][0]["text"])
        self.assertTrue(doc_payload["ok"])

        # 4. Watch dashboard CLI (--once)
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--root", str(self.root), "watch", "--once"])
        dash_out = buf.getvalue()
        self.assertIn("genai-agentic-ops Live Dashboard", dash_out)
        self.assertIn("[LOCK]", dash_out)
        self.assertIn("[TELEMETRY]", dash_out)

    def test_concurrent_telemetry_recording(self) -> None:
        """Verify parallel writes to metrics.jsonl do not interleave or corrupt JSON lines."""
        ledger = self.coord.telemetry
        num_threads = 20
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                ledger.record_run_metrics(
                    run_id=f"run-concurrent-{idx}",
                    task_id=f"task-concurrent-{idx}",
                    workflow_id="wf-concurrent",
                    runtime="antigravity",
                    role="developer",
                    duration_ms=100 + idx,
                    prompt_text=f"Prompt for worker {idx}",
                    stdout_text=f"Output from worker {idx}",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        entries = ledger.list_entries(workflow_id="wf-concurrent")
        self.assertEqual(len(entries), num_threads)
        run_ids = {e["run_id"] for e in entries}
        expected_run_ids = {f"run-concurrent-{i}" for i in range(num_threads)}
        self.assertEqual(run_ids, expected_run_ids)

    def test_mcp_server_multiline_and_streaming(self) -> None:
        """Verify MCPServer.run_stdio handles multi-line JSON and Content-Length framed input."""
        server = MCPServer(self.coord)

        # 1. Multi-line pretty-printed JSON-RPC
        multiline_req = (
            "{\n"
            '  "jsonrpc": "2.0",\n'
            '  "id": "req-multi",\n'
            '  "method": "ping"\n'
            "}\n"
        )
        inp = io.StringIO(multiline_req)
        out = io.StringIO()
        server.run_stdio(in_stream=inp, out_stream=out)
        out.seek(0)
        resp = json.loads(out.read().strip())
        self.assertEqual(resp["id"], "req-multi")
        self.assertEqual(resp["jsonrpc"], "2.0")

        # 2. Content-Length framed JSON-RPC
        payload = json.dumps({"jsonrpc": "2.0", "id": "req-cl", "method": "initialize"})
        cl_req = f"Content-Length: {len(payload)}\r\n\r\n{payload}"
        inp_cl = io.StringIO(cl_req)
        out_cl = io.StringIO()
        server.run_stdio(in_stream=inp_cl, out_stream=out_cl)
        out_cl.seek(0)
        resp_cl = json.loads(out_cl.read().strip())
        self.assertEqual(resp_cl["id"], "req-cl")
        self.assertEqual(resp_cl["result"]["serverInfo"]["name"], "genai-agentic-ops")


if __name__ == "__main__":
    unittest.main()
