# ADR-003: Shared Workspace Execution

## Status
Accepted

## Context
When orchestrating multiple coding agents, a fundamental choice exists between:
1. Isolated worktrees/containers (cloning the repo or using `git worktree` for each worker).
2. Shared workspace (workers operate directly in the developer's working directory).

While git worktrees provide file-level isolation, they introduce severe practical issues in developer environments: dependency reinstall overhead (`node_modules`, python virtualenvs), file watcher confusion, port conflicts, lost language server caches, and complex merge conflicts when reconciling work. Most developers prefer agents to edit code in their live workspace so they can observe changes in their active editor.

However, operating in a shared workspace without strict guards risks clobbering uncommitted user changes, silent modifications to sensitive files (e.g., `.env`), and race conditions between concurrent agents.

## Decision
We adopt **shared workspace execution** as the MVP model, governed by the following safety protocol:

1. **Pre-Execution Baseline Snapshot**:
   - The orchestrator captures full workspace state prior to spawning a worker.
   - Because `git status` ignores files matching `.gitignore` (such as `.env` or credentials), the snapshot performs a shallow filesystem walk recording `(path, size, mtime, sha256)` for all root and configured files, ensuring gitignored protected files are tracked.
   - Active staged and unstaged git changes are recorded. Pre-existing user modifications are protected.

2. **Advisory Process Locking & Windows Staleness Tuple**:
   - To prevent concurrent conflicting workers, an advisory lock file (`.agentic/locks/workspace.lock`) is acquired atomically using `O_EXCL` and atomic write (`os.replace`).
   - The lock records a process identity tuple: `(hostname, pid, process_start_time)`.
   - On Windows, PIDs are frequently reused by the operating system. The lock validator reads the process creation timestamp from the OS kernel to confirm whether the process owning the lock is genuinely the active worker, rather than relying on PID or lock age alone.

3. **Sequential Execution**:
   - Only one write-capable worker may hold the workspace lock and execute at any given time.

4. **Post-Execution Diff & Path Scope Validation**:
   - After worker exit, the workspace is re-scanned against the baseline.
   - Changed paths are verified against the task's `allowed_paths` and built-in protected paths.

5. **Strict No-Auto-Revert Policy**:
   - If unexpected modifications, deletions, or out-of-scope edits occur, the orchestrator **must never automatically revert or discard files**.
   - The task is immediately marked `BLOCKED`, the lock is retained or frozen, and the diff is presented to the human developer for resolution.

## Consequences
### Positive
- Direct compatibility with developer IDEs, build caches, and dev servers.
- Zero duplicate dependency installations or worktree disk bloat.
- Comprehensive detection of unauthorized edits, including sensitive gitignored files.

### Negative / Trade-offs
- Concurrency is serialized: write-capable workers cannot execute simultaneously in the same workspace.
- The advisory lock coordinates cooperating tools; rogue processes outside the harness are not sandboxed by this lock alone.
