---
name: agentic-orchestrator
description: Formulate structured workflow plans, validate schemas, and execute multi-agent tasks via the deterministic agentic orchestrator CLI.
---

# Agentic Orchestrator Skill for Claude Code

Teaches Claude Code how to serve as the host conversational assistant and default planner for `genai-agentic-ops`.

## 1. Host-Native Role (ADR-001, ADR-004)

Claude Code functions as the primary developer interface:
- Discuss goals, analyze user requirements, and construct structured multi-agent plans.
- Do NOT directly perform ad-hoc code modifications when executing orchestrated initiatives; delegate execution to registered workers.
- Governance, dependency graphs, advisory locks, and human approval verification are deterministically managed by the `orchestrator` CLI.
- All orchestration commands are invoked via `python -m orchestrator.cli.main`.

## 2. Formulating Structured Plans

When breaking down an initiative into multi-agent tasks, construct a JSON plan matching `contracts/plan.schema.json`:

```json
{
  "schema_version": "1.0",
  "workflow_id": "wf-<initiative-id>",
  "title": "<Workflow Title>",
  "description": "<Overview of goals and scope>",
  "planner": {
    "id": "claude-code",
    "runtime": "claude-code",
    "attested": false
  },
  "execution_mode": "sequential",
  "approval_required": true,
  "tasks": [
    {
      "task_id": "task-001",
      "title": "<Concise Task Title>",
      "description": "<Detailed specifications for worker>",
      "role": "developer",
      "runtime": "claude-code",
      "allowed_paths": ["src/module/"],
      "acceptance_criteria": [
        "All unit tests pass",
        "Source files maintain <300 lines anti-monolith limit"
      ],
      "verification_commands": [
        "python -m unittest discover -s tests -v"
      ]
    }
  ]
}
```

Key Schema Rules:
- `workflow_id`: Must match `^wf-[a-zA-Z0-9_-]+$`.
- `task_id`: Must match `^task-[a-zA-Z0-9_-]+$`.
- `planner.runtime`: Set to `"claude-code"`, `"host"`, or other registered runtimes.
- `role`: One of `"planner"`, `"developer"`, `"tester"`, `"reviewer"`.
- `allowed_paths`: Bounded directory or file prefixes. Worker file changes outside this set cause automatic governance rejection (`blocked`).

## 3. Saving and Validating Plans

Always write plans to disk before submission to establish an audit trail and allow safe iteration:

1. Save the JSON plan to `.agentic/plans/<workflow_id>.json`.
2. Validate the plan file against `contracts/plan.schema.json` and safety policies:
   ```bash
   python -m orchestrator.cli.main plan validate .agentic/plans/<workflow_id>.json
   ```
3. Inspect the returned JSON envelope (`{"ok": true, ...}`). If validation errors are returned, fix the JSON plan and re-validate before asking for developer confirmation.

## 4. Submitting the Plan

Once approved by the human developer, submit the plan to initialize state:
```bash
python -m orchestrator.cli.main plan submit .agentic/plans/<workflow_id>.json
```
This registers workflow and task records under `.agentic/state/` and marks initial tasks without dependencies as `ready`.

## 5. Executing Tasks

Run individual ready tasks:
```bash
python -m orchestrator.cli.main task run <task_id>
```

Or run all ready tasks sequentially:
```bash
python -m orchestrator.cli.main workflow run <workflow_id>
```

During execution, the orchestrator:
- Acquires process-verified advisory lock (`.agentic/locks/active.json`).
- Captures pre-execution baseline snapshot (including gitignored files).
- Executes worker runtime adapter in headless mode.
- Validates that diff bounds stay strictly within `allowed_paths`.
- Executes declared `verification_commands`.
- Transitions state to `verified` if tests pass, or `blocked` if violations occur.

## 6. Human Approval Gates (ADR-004, ADR-007)

Workers and host assistants are strictly forbidden from self-approving tasks:
- When a task reaches `verified`, it pauses at an approval gate.
- Inspect the approval request:
  ```bash
  python -m orchestrator.cli.main approval show <task_id>
  ```
- Prompt the human user for approval. Provide the command or apply the single-use token:
  ```bash
  python -m orchestrator.cli.main task approve <task_id> --token <token>
  ```
- Downstream dependent tasks are only unlocked once approval is granted.

## 7. Concise Reporting Guidelines

- Do not flood conversational context with entire worker logs.
- Provide high-level status summaries: Task ID, status (`verified` or `blocked`), files changed, test results.
- Direct developer to `.agentic/runs/<run_id>/stdout.log` for raw execution output.
