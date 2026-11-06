"""Tests for AgentRegistry, schema validation, and CLI commands."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from orchestrator.cli.main import main
from orchestrator.registry.agents import AgentRegistry


class TestAgentRegistry(unittest.TestCase):
    """Test agent registry discovery, validation against schema, and capability reporting."""

    def setUp(self) -> None:
        self.registry = AgentRegistry()

    def test_default_adapters_registered(self) -> None:
        self.assertIsNotNone(self.registry.get_adapter("claude-code"))
        self.assertIsNotNone(self.registry.get_adapter("antigravity"))
        self.assertIsNotNone(self.registry.get_adapter("gemini-cli"))
        self.assertIsNotNone(self.registry.get_adapter("codex"))
        self.assertIsNone(self.registry.get_adapter("unknown-agent"))

    def test_contract_dict_validates_against_schema(self) -> None:
        contract = self.registry.to_contract_dict()
        self.assertEqual(contract["schema_version"], "0.1")
        self.assertIn("agents", contract)

        is_valid, errors = self.registry.validate(contract)
        self.assertTrue(is_valid, f"Validation errors: {errors}")
        self.assertEqual(len(errors), 0)

    def test_invalid_registry_fails_validation(self) -> None:
        bad_contract = {
            "schema_version": "0.1",
            "agents": {
                "invalid-agent": {
                    "runtime": "invalid-runtime-not-in-enum",
                    "command": "bad",
                    "enabled": True,
                    "roles": ["developer"],
                    "maturity": "unverified-not-in-enum",
                }
            },
        }
        is_valid, errors = self.registry.validate(bad_contract)
        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)

    def test_inspect_agent(self) -> None:
        claude = self.registry.inspect_agent("claude-code")
        self.assertIsNotNone(claude)
        assert claude is not None
        self.assertEqual(claude["runtime"], "claude-code")
        self.assertEqual(claude["command"], "claude")
        self.assertIn("maturity", claude)
        self.assertIn("capabilities", claude)

        missing = self.registry.inspect_agent("missing-agent")
        self.assertIsNone(missing)

    def test_list_agents(self) -> None:
        agents = self.registry.list_agents()
        self.assertGreaterEqual(len(agents), 4)
        names = [a["name"] for a in agents]
        self.assertIn("claude-code", names)
        self.assertIn("antigravity", names)


class TestAgentCLI(unittest.TestCase):
    """Test CLI commands: agentic agent list and agentic agent inspect."""

    def test_cli_agent_list(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["agent", "list"])

        self.assertEqual(cm.exception.code, 0)
        output = json.loads(buf.getvalue())
        self.assertTrue(output["ok"])
        self.assertIn("agents", output["data"])
        self.assertGreaterEqual(output["data"]["count"], 4)

    def test_cli_agent_inspect_success(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["agent", "inspect", "claude-code"])

        self.assertEqual(cm.exception.code, 0)
        output = json.loads(buf.getvalue())
        self.assertTrue(output["ok"])
        self.assertEqual(output["data"]["runtime"], "claude-code")
        self.assertEqual(output["data"]["name"], "claude-code")

    def test_cli_agent_inspect_not_found(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                main(["agent", "inspect", "does-not-exist"])

        self.assertEqual(cm.exception.code, 1)
        output = json.loads(buf.getvalue())
        self.assertFalse(output["ok"])
        self.assertEqual(output["error"]["code"], "AGENT_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
