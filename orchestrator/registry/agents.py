"""Agent registry and discovery for genai-agentic-ops runtime adapters.

Discovers registered adapters, queries capabilities, and validates against
contracts/agent-registry.schema.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from orchestrator.adapters.antigravity import AntigravityAdapter
from orchestrator.adapters.base import AgentAdapter
from orchestrator.adapters.claude_code import ClaudeCodeAdapter
from orchestrator.adapters.codex import CodexAdapter
from orchestrator.adapters.gemini_cli import GeminiCliAdapter


class AgentRegistry:
    """Central registry and capability inspector for agent runtime adapters."""

    def __init__(self, schema_path: str | Path | None = None) -> None:
        if schema_path is None:
            here = Path(__file__).resolve().parent
            repo_root = here.parent.parent
            schema_path = repo_root / "contracts" / "agent-registry.schema.json"

        self.schema_path = Path(schema_path).resolve()
        if not self.schema_path.is_file():
            raise FileNotFoundError(f"Agent registry schema not found: {self.schema_path}")

        with open(self.schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)
        self.validator = Draft7Validator(self.schema)

        self._adapters: dict[str, AgentAdapter] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register standard runtime adapters."""
        self.register(ClaudeCodeAdapter())
        self.register(AntigravityAdapter())
        self.register(GeminiCliAdapter())
        self.register(CodexAdapter())

    def register(self, adapter: AgentAdapter) -> None:
        """Register an adapter instance."""
        self._adapters[adapter.name] = adapter

    def get_adapter(self, name: str) -> AgentAdapter | None:
        """Retrieve an adapter by name."""
        return self._adapters.get(name)

    def to_contract_dict(self) -> dict[str, Any]:
        """Serialize current agent registry into dictionary conforming to schema."""
        agents_dict: dict[str, Any] = {}

        for name, adapter in self._adapters.items():
            detected = adapter.detect()
            bin_path = getattr(adapter, "find_binary", lambda: None)()

            agent_info: dict[str, Any] = {
                "runtime": adapter.runtime,
                "command": adapter.command,
                "enabled": detected,
                "roles": ["planner", "developer", "tester", "reviewer"],
                "maturity": adapter.maturity.value,
                "capabilities": adapter.capabilities(),
            }
            if bin_path:
                agent_info["binary_path"] = bin_path

            agents_dict[name] = agent_info

        return {
            "schema_version": "0.1",
            "agents": agents_dict,
        }

    def validate(self, registry_dict: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
        """Validate serialized registry against agent-registry.schema.json."""
        target = registry_dict if registry_dict is not None else self.to_contract_dict()
        errors: list[str] = []
        for err in self.validator.iter_errors(target):
            loc = ".".join(str(p) for p in err.path) if err.path else "root"
            errors.append(f"{loc}: {err.message}")
        return len(errors) == 0, errors

    def list_agents(self) -> list[dict[str, Any]]:
        """List registered agents with summary information for CLI display."""
        contract = self.to_contract_dict()
        items: list[dict[str, Any]] = []
        for name, info in contract.get("agents", {}).items():
            item = dict(info)
            item["name"] = name
            items.append(item)
        return items

    def inspect_agent(self, name: str) -> dict[str, Any] | None:
        """Return detailed capability report and maturity label for a specific agent."""
        adapter = self.get_adapter(name)
        if not adapter:
            return None

        contract = self.to_contract_dict()
        agent_data = contract.get("agents", {}).get(name)
        if not agent_data:
            return None

        report = dict(agent_data)
        report["name"] = name
        return report
