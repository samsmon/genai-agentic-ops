# kit: optional enforcement

The rules in `RULES.md` are text. The kit turns some of them into checks that run without a model. Install only the modules you want; the bootstrap (Part A) asks.

Honest limits: the guard is one neutral core (`core/policy.py`) with one thin adapter per tool, and each tool's hook system is different. The adapters follow each tool's official documentation; only some have been run for real (see the matrix below, and `compat.md` for sources and access dates). Where a tool has no hook, or the adapter is untested, you get the git hooks (at commit time) and the written rules. Nothing here replaces branch protection, CI, or code review.

## Modules

| Module | Files | What it does | Runs in |
|---|---|---|---|
| guard core | `core/policy.py` | The decisions: blocks agent attribution lines and git identity changes, the hook-bypass flag, sleep-loop polling; asks before destructive commands; blocks full reads of big text files. Pure Python, no I/O | Used by every adapter |
| guard adapters | `claude/` (guard.py, settings.json), `adapters/codex/`, `adapters/cursor/`, `adapters/opencode/`, `adapters/antigravity/` | Read the tool's own payload, call the core, answer in the tool's own format. Install only the tools you use | Per tool, see matrix |
| session start | `claude/hooks/session_start.py` | Prints the sync and lock summary at session start, sets `core.hooksPath` | Claude Code only |
| githooks | `githooks/commit-msg`, `githooks/pre-commit` | Rejects agent trailers and agent/bot identities; rejects large files and likely secrets | Any agent that commits |
| scripts | `scripts/start-brief.*`, `scripts/wrap-check.*`, `scripts/precommit-check.*` | Session start summary, end-of-session check, the pre-commit scan | Any agent, any shell |
| handoff (optional) | `handoff/handoff-check.*` | Checks the cross-agent review protocol (rule 13) | Any agent |
| harness builder | `harness-builder.md` | Detail for rule 12 (recommend a harness when work repeats) | Text |

Every script exists in two forms: `.ps1` (Windows PowerShell 5.1 or PowerShell 7) and `.sh` (POSIX sh; `bash` for the tests). Use the one the machine has; they behave the same and have the same test cases.

## Install layout

Copy, never overwrite; show diffs for files that already exist. Merge `claude/settings.json` into an existing `.claude/settings.json`.

| From | To in the project |
|---|---|
| `core/policy.py` | `scripts/agentic-ops/core/policy.py` (every adapter looks for it there, or next to the kit as `core/`) |
| `claude/settings.json` | `.claude/settings.json` (merge) |
| `claude/hooks/*.py` | `.claude/hooks/` |
| `adapters/codex/hooks.json`, `guard.py` | `.codex/hooks.json` (merge), `.codex/hooks/guard.py` |
| `adapters/cursor/hooks.json`, `guard.py` | `.cursor/hooks.json` (merge), `.cursor/hooks/guard.py` |
| `adapters/opencode/agentic-ops-guard.js` | `.opencode/plugins/agentic-ops-guard.js` |
| `adapters/antigravity/hooks.json`, `guard.py` | `.agents/hooks.json` (merge), `.agents/hooks/guard.py` |
| `githooks/*` | `.githooks/` (then `chmod +x .githooks/*` on Unix, or `git update-index --chmod=+x`) |
| `scripts/*` and `handoff/*` | `scripts/agentic-ops/` (wrap-check finds `handoff-check.*` next to itself) |
| `tests/*` | `scripts/agentic-ops/tests/` (optional) |

Then enable the git hooks once per clone: `git config core.hooksPath .githooks` (the session start hook does this automatically in Claude Code).

## Using the scripts

```
# session start
powershell -NoProfile -File scripts/agentic-ops/start-brief.ps1
sh scripts/agentic-ops/start-brief.sh

# end of session (agent name must match the ops log's Agent column)
powershell -NoProfile -File scripts/agentic-ops/wrap-check.ps1 -Agent claude-code -GitPolicy user-only-git
sh scripts/agentic-ops/wrap-check.sh --agent claude-code --git-policy user-only-git
```

Exit codes: `start-brief` exits 2 on any `STOP:` line; `wrap-check` exits 1 when any line starts with `FAIL`. Both are read-only.

`wrap-check -Ignore 'path/*'` (`--ignore`) skips tracked changes that belong to another session, only after the user confirmed they are not yours.

## Compatibility matrix

"Documented" means the adapter follows the tool's official docs and passes tests with payloads copied from them (`tests/fixtures/`). "Tested live" means someone ran the real tool with the hook installed. Nothing is claimed beyond that. Sources and access dates: `compat.md`.

| Tool | Reads `AGENTS.md` | Guard hook | Documented | Tested live |
|---|---|---|---|---|
| Claude Code | Through `CLAUDE.md` containing `@AGENTS.md` | `.claude/settings.json`, PreToolUse (Read, Bash, PowerShell) | Yes | Origin copy of the guard blocked real commands in a Claude Code session on 2026-10-22; the refactored kit version (core + adapter) has payload tests only |
| Codex | Yes (global, then each directory from the repo root; 32 KiB combined by default) | `.codex/hooks.json`, PreToolUse, matcher `Bash`. "Ask" is not supported there, so risky commands are blocked with a "get confirmation" message | Yes | No (not installed here) |
| Cursor | Yes (project root `AGENTS.md`; the CLI also reads `CLAUDE.md`) | `.cursor/hooks.json`, `beforeShellExecution`, native. Cursor can also load the Claude hooks by itself (third-party hooks, on by default); do not enable both for the same command | Yes, shell commands only. No read guard: Cursor's read hook has no `limit` field | No (not installed here) |
| OpenCode | Yes (`AGENTS.md`; falls back to `CLAUDE.md` only when `AGENTS.md` is absent) | `.opencode/plugins/agentic-ops-guard.js`, `tool.execute.before`; a throw blocks. "Ask" becomes a block | Experimental: the shell tool's argument name is not in the docs, so the plugin tries `command`, then `cmd` | No (not installed here; the plugin is tested with Node and fixture inputs) |
| Antigravity | Yes (`AGENTS.md` and `GEMINI.md`, scoped per directory; each rule file is truncated above 24,000 bytes) | `.agents/hooks.json`, PreToolUse, matcher `run_command` | Experimental: the docs show the input and the "ask" output, not a full "deny" example; the deny shape is inferred | No. The IDE is installed on the author's machine, but a hook only fires inside a live agent session, which was not run |

Cross-tool layers that need no hook support: the git hooks (`githooks/`), the scripts (any agent that can run a shell), and the written rules. They are the whole story for any tool or version whose hook adapter is missing or wrong.

## Configuration

- `core/policy.py`: constants at the top (`RULES_DOC`, `BIG_BYTES`, `BLOCK_*`, `ASK_DESTRUCTIVE`). Adapters hold only tool-specific switches (`CODEX_ASK_AS` in the Codex adapter, `ASK_AS` in the OpenCode plugin: set to `allow` to let risky commands through instead of blocking them). `BLOCK_AGENT_TRAILERS` and `BLOCK_IDENTITY_CHANGE` encode a "no agent attribution in git history" policy; set them to `False` if your project wants attribution.
- `commit-msg` enforces the same policy. Exception on the user's say-so: `ALLOW_AGENT_TRAILER=1 git commit ...`. Remove the hook if you want attribution.
- `precommit-check`: `ALLOW_BIG_FILES=1`, `ALLOW_SECRET_PATTERN=1` (user's call only), `SECRET_SCAN_SKIP='dir/*,other/*'`, rules-file size warning (`-RulesFile`, `-MaxRulesBytes`).
- `start-brief` / `wrap-check` read `docs/CURRENT_OPS.md` by default (`-OpsFile` / `OPS_FILE`). `start-brief` also prints a state file (`NOW.md`) if one exists.
- Handoff module defaults (`NOW.md`, `log/YYYY-MM.md`, `## Awaiting review`, `discussion/` folders) are parameters of `handoff-check.*`.

## Git policy and wrap-check

Under `user-only-git` the agent cannot commit, so uncommitted changes are reported as information rather than failures (`-GitPolicy user-only-git`). Under `agent-commits` (default) unpushed commits and uncommitted tracked changes fail.

## Tests

```
powershell -NoProfile -File tests/run-tests.ps1     # all PowerShell suites, the Python tests (guard, policy core, adapters, rules block), and the bash suite if bash exists
sh tests/run-tests.sh                               # the Python tests and the bash suite
```

Tests build temporary git repositories and delete them afterwards. The `wrap-check` PowerShell suite is the slowest (use `-Skip wrap-check`).
