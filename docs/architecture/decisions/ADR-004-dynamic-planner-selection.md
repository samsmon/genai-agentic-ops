# ADR-004: Dynamic Planner Selection

## Status
Accepted

## Context
In a multi-agent environment, different foundation models have different strengths. A user may converse with Antigravity as their everyday host assistant, but wish to delegate planning to Claude Code (for deep architectural breakdown) or Gemini (for large codebase ingest). Conversely, a developer running Claude Code may wish to plan using Codex.

Hardcoding the host as the sole planner limits system utility. However, allowing dynamic planner delegation introduces critical security risks:
1. Untrusted Plan Content: An external planner reading repository files can be subverted via prompt injection, producing a plan that opens protected paths or executes arbitrary shell commands.
2. Silent Substitution Risk: If an external planner fails or is missing, silently falling back to a different model can produce unexpected plans without user consent.

## Decision
We implement **dynamic planner selection** under strict governance constraints:

1. **Host as Default Planner**:
   - By default, the active host assistant's LLM produces the structured execution plan (`planner: { id: "host", runtime: "host" }`).
   - In host planning mode, the planner identity is self-reported by the host integration and marked with `attested: false`.

2. **Explicit External Planner Selection**:
   - The user or host integration may explicitly specify an external planner runtime (e.g., `planner: { id: "claude", runtime: "claude-code" }`).
   - The orchestrator invokes the external planner through its runtime adapter using a dedicated planning prompt.

3. **External Planner Output as Untrusted Data**:
   - Raw output from an external planner is strictly treated as untrusted data.
   - The generated plan must validate completely against `contracts/plan.schema.json`. Any extra fields, missing constraints, or format errors trigger immediate plan rejection.
   - Built-in protected paths (`.claude/`, `.githooks/`, `RULES.md`, `kit/`, etc.) cannot be included in any task's `allowed_paths`.

4. **Mandatory Human Plan Approval**:
   - Before any tasks from a dynamically generated plan are registered into the state machine, the plan must be approved by the human developer (`approval.plan: required`).

5. **No Silent Fallback**:
   - If the requested planner is not installed, unauthenticated, times out, or fails to generate a valid schema-compliant plan, the orchestrator **must stop and report the failure**.
   - The orchestrator must never silently switch planners without explicit user confirmation.

## Consequences
### Positive
- Maximum architectural flexibility: users can leverage the best planning model for their specific task.
- Immune to silent degradation: users always know which model planned their tasks.
- Prompt injection resilience: external plans are sandboxed by schema validation and human approval.

### Negative / Trade-offs
- External planner invocation requires a round-trip CLI process execution and plan parsing step.
- An extra user approval step is enforced before tasks can begin execution.
