# Antigravity adapter

Guard for shell commands (`run_command`) through Antigravity's PreToolUse hook. Status: the `deny` answer was seen blocking a real command in Antigravity (Gemini 3.8 Flash High, Windows, 2026-10-23, one machine, one run). Everything else is from the documentation. The matrix is in `../../README.md`.

## Install

Use `kit/install.*` with `--tools antigravity` (it copies the two files below and the shared core, and merges `hooks.json`). By hand:

1. Copy `core/policy.py` to `scripts/agentic-ops/core/policy.py` in the project (shared by all adapters).
2. Copy `guard.py` to `.agents/hooks/guard.py`.
3. Merge `hooks.json` into `.agents/hooks.json` (workspace) or `~/.gemini/config/hooks.json` (global; use an absolute path there). The hook name `agentic-ops-guard` is yours to rename; `"enabled": false` on it switches it off.
4. Hooks can be viewed and toggled in the app (Settings, Customizations, Hooks), the IDE menu, or `/hooks` in the CLI.
5. On macOS or Linux change `python` to `python3` in `hooks.json` if needed.

## Behavior and limits

- **Answers.** `{"decision": "allow|ask|deny", "reason"}` on stdout with exit 0.
- **`ask` is answered as `deny`.** Observed live: when the guard answered `ask` for `git push --force origin main`, the IDE ran the command without a prompt. So `guard.py` has `ASK_AS = "deny"`: a destructive command is blocked with a message telling the agent to ask the user in the chat; the user runs it in their own terminal or lifts the guard. Set `ASK_AS = "ask"` (or the environment variable `AGENTIC_OPS_ASK_AS=ask`) when your version enforces `ask`.
- **How the command runs.** The IDE splits the `command` string on spaces and runs it with no shell, from the folder that holds `hooks.json` (`.agents/`). Seen live (Gemini 3.8 Flash High, Windows, 2026-10-25): `python -I hooks/guard.py` worked, `python .agents/hooks/guard.py` failed with a missing file, and a one-liner with nested double quotes (v2.3.0 and v2.3.1) was cut at the first space, so Python raised `SyntaxError: unterminated string literal` and the IDE refused every shell command. That is why the shipped command is the plain `python -B -I hooks/guard.py`: no quotes, no shell characters, a path relative to `.agents/`. Do not add either. A hook that exits non-zero blocks the command (it does not fail open). `python -B` keeps `__pycache__` out of the project; the guard finds the core from its own location.
- **Workspace root.** The IDE loads `.agents/hooks.json` from the folder you opened as the workspace. Open the repository root itself. A live run opened the parent folder of the repository: the guard never loaded and `git push --force` ran. `doctor` cannot see which folder the IDE opened, so it reports this as UNKNOWN and the installer prints a reminder.
- Not documented: exit-code semantics, a Windows-specific command field, and any trust step.
- No read guard: the read tool's argument names are not documented.
- Rules file size: Antigravity truncates any single rule file (`AGENTS.md`, `GEMINI.md`, `.agents/rules/*.md`) over 24,000 bytes. `start-brief`, `precommit-check` and `doctor` warn about it.
- If hooks do not fire in your version, the git hooks and the written rules still apply. `doctor` proves that the guard answers correctly from here; it cannot prove that the IDE calls it.
