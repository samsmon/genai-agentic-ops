"""Tests for provider-reported token usage in the telemetry ledger."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.governance.metrics import TelemetryLedger, extract_provider_usage


class TestExtractProviderUsage(unittest.TestCase):
    def test_anthropic_style_result(self) -> None:
        raw = {
            "model": "example-model",
            "total_cost_usd": 0.0125,
            "usage": {
                "input_tokens": 1200,
                "output_tokens": 300,
                "cache_read_input_tokens": 5000,
                "cache_creation_input_tokens": 800,
            },
        }
        self.assertEqual(
            extract_provider_usage(raw),
            {
                "input_tokens": 1200,
                "output_tokens": 300,
                "cache_read_input_tokens": 5000,
                "cache_creation_input_tokens": 800,
                "cost_usd": 0.0125,
                "model": "example-model",
            },
        )

    def test_openai_style_keys(self) -> None:
        usage = extract_provider_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 4}})
        self.assertEqual(usage["input_tokens"], 10)
        self.assertEqual(usage["output_tokens"], 4)
        self.assertIsNone(usage["cache_read_input_tokens"])
        self.assertNotIn("cost_usd", usage)

    def test_unknown_shapes_return_none(self) -> None:
        for raw in (None, "plain text", [], {}, {"usage": "n/a"}, {"usage": {"tokens": 5}},
                    {"usage": {"input_tokens": True}}, {"usage": {"input_tokens": -1}}):
            self.assertIsNone(extract_provider_usage(raw), raw)


class TestLedgerTokenSource(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger = TelemetryLedger(Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _record(self, run_id: str, usage: dict | None) -> dict:
        return self.ledger.record_run_metrics(
            run_id=run_id, task_id="t", workflow_id="wf", runtime="mock", role="implementer",
            duration_ms=10, prompt_text="abcd" * 10, provider_usage=usage,
        )

    def test_entries_are_labelled_by_token_source(self) -> None:
        estimated = self._record("run-a", None)
        provider = self._record("run-b", {"input_tokens": 100, "output_tokens": 20})

        self.assertEqual(estimated["token_source"], "estimated")
        self.assertIsNone(estimated["provider_usage"])
        self.assertEqual(provider["token_source"], "provider")
        # The estimate is still recorded next to the provider figures.
        self.assertEqual(provider["estimated_tokens"], 10)

        summary = self.ledger.summarize()
        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["runs_with_provider_usage"], 1)
        self.assertEqual(summary["total_provider_input_tokens"], 100)
        self.assertEqual(summary["total_provider_output_tokens"], 20)


if __name__ == "__main__":
    unittest.main()
