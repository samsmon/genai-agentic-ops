# ADR-007: Governance-First Execution

## Status
Accepted

## Context
A major failure mode in autonomous coding tools is prioritizing execution velocity over safety controls. If host delegation (M3) is released before baseline tracking, advisory locking, and path scope checks (originally slated for M4), users run the acute risk of uncontrolled file edits, clobbered working trees, and bypassed security boundaries.

Furthermore, existing Agentic Ops already contains a proven, tested policy engine in `kit/core/policy.py` and git safety hooks. Re-implementing these safety rules inside the orchestrator would lead to duplicated logic and divergent behavior between host sessions and worker runs.

## Decision
We enforce a **governance-first** architecture:

1. **Pulling Safety Checks Ahead of Host Delegation**:
   - Pre-execution baseline capture, advisory locking, and path scope checks are pulled forward into M1 and M2, prior to the M3 host integration release.
   - No worker delegation is enabled without active pre-run snapshotting and post-run diff validation.

2. **Reuse `kit/core/policy.py` as Narrow Library**:
   - The orchestrator imports and calls `kit/core/policy.py` through a narrow, well-defined interface:
     `evaluate(action: ActionRequest) -> Decision(allow|ask|deny, reason, rule_id)`
   - Both host hooks and the orchestrator core call this single source of policy truth.

3. **Separation of Completion, Verification, and Approval**:
   - A process exit code of 0 only transitions a task to `completed`.
   - The task cannot transition to `verified` until the orchestrator independently runs verification commands and verifies diff bounds.
   - The task cannot transition to `approved` without explicit human authorization.
   - Workers are strictly prohibited from self-certifying or approving tasks.

4. **Anti-Monolith File Size Verification**:
   - Post-run diff checks automatically inspect modified code files (.py, .ts, .js, .html, etc.).
   - Any modified file exceeding the 500-line hard limit (or expanding beyond the 300-line soft target without approval) triggers a `BLOCKED` status, mirroring pre-commit hook behavior.

## Consequences
### Positive
- System is safe by default before any multi-agent delegation occurs.
- Single unified policy enforcement across all tools and runtimes.
- Workers cannot disguise failing tests or hallucinated success.

### Negative / Trade-offs
- Additional upfront development in M1 and M2 before demoing end-to-end host delegation.
- Verification commands introduce execution latency at the end of each task.
