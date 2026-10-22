# kit: optional enforcement

The rules in `RULES.md` are text. The kit turns some of them into checks that run without a model. Install only the modules you want; the bootstrap (Part A) asks.

Honest limits: the Claude Code hooks run only in Claude Code. Other agents are covered by the git hooks (at commit time) and by the written rules. Nothing here replaces branch protection, CI, or code review.

## Modules

| Module | Files | What it does | Runs in |
|---|---|---|---|
| guard | `claude/hooks/guard.py`, `claude/settings.json` | Blocks full reads of big text files, agent attribution lines and git identity changes, `--no-verify`, sleep-loop polling. Asks before destructive commands | Claude Code only |
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
| `claude/settings.json` | `.claude/settings.json` (merge) |
| `claude/hooks/*.py` | `.claude/hooks/` |
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

## Configuration

- `guard.py`: constants at the top (`RULES_DOC`, `BIG_BYTES`, `BLOCK_*`, `ASK_DESTRUCTIVE`). `BLOCK_AGENT_TRAILERS` and `BLOCK_IDENTITY_CHANGE` encode a "no agent attribution in git history" policy; set them to `False` if your project wants attribution.
- `commit-msg` enforces the same policy. Exception on the user's say-so: `ALLOW_AGENT_TRAILER=1 git commit ...`. Remove the hook if you want attribution.
- `precommit-check`: `ALLOW_BIG_FILES=1`, `ALLOW_SECRET_PATTERN=1` (user's call only), `SECRET_SCAN_SKIP='dir/*,other/*'`, rules-file size warning (`-RulesFile`, `-MaxRulesBytes`).
- `start-brief` / `wrap-check` read `docs/CURRENT_OPS.md` by default (`-OpsFile` / `OPS_FILE`). `start-brief` also prints a state file (`NOW.md`) if one exists.
- Handoff module defaults (`NOW.md`, `log/YYYY-MM.md`, `## Awaiting review`, `discussion/` folders) are parameters of `handoff-check.*`.

## Git policy and wrap-check

Under `user-only-git` the agent cannot commit, so uncommitted changes are reported as information rather than failures (`-GitPolicy user-only-git`). Under `agent-commits` (default) unpushed commits and uncommitted tracked changes fail.

## Tests

```
powershell -NoProfile -File tests/run-tests.ps1     # all PowerShell suites, Python guard test, and the bash suite if bash exists
sh tests/run-tests.sh                               # Python guard test and the bash suite
```

Tests build temporary git repositories and delete them afterwards. The `wrap-check` PowerShell suite is the slowest (use `-Skip wrap-check`).
