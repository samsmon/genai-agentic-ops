# ADR-002: Project-Scoped Configuration

## Status
Accepted

## Context
Engineering projects have distinct technology stacks, testing frameworks, coding conventions, safety rules, and sensitivity levels. A single global configuration across an entire machine fails to accommodate project-specific requirements:
- A private internal tool may permit broad write access, while an open-source library requires strict pull-request boundaries and user-only git commits.
- Different repositories use different test runners (`pytest` vs `npm test` vs `go test`).
- Available worker CLIs, installed roles, and path permissions differ per codebase.

## Decision
We decide that configuration, runtime registry, and orchestration state must be **project-scoped**:
1. All project configuration is defined in a project-root configuration file (`agentic.yaml`) or project configuration directory (`.agentic/config.json`).
2. Orchestration state, task runs, intent records, and locks reside strictly in the local project directory under `.agentic/`.
3. An `agentic init` command initializes project configuration, detecting project frameworks and setting baseline policies.
4. Global user configuration (`~/.agentic/`) is limited to machine-wide defaults (such as default CLI paths or provider API settings) and is always overridden by project-local configuration.
5. Project configuration files are subject to schema validation against `config.schema.json`.

## Consequences
### Positive
- Strict isolation: tasks or policies in project A cannot leak into or affect project B.
- Team sharing: project configuration (`agentic.yaml`) can be checked into version control, ensuring uniform agent behavior across developers.
- Fine-grained governance: allowed verification commands and protected paths are customized to the exact repository layout.

### Negative / Trade-offs
- Each project must be initialized before orchestration functions are available.
- State directories (`.agentic/state/`, `.agentic/runs/`, `.agentic/locks/`) must be added to `.gitignore` to prevent tracking runtime churn.
