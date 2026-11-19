# Budget guard

Status: implemented, tested with a mock adapter only. No runtime's live usage output has been checked against it.

## What it does

An optional `budget` object in `.agentic/config.json` caps spend. Without it nothing is checked, logged or written, and behaviour is unchanged.

```json
{"budget": {
  "max_task_tokens": 50000,
  "max_workflow_tokens": 200000,
  "max_workflow_usd": 5.0,
  "max_run_tokens": 100000,
  "max_run_usd": 2.5,
  "warn_ratio": 0.8,
  "on_estimate_only": "charge"
}}
```

A task may also carry its own `max_task_tokens`. "Run" means one `run_workflow` call. An invalid `budget` object stops execution (fail closed).

## Limitation: this is not a hard mid-run cap

Provider usage is known only after a run ends. The guard therefore works at two points:

1. **Admission**, before a task starts: blocked when the spend so far has reached a limit, or when spend plus the task's estimate would cross it. The estimate is the task's own cap, else the median of earlier runs of the same role, else zero. A limit of `0` blocks everything.
2. **Accounting**, after the run: the real spend is charged and any overshoot is logged.

The per-task `timeout_seconds` stays the only mid-run stop. One task can overshoot a limit by what it spends in a single run; that is recorded as `budget_exceeded` with `decision: overrun_recorded`, and the next admission is blocked.

## Units and token source

A run is charged with provider tokens (input plus output) when the runtime reported them, otherwise with the byte-based estimate. Provider and estimated figures are kept in separate fields (`provider_tokens`, `estimated_tokens`) and are never merged in reports; only the token-limit comparison adds them. USD limits use provider `cost_usd` only. There is no price table, so runs without a reported cost count as `usd_unmeasured_runs` and add nothing to USD spend. `on_estimate_only: "block"` refuses to continue a workflow once any of its spend is estimate-only.

## When a limit is hit

- The task stays `READY` (no new state; it was never started) and `run_task` raises `BudgetExceededError`. `run_workflow` stops and returns `budget_blocked`.
- Audit events: `budget_warning` at `warn_ratio`, `budget_exceeded` (`blocked_admission` or `overrun_recorded`, with scope, unit, limit, spent and the source breakdown), `budget_override`.
- Override is human only: `agentic budget approve --workflow-id W --extra-tokens N [--extra-usd X] --reason T`. It is refused when `AGENTIC_NON_INTERACTIVE=1` and has no MCP tool. Overrides are stored in `.agentic/budget/overrides.json`. `agentic budget status --workflow-id W` shows limits and spend.

## Cost per accepted change

`coord.telemetry_summary()` (used by `status`, `watch` and MCP) joins the ledger with human approvals and adds:

- `runs`: one record per run with `verified`, `approved`, `charged_tokens`, `token_source`, `cost_usd`.
- `accepted_changes`: distinct approved tasks.
- `cost_per_accepted_change`: spend of all runs, failed and blocked included, divided by accepted changes, per token source. `null` when nothing is accepted.

Ledger entries stay at `schema_version` 1.1; approval is joined at read time because it happens after the entry is written. Retries of one task count their spend but only one accepted change.

## Not covered

Streaming usage from adapters (needed for a true mid-run stop), model price tables, and per-role or per-runtime budgets.
