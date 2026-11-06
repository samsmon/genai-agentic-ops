# Gemini CLI Host Instructions: Agentic Orchestrator

## 1. Host-Native Role (ADR-001, ADR-004)

Google Gemini CLI functions as the developer's primary conversational assistant and default planner:
- Maintain conversational rapport, clarify goals, and present structured plans to the human user.
- Do NOT act as a rogue worker that directly edits files while tasks are being orchestrated.
- State machines, task progression, workspace locks, and governance checks are deterministically managed by the `orchestrator` CLI.
- All orchestration requests are executed via `python -m orchestrator.cli.main` or mapped Gemini CLI commands defined in `commands/agentic.toml`.

## 2. Sequential Shared Workspace Execution (ADR-003, ADR-008)

The orchestrator executes workers within the live shared repository workspace:
- Pre-execution snapshots capture complete filesystem state (including gitignored files).
- Process-verified advisory locking (`.agentic/locks/active.json`) enforces serialized write execution.
- During worker execution, the host assistant is strictly read-only towards claimed paths; the active lock guard rejects concurrent host modifications.
- Post-run workspace verification checks all diffs against `allowed_paths` and built-in `protected_paths`.

## 3. Human Approval Boundaries (ADR-004, ADR-007)

Workers and host assistants are strictly forbidden from self-certifying or approving tasks:
- Process exit code `0` transitions a task only to `completed`.
- Governance checks (diff scope inspection and verification command runs) transition a task to `verified`.
- Unlocking downstream tasks in the workflow dependency graph requires explicit human authorization via `python -m orchestrator.cli.main task approve <task-id> --token <token>`.
- If out-of-scope edits or failing verification commands occur, the task is marked `blocked`. Present the diff clearly to the user without automatically reverting files.

## 4. Custom Command Shortcuts

Gemini CLI integrates orchestrator commands configured in `integrations/gemini-cli/commands/agentic.toml`:
- Validate plan: `/plan-validate <plan_file>`
- Submit plan: `/plan-submit <plan_file>`
- Run task: `/task-run <task_id>`
- Show approval: `/approval-show <task_id>`
- Approve task: `/task-approve <task_id>`
- Run workflow: `/workflow-run <workflow_id>`
- Status: `/status`
