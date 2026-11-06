---
name: agentic-orchestrator
description: Formulate structured workflow plans, validate schemas, and execute multi-agent tasks via the deterministic agentic orchestrator CLI.
---

# Agentic Orchestrator Skill

Teaches Antigravity how to serve as the host conversational assistant and planner for `genai-agentic-ops`.

## 1. Formulating Structured Plans

When breaking down an initiative into multi-agent tasks, construct a JSON plan matching `contracts/plan.schema.json`:

```json
{
  "schema_version": "1.0",
  "workflow_id": "wf-<initiative-id>",
  "title": "<Workflow Title>",
  "description": "<Overview of goals>",
  "planner": {
    "id": "antigravity",
    "runtime": "antigravity",
    "attested": true
  },
  "execution_mode": "sequential",
  "approval_required": true,
  "tasks": [
    {
      "task_id": "task-001",
      "title": "<Concise Task Title>",
      "description": "<Detailed instructions for worker>",
      "role": "developer",
      "runtime": "antigravity",
      "allowed_paths": ["src/module/"],
      "acceptance_criteria": ["All unit tests pass", "Anti-monolith limit <300 lines maintained"],
      "verification_commands": ["python -m unittest discover -s tests -v"]
    }
  ]
}
```

## 2. Saving and Validating Plans

1. Save the JSON plan to `.agentic/plans/<workflow_id>.json`.
2. Validate the plan file against `contracts/plan.schema.json` and safety policies:
   ```powershell
   python -m orchestrator.cli.main plan validate .agentic/plans/<workflow_id>.json
   ```
3. If errors are returned, correct the plan file and re-validate before presenting to the user.

## 3. Submitting the Plan

Once approved by the human developer:
```powershell
python -m orchestrator.cli.main plan submit .agentic/plans/<workflow_id>.json
```
This registers the tasks in `.agentic/state/` and marks initial independent tasks as `ready`.

## 4. Executing Tasks

Run individual ready tasks:
```powershell
python -m orchestrator.cli.main task run <task-id>
```

Or execute eligible tasks sequentially across the shared workspace:
```powershell
python -m orchestrator.cli.main workflow run <workflow_id>
```

The orchestrator deterministically:
- Acquires process-verified advisory lock (`.agentic/locks/active.json`).
- Snapshots baseline state across the workspace (including gitignored files).
- Executes worker runtime adapter in headless mode.
- Validates that diff bounds stay strictly within `allowed_paths`.
- Executes declared `verification_commands`.
- Transitions state to `verified` if tests pass, or `blocked` if diff violations or failures occur.

## 5. Human Approval Gates

When a task reaches `verified`, request developer approval before downstream tasks unlock:
```powershell
python -m orchestrator.cli.main task approve <task-id>
```

## 6. Concise Reporting Guidelines

- Never flood conversation context with hundreds of lines of worker stdout/stderr.
- Emit short summaries: Task ID, status (`verified` or `blocked`), changed files count, and test pass/fail status.
- Direct the developer to inspect detailed logs under `.agentic/runs/<run_id>/stdout.log`.
