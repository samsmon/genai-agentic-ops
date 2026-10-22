# Codex adapter

Guard for shell commands (`Bash` tool) through Codex's PreToolUse hook. Status: documented, not tested live (see the matrix in `../../README.md`).

## Install

1. Copy `core/policy.py` to `scripts/agentic-ops/core/policy.py` in the project (shared by all adapters).
2. Copy `guard.py` to `.codex/hooks/guard.py`.
3. Merge `hooks.json` into `.codex/hooks.json` (create it if absent).
4. Start Codex, run `/hooks`, review and **trust** the new hook. Project hooks load only when the project's `.codex/` layer is trusted, and Codex skips a hook again whenever its content changes.

Hooks are on by default; `[features] hooks = false` in `config.toml` turns them off.

## Behavior and limits

- Deny: exit 2 with the reason on stderr. Allow: silent exit 0.
- Codex cannot ask, so a risky command (force push, `reset --hard`, recursive delete) is blocked with a "get the user's confirmation" message. Set `CODEX_ASK_AS = "allow"` in `guard.py` to let those through.
- Only the `Bash` tool is inspected. `apply_patch` and MCP tools are not. A guard on the shell is a safety layer, not a sandbox.
- The command path in `hooks.json` is relative to the session working directory; start Codex at the repo root or edit it to an absolute path.
- Fails open: a missing core prints a warning on stderr and allows.
