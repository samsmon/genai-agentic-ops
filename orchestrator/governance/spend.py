"""Spend accounting over telemetry ledger entries.

Shared by the budget guard and the telemetry summary so both read spend the
same way. A run is charged with provider-reported tokens (input plus output)
when the ledger entry carries them, and with the byte-based estimate
otherwise. The two sources are always reported separately; a total that adds
them (``charged_tokens``) is only used to compare against a token limit.
"""
from __future__ import annotations

from typing import Any

PROVIDER = "provider"
ESTIMATED = "estimated"


def charged_tokens(entry: dict[str, Any]) -> tuple[int, str]:
    """Return (tokens charged for this run, token source label)."""
    usage = entry.get("provider_usage")
    if entry.get("token_source") == PROVIDER and isinstance(usage, dict):
        total = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
        return total, PROVIDER
    return int(entry.get("estimated_tokens") or 0), ESTIMATED


def run_cost_usd(entry: dict[str, Any]) -> float | None:
    """Provider-reported cost of a run, or None when none was reported."""
    usage = entry.get("provider_usage")
    if isinstance(usage, dict) and isinstance(usage.get("cost_usd"), (int, float)):
        return float(usage["cost_usd"])
    return None


def total_spend(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum spend over entries, keeping provider and estimated figures apart."""
    out: dict[str, Any] = {
        "charged_tokens": 0,
        "provider_tokens": 0,
        "estimated_tokens": 0,
        "provider_runs": 0,
        "estimated_runs": 0,
        "provider_usd": 0.0,
        "usd_unmeasured_runs": 0,
    }
    for entry in entries:
        tokens, source = charged_tokens(entry)
        out["charged_tokens"] += tokens
        out[f"{source}_tokens"] += tokens
        out[f"{source}_runs"] += 1
        cost = run_cost_usd(entry)
        if cost is None:
            out["usd_unmeasured_runs"] += 1
        else:
            out["provider_usd"] += cost
    out["provider_usd"] = round(out["provider_usd"], 6)
    return out
