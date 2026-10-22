# Antigravity adapter (experimental)

Guard for shell commands (`run_command`) through Antigravity's PreToolUse hook. Status: experimental, not tested live (see the matrix in `../../README.md`).

## Install

1. Copy `core/policy.py` to `scripts/agentic-ops/core/policy.py` in the project (shared by all adapters).
2. Copy `guard.py` to `.agents/hooks/guard.py`.
3. Merge `hooks.json` into `.agents/hooks.json` (workspace) or `~/.gemini/config/hooks.json` (global). The hook name `agentic-ops-guard` is yours to rename; `"enabled": false` on it switches it off.
4. Hooks can be viewed and toggled in the app (Settings, Customizations, Hooks), the IDE menu, or `/hooks` in the CLI.
5. On macOS or Linux change `python` to `python3` in `hooks.json` if needed.

## Behavior and limits

- Answers `{"decision": "allow|ask|deny", "reason"}` on stdout with exit 0. The docs show the `ask` output as an example; the `deny` shape is inferred from the field description. If a denied command still runs, change `answer()` in `guard.py`.
- Not documented: exit-code semantics, a Windows-specific command field, the working directory of hook commands, and any trust step. The command path in `hooks.json` is relative; use an absolute path if hooks run elsewhere.
- No read guard: the read tool's argument names are not documented.
- Rules file size: Antigravity truncates any single rule file (`AGENTS.md`, `GEMINI.md`, `.agents/rules/*.md`) over 24,000 bytes. `start-brief` and `precommit-check` warn about it.
- If hooks do not fire in your version, the git hooks and the written rules still apply.
