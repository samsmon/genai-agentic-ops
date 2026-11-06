# ADR-006: Filesystem Persistence Before Database

## Status
Accepted

## Context
Orchestrating multi-agent tasks requires persistent storage for workflow states, task definitions, execution logs, and advisory locks across process invocations.
Using an external database (e.g., PostgreSQL, Redis) introduces significant operational dependencies and setup hurdles for a lightweight developer tool. Even an embedded database (such as SQLite) introduces binary file diffing issues in version control, potential concurrent locking bugs across different platforms, and opaque inspection for developers.

## Decision
We select **filesystem-based persistence** using human-readable JSON files for the MVP, structured under `.agentic/`:

1. **Storage Layout**:
   - `.agentic/state/`: Canonical task and workflow JSON state records.
   - `.agentic/plans/`: Stored plan definitions submitted by host or external planners.
   - `.agentic/runs/`: Append-only execution records, audit logs, and raw process stdout/stderr references.
   - `.agentic/locks/`: Active advisory lock files.

2. **Atomic Writes via Write-Replace**:
   - To eliminate file corruption during abrupt shutdowns or power failures, all state and artifact writes must use atomic write-replace semantics:
     Write full content to a temporary file in the same target folder (`<file>.tmp.<pid>`), flush to disk, and atomically rename (`os.replace`) to the final target path.

3. **Write-Ahead Intent Logging**:
   - State mutations involving external side effects (spawning worker processes, acquiring locks) write an `intent-<run_id>.json` file before executing the action.
   - Upon process completion, a corresponding `result-<run_id>.json` is written.
   - Orchestrator recovery checks for orphaned intents upon startup to reconcile crash states.

4. **One-Way Projection to CURRENT_OPS.md**:
   - `docs/CURRENT_OPS.md` is strictly treated as an emitted Markdown projection of the machine state in `.agentic/state/`.
   - The orchestrator regenerates the active rows in `CURRENT_OPS.md` whenever state changes, keeping human documentation in sync without manual drift.

## Consequences
### Positive
- Zero external dependencies: works out of the box on any machine with standard filesystem access.
- Total transparency: developers can inspect, read, and debug all states using standard text editors, `cat`, or `jq`.
- Resilient crash recovery without database corruption risks.

### Negative / Trade-offs
- High-volume concurrency or thousands of simultaneous queries would experience filesystem I/O overhead (acceptable for sequential local developer orchestration).
- An SQLite backend may be evaluated in future milestones (M6+) if workflow state history scales significantly.
