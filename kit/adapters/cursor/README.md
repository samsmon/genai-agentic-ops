# Cursor adapter

Guard for shell commands through Cursor's `beforeShellExecution` hook. Status: documented, not tested live (see the matrix in `../../README.md`).

## Install

1. Copy `core/policy.py` to `scripts/agentic-ops/core/policy.py` in the project (shared by all adapters).
2. Copy `guard.py` to `.cursor/hooks/guard.py`.
3. Merge `hooks.json` into `.cursor/hooks.json` (create it if absent). Project hook commands run from the project root.
4. On macOS or Linux change `python` to `python3` in `hooks.json` if `python` is not on the path.

## Behavior and limits

- Answers `{"permission": "allow|ask|deny", "user_message", "agent_message"}` on stdout with exit 0. Cursor can ask, so destructive commands show a confirmation.
- `failClosed` is `false`: if the hook crashes or times out, the command runs. Set it to `true` for a hard guard, at the cost of blocking when Python is missing.
- No read guard: Cursor's read hook has no `limit` field, so the big-file rule would block every large read.
- The Cursor CLI (`cursor-agent`) has been reported to fire only part of the hook events; shell hooks are the ones reported working. Check your version.
- Cursor can import `.claude/settings.json` hooks by itself ("third-party hooks", on by default). If you installed the Claude adapter too, the same command may be checked twice. Keep one of the two.
