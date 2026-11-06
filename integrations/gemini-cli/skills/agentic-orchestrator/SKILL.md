---
name: agentic-orchestrator
description: Formulate structured workflow plans, validate schemas, and execute multi-agent tasks via the deterministic agentic orchestrator CLI.
---

# Agentic Orchestrator Skill for Gemini CLI

Teaches Gemini CLI how to serve as the host conversational assistant and default planner for `genai-agentic-ops`.

## 1. Host-Native Role (ADR-001, ADR-004)

Gemini CLI functions as the developer's primary conversational assistant and default planner:
- Maintain context, formulate structured multi-agent plans, and guide the user through execution.
- Do NOT directly perform ad-hoc code edits on tasks undergoing orchestration.
- State machines, task progression, workspace locks, and governance checks are deterministically managed by the `orchestrator` CLI.
- All orchestration commands are invoked via `python -m orchestrator.cli.main` or native commands in `commands/agentic.toml`.

## 2. Formulating Structured Plans

When breaking down an initiative into multi-agent tasks, construct a JSON plan matching `contracts/plan.schema.json`:

```json
{
  "schema_version": "1.0",
  "workflow_id": "wf-<initiative-id>",
  "title": "<Workflow Title>",
  "description": "<Overview of goals and scope>",
  "planner": {
    "id": "gemini-cli",
    "runtime": "gemini-cli",
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
      "runtime": "gemini-cli",
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
- `planner.runtime`: Set to `"gemini-cli"`, `"host"`, or other registered runtimes.
- `role`: One of `"planner"`, `"developer"`, `"tester"`, `"reviewer"`.
- `allowed_paths`: Bounded file and directory prefixes for worker modifications.

## 3. Saving and Validating Plans

Always persist plans to disk before submission to establish an audit trail and enable iterative correction:

1. Save the JSON plan to `.agentic/plans/<workflow_id>.json`.
2. Validate the plan file against `contracts/plan.schema.json` and safety policies:
   ```bash
   python -m orchestrator.cli.main plan validate .agentic/plans/<workflow_id>.json
   ```
3. Inspect the returned JSON envelope (`{"ok": true, ...}`). If errors occur, correct the JSON plan and re-validate before presenting it to the user.

## 4. Submitting the Plan

Once confirmed by the human developer, submit the plan to initialize state:
```bash
python -m orchestrator.cli.main plan submit .agentic/plans/<workflow_id>.json
```
This registers workflow and task records under `.agentic/state/` and marks initial independent tasks as `ready`.

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

- Never flood conversational context with raw worker output.
- Emit concise status summaries: Task ID, status (`verified` or `blocked`), files changed, test results.
- Direct developer to `.agentic/runs/<run_id>/stdout.log` for raw execution output.
