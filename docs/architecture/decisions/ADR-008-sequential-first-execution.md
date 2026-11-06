# ADR-008: Sequential-First Execution

## Status
Accepted

## Context
Running multiple AI agents concurrently on a shared repository workspace presents severe data-integrity hazards:
- Simultaneous writes to overlapping files produce corrupt merges, lost code edits, and unresolvable diffs.
- Concurrent execution invalidates baseline snapshots: a diff captured after agent A finishes could erroneously include in-progress edits made by agent B.
- Language servers, dev compilers, and test runners lock build cache directories (e.g., `.pytest_cache`, `target/`, `dist/`), causing intermittent build crashes when invoked concurrently.

While concurrent execution offers potential throughput gains, correctness, auditability, and safety are non-negotiable prerequisites.

## Decision
We mandate **sequential-first execution** for all write-capable tasks in the shared workspace:

1. **Serialized Write Tasks**:
   - The workflow engine schedules and dispatches tasks strictly one at a time whenever the task requires write capability (`role != "reviewer"` or `allowed_paths` is non-empty).
   - The active task holds the exclusive workspace lock for its entire lifecycle (`ready` -> `running` -> `completed` -> `verified`).
   - Downstream or independent write tasks queue in `ready` until the active lock is formally released.

2. **Deferred Concurrency Modes**:
   - **Parallel Read-Only Reviewers**: Multiple reviewers running read-only tools without workspace modification may be permitted to run concurrently in future milestones (M6), provided they hold no write locks and diff validation confirms zero changes.
   - **Worktree Isolation**: True parallel write execution is deferred until an isolated git worktree engine with automated 3-way merge conflict reconciliation is designed and tested.

## Consequences
### Positive
- Absolute determinism: every file change can be attributed unambiguously to a single task and runtime run.
- Baseline snapshots and post-run diff validations remain completely accurate and isolated.
- Zero risk of agents clobbering each other's edits.

### Negative / Trade-offs
- Workflow total wall-clock duration equals the sum of sequential task runtimes.
- Does not take full advantage of multi-core parallelism for independent write tasks in the MVP.
