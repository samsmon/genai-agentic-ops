"""Budget guard: admission check before a task, accounting after it.

Limits are read from the ``budget`` object in ``.agentic/config.json``. With no
``budget`` configured, every method here is a no-op and nothing is logged.

Limitation, stated plainly: provider usage is only known after a run ends, so
this is not a hard mid-run cap. The guard (1) refuses to start a task when the
spend so far already reaches a limit or the task's estimated cost would cross
it, and (2) charges the real spend after the run. A single task can therefore
overshoot a limit by what it spends in one run; the overshoot is recorded as
an ``overrun_recorded`` audit event and blocks the next admission. The
per-task timeout remains the only mid-run stop.
"""
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path
from typing import Any

from orchestrator.governance.approval import ensure_interactive_environment
from orchestrator.governance.audit import AuditLogger
from orchestrator.governance.metrics import TelemetryLedger
from orchestrator.governance.spend import ESTIMATED, charged_tokens, run_cost_usd, total_spend

_TOKEN_LIMITS = ("max_task_tokens", "max_workflow_tokens", "max_run_tokens")
_USD_LIMITS = ("max_workflow_usd", "max_run_usd")
_OTHER_KEYS = ("warn_ratio", "on_estimate_only")


class BudgetExceededError(ValueError):
    """Raised at admission when a budget forbids starting the task."""

    def __init__(self, decision: dict[str, Any]) -> None:
        super().__init__(decision["message"])
        self.decision = decision


def validate_budget_config(raw: Any) -> dict[str, Any] | None:
    """Return a validated budget config, None when disabled, ValueError when invalid."""
    if raw is None or raw == {}:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Invalid budget config: 'budget' must be an object")
    unknown = set(raw) - set(_TOKEN_LIMITS) - set(_USD_LIMITS) - set(_OTHER_KEYS)
    if unknown:
        raise ValueError(f"Invalid budget config: unknown keys {sorted(unknown)}")
    for key in _TOKEN_LIMITS:
        val = raw.get(key)
        if val is not None and (not isinstance(val, int) or isinstance(val, bool) or val < 0):
            raise ValueError(f"Invalid budget config: '{key}' must be an integer >= 0")
    for key in _USD_LIMITS:
        val = raw.get(key)
        if val is not None and (
            not isinstance(val, (int, float)) or isinstance(val, bool) or val < 0
        ):
            raise ValueError(f"Invalid budget config: '{key}' must be a number >= 0")
    ratio = raw.get("warn_ratio", 0.8)
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0 < ratio <= 1:
        raise ValueError("Invalid budget config: 'warn_ratio' must be in (0, 1]")
    if raw.get("on_estimate_only", "charge") not in ("charge", "block"):
        raise ValueError("Invalid budget config: 'on_estimate_only' must be 'charge' or 'block'")
    cfg = dict(raw)
    cfg.setdefault("warn_ratio", 0.8)
    cfg.setdefault("on_estimate_only", "charge")
    return cfg


class BudgetGuard:
    """Enforces configured token and USD limits for tasks, workflows and runs."""

    def __init__(self, root_dir: str | Path, ledger: TelemetryLedger, audit: AuditLogger) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.ledger = ledger
        self.audit = audit
        self.config_path = self.root_dir / ".agentic" / "config.json"
        self.overrides_path = self.root_dir / ".agentic" / "budget" / "overrides.json"

    # -- configuration -----------------------------------------------------
    def load_config(self) -> dict[str, Any] | None:
        if not self.config_path.is_file():
            return None
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return validate_budget_config(data.get("budget"))

    def load_overrides(self) -> dict[str, Any]:
        try:
            data = json.loads(self.overrides_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _limits(self, cfg: dict[str, Any], workflow_id: str, scope: str) -> dict[str, float | None]:
        extra = self.load_overrides().get(workflow_id, {})
        out: dict[str, float | None] = {}
        for unit, extra_key in (("tokens", "extra_tokens"), ("usd", "extra_usd")):
            base = cfg.get(f"max_{scope}_{unit}")
            out[unit] = None if base is None else base + extra.get(extra_key, 0)
        return out

    # -- estimate ----------------------------------------------------------
    def estimate(self, task: dict[str, Any], cfg: dict[str, Any]) -> int:
        """Tokens reserved at admission: the task cap, else a median of past runs of the role."""
        cap = task.get("max_task_tokens", cfg.get("max_task_tokens"))
        if cap is not None:
            return int(cap)
        past = [
            charged_tokens(e)[0]
            for e in self.ledger.list_entries()
            if e.get("role") == task.get("role")
        ]
        return int(statistics.median(past)) if past else 0

    # -- admission ---------------------------------------------------------
    def admit(self, task: dict[str, Any], *, run_ids: list[str] | None = None) -> dict[str, Any] | None:
        """Raise BudgetExceededError if the task must not start; else return the decision."""
        cfg = self.load_config()
        if cfg is None:
            return None
        wf_id = task["workflow_id"]
        entries = self.ledger.list_entries(workflow_id=wf_id)
        est = self.estimate(task, cfg)
        scopes = {"workflow": entries}
        if run_ids is not None:
            scopes["run"] = [e for e in entries if e.get("run_id") in run_ids]

        if cfg["on_estimate_only"] == "block":
            n_est = sum(1 for e in entries if charged_tokens(e)[1] == ESTIMATED)
            if n_est:
                self._block(task, cfg, "workflow", "tokens", None, n_est, 0, entries,
                            "estimate_only_spend")
        for scope, scoped in scopes.items():
            spent = total_spend(scoped)
            limits = self._limits(cfg, wf_id, scope)
            for unit, key, reserve in (("tokens", "charged_tokens", est), ("usd", "provider_usd", 0)):
                limit = limits[unit]
                if limit is None:
                    continue
                if spent[key] >= limit or spent[key] + reserve > limit:
                    self._block(task, cfg, scope, unit, limit, spent[key], reserve, scoped,
                                "limit_reached")
                if limit > 0 and spent[key] >= cfg["warn_ratio"] * limit:
                    self.audit.log_event(
                        "budget_warning", task_id=task["task_id"], workflow_id=wf_id,
                        details={"scope": scope, "unit": unit, "limit": limit, "spent": spent[key]},
                    )
        return {"allowed": True, "estimate_tokens": est}

    def _block(self, task: dict, cfg: dict, scope: str, unit: str, limit: float | None,
               spent: float, estimate: int, entries: list, reason: str) -> None:
        breakdown = total_spend(entries)
        decision = {
            "allowed": False, "scope": scope, "unit": unit, "limit": limit, "spent": spent,
            "estimate_tokens": estimate, "reason": reason, "decision": "blocked_admission",
            "token_sources": {k: breakdown[k] for k in
                              ("provider_tokens", "estimated_tokens", "provider_runs",
                               "estimated_runs", "provider_usd", "usd_unmeasured_runs")},
            "message": (f"Budget {scope} {unit} {reason}: spent {spent} of {limit} "
                        f"(estimate {estimate}); task '{task['task_id']}' not started"),
        }
        self.audit.log_event(
            "budget_exceeded", task_id=task["task_id"], workflow_id=task["workflow_id"],
            details={k: v for k, v in decision.items() if k != "message"},
        )
        raise BudgetExceededError(decision)

    # -- accounting --------------------------------------------------------
    def account(self, task: dict[str, Any], run_id: str, *, run_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Charge a finished run (already in the ledger); record any overshoot."""
        cfg = self.load_config()
        if cfg is None:
            return []
        wf_id = task["workflow_id"]
        entries = self.ledger.list_entries(workflow_id=wf_id)
        mine = next((e for e in entries if e.get("run_id") == run_id), None)
        if mine is None:
            return []
        tokens, source = charged_tokens(mine)
        found: list[dict[str, Any]] = []

        def overrun(scope: str, unit: str, limit: float, spent: float) -> None:
            details = {"scope": scope, "unit": unit, "limit": limit, "spent": spent,
                       "token_source": source, "decision": "overrun_recorded"}
            found.append(details)
            self.audit.log_event("budget_exceeded", task_id=task["task_id"], workflow_id=wf_id,
                                 run_id=run_id, details=details)

        cap = task.get("max_task_tokens", cfg.get("max_task_tokens"))
        if cap is not None and tokens > cap:
            overrun("task", "tokens", cap, tokens)
        scopes = {"workflow": entries}
        if run_ids is not None:
            scopes["run"] = [e for e in entries if e.get("run_id") in set(run_ids) | {run_id}]
        for scope, scoped in scopes.items():
            spent = total_spend(scoped)
            limits = self._limits(cfg, wf_id, scope)
            for unit, key, own in (("tokens", "charged_tokens", tokens),
                                   ("usd", "provider_usd", run_cost_usd(mine) or 0.0)):
                limit = limits[unit]
                if limit is not None and spent[key] > limit >= spent[key] - own:
                    overrun(scope, unit, limit, spent[key])
        return found

    # -- human override ----------------------------------------------------
    def grant_override(self, workflow_id: str, *, extra_tokens: int = 0, extra_usd: float = 0.0,
                       approver: str = "human", reason: str = "") -> dict[str, Any]:
        """Raise a workflow's limits. Human only: refused in non-interactive sessions."""
        ensure_interactive_environment()
        if extra_tokens < 0 or extra_usd < 0:
            raise ValueError("Budget override amounts must be >= 0")
        data = self.load_overrides()
        cur = data.setdefault(workflow_id, {"extra_tokens": 0, "extra_usd": 0.0})
        cur["extra_tokens"] = cur.get("extra_tokens", 0) + extra_tokens
        cur["extra_usd"] = round(cur.get("extra_usd", 0.0) + extra_usd, 6)
        self.overrides_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.overrides_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.overrides_path)
        details = {"extra_tokens": extra_tokens, "extra_usd": extra_usd,
                   "approver": approver, "reason": reason, "totals": dict(cur)}
        self.audit.log_event("budget_override", workflow_id=workflow_id, details=details)
        return {"workflow_id": workflow_id, **details}

    def status(self, workflow_id: str) -> dict[str, Any]:
        """Configured limits, overrides and spend so far for a workflow."""
        cfg = self.load_config()
        if cfg is None:
            return {"enabled": False}
        spent = total_spend(self.ledger.list_entries(workflow_id=workflow_id))
        return {"enabled": True, "config": cfg, "spent": spent,
                "workflow_limits": self._limits(cfg, workflow_id, "workflow"),
                "override": self.load_overrides().get(workflow_id, {})}

