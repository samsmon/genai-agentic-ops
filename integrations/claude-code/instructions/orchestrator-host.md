# Claude Code Host Instructions: Agentic Orchestrator

## 1. Host-Native Role (ADR-001, ADR-004)

Claude Code functions as the developer's primary conversational assistant and default planner:
- Interact with the developer, clarify goals, and formulate structured plans matching `contracts/plan.schema.json`.
- Do NOT act as an unregistered worker that modifies code directly while multi-agent tasks are orchestrated.
- State machines, task progression, workspace locks, and governance checks are deterministically managed by the `orchestrator` CLI.
- All orchestration commands are executed via `python -m orchestrator.cli.main`.

## 2. Sequential Shared Workspace Execution (ADR-003, ADR-008)

The orchestrator executes workers within the live shared repository workspace:
- Pre-execution snapshots capture complete filesystem state (including gitignored files).
- Process-verified advisory locking (`.agentic/locks/active.json`) enforces serialized write execution.
- During worker execution, the host assistant is strictly read-only towards claimed paths; the `active_lock_guard` PreToolUse hook intercepts and rejects concurrent host `Edit` and `Write` calls.
- Post-run workspace verification checks all diffs against `allowed_paths` and built-in `protected_paths`.

## 3. Human Approval Boundaries (ADR-004, ADR-007)

Workers and host assistants are strictly forbidden from self-certifying or approving tasks:
- Process exit code `0` transitions a task only to `completed`.
- Governance checks (diff scope inspection and verification command runs) transition a task to `verified`.
- Unlocking downstream tasks in the workflow dependency graph requires explicit human authorization via `python -m orchestrator.cli.main task approve <task-id> --token <token>`.
- If out-of-scope edits or failing verification commands occur, the task is marked `blocked`. Present the diff clearly to the user without automatically reverting files.

## 4. Hook and Settings Setup

Include the active lock guard in `.claude/settings.json` or `hooks.json` to prevent concurrent writes during active worker runs:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python -B -I integrations/claude-code/hooks/active_lock_guard.py"
          }
        ]
      }
    ]
  }
}
```
