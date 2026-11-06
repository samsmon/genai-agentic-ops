# ADR-001: Host-Native Orchestration

## Status
Accepted

## Context
Software developers work primarily within modern AI coding assistants such as Antigravity, Claude Code, Codex, and Gemini CLI. Existing multi-agent frameworks often force developers into dedicated web dashboards or proprietary chat terminals, severing their existing developer environment, custom extensions, and established workflows.

Furthermore, host assistants already feature rich context windows, editor integrations, and advanced conversational understanding. Re-implementing a conversational interface in the orchestrator is redundant and creates user friction.

## Decision
We adopt a **host-native** orchestration model:
1. The user's preferred host coding assistant remains the primary interactive interface and default planner.
2. The orchestrator is implemented as a deterministic command-line interface (CLI) and core state engine (`agentic`), not an independent chat application.
3. Host assistants interface with the orchestrator via host-native skills, slash commands, instructions, and hooks.
4. The orchestrator manages deterministic state machines, task queues, dependency graphs, workspace safety locks, and runtime adapter invocations.
5. All execution updates, verification results, and diff summaries are returned to the host assistant in machine-readable envelopes for presentation to the user.

## Consequences
### Positive
- Zero developer workflow disruption: developers interact inside their existing IDE/CLI tools.
- Provider-neutral: the same orchestration core and protocol serve Antigravity, Claude Code, Codex, and Gemini CLI.
- Token efficiency: the host assistant is not flooded with raw worker logs; it receives concise structured results and artifact pointers.

### Negative / Trade-offs
- Each host requires a dedicated host integration layer (skills/hooks/workflows).
- Host assistants cannot be completely constrained by natural language alone; deterministic hooks (`PreToolUse`, `Stop`) are required to prevent host LLMs from bypassing the orchestrator.
