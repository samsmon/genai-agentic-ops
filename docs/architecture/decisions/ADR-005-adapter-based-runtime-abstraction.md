# ADR-005: Adapter-Based Runtime Abstraction

## Status
Accepted

## Context
Installed coding CLIs (Antigravity CLI `agy`, Claude Code CLI `claude`, Codex CLI `codex`, Gemini CLI `gemini`) differ substantially in their command-line arguments, headless execution flags, permission controls, session management capabilities, and output formatting.
Directly embedding provider-specific CLI logic inside workflow or state coordination code would create tight coupling, brittle code, and high maintenance overhead.

## Decision
We abstract all CLI interactions behind a provider-neutral **Runtime Adapter** interface:

1. **Standard Adapter Protocol**:
   Each CLI adapter implements the standard protocol:
   ```python
   from typing import Protocol, Dict, Any

   class AgentAdapter(Protocol):
       def detect(self) -> bool: ...
       def capabilities(self) -> Dict[str, Any]: ...
       def execute(self, task: Dict[str, Any], handoff: Dict[str, Any]) -> ExecutionResult: ...
       def resume(self, run_handle: str, message: str) -> ExecutionResult: ...
       def interrupt(self, run_handle: str) -> None: ...
   ```

2. **Honest Maturity Classification**:
   Every adapter and capability must declare an explicit verification level:
   - `documented`: Behavior and flags derived solely from official CLI documentation; unverified on the local machine.
   - `fixture-tested`: Adapter output parsing and command construction validated against recorded mock fixtures.
   - `live-tested`: Successfully executed against a genuine, locally installed CLI binary end-to-end.
   Unverified capabilities (such as session resume or streaming) must never be assumed.

3. **Typed Execution Result Structure**:
   Adapters return a strongly-typed execution structure separating process execution metadata from governance verification:
   - `exit_code`: Process integer returncode
   - `timed_out`: Boolean flag indicating if process exceeded execution deadline
   - `permission_denials`: List of permission denial events detected in CLI logs
   - `session_id` / `run_handle`: Provider session identifier if supported
   - `stdout_ref` / `stderr_ref`: Paths to persisted raw output files
   - `duration_ms`: Execution duration in milliseconds

4. **Process Tree Termination**:
   When interrupting or timing out a worker, the adapter must not kill only the parent CLI process, leaving orphaned background processes (e.g., node servers or pytest workers). Adapters must manage process groups (POSIX) or Windows Job Objects to terminate the complete process tree cleanly.

## Consequences
### Positive
- Provider neutrality: the orchestration engine remains completely agnostic to CLI specifics.
- Verifiable reliability: capabilities are accurately advertised based on evidence, preventing silent runtime failures.
- Clean process cleanup: orphan processes cannot continue writing to the workspace.

### Negative / Trade-offs
- Each newly supported CLI requires an adapter implementation with dedicated fixture and integration tests.
