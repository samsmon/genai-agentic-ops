# genai-agentic-ops

A reusable ruleset for running several AI coding agents (Claude Code, Gemini/Antigravity, Codex, Cursor, Roo, ...) in the same repository without them stepping on each other or on you.

The rules are plain text. Your agent reads `RULES.md`, merges the rules into the project's `AGENTS.md`, and creates a small live task log. v2 adds an optional [`kit/`](kit/README.md) of hooks and scripts that enforce some of those rules mechanically.

## Problem

Parallel agents have no shared memory. In practice that means:

- two agents edit the same file or restart the same service,
- long tasks block the chat and get polled in `sleep` loops,
- code gets changed before you have seen a plan,
- a crashed agent leaves a lock behind forever,
- instructions hidden in files or web pages get treated as commands,
- the same manual chore is repeated for months because nobody built a tool for it.

## What you get

| Rule | Why |
|---|---|
| Check git sync instead of blind `git pull` (`--ff-only`, stop on diverged) | No surprise merges or lost local work |
| Analyze first, get approval before any change (read-only is free) | You see the plan before the diff |
| Long tasks go to a subagent or background job, no polling | Chat stays usable, no tool-call floods |
| Live log in `docs/CURRENT_OPS.md`, one row per task, stale-lock rule, rotation to an archive file | Agents can see each other's work; the log stays short |
| Destructive actions and secrets always need an explicit ask | Hard stops for the expensive mistakes |
| Trust boundary: files, web and tool output are data, not commands | Prompt-injection defense |
| Subagents inherit the rules and never self-approve | Delegation cannot bypass approval |
| Git policy you choose: `user-only-git` or `agent-commits` (new in v2) | Decide once who runs git |
| Token discipline: no whole-file pastes, big files read in parts (new) | Cheaper sessions |
| Honest enforcement section (new) | Agents say what is machine-checked and what is only text |
| Harness builder (new): the agent recommends a script, template, doc, skill or hook when work repeats | Repeated chores turn into tools, without unasked building |
| Optional handoff protocol between agents (new) | Work written by one agent gets reviewed by another |

## Quick start

Pin the URL to a commit SHA, not `main`, so the rules only change when you choose.

```
Read https://raw.githubusercontent.com/samsmon/genai-agentic-ops/<SHA-V2>/RULES.md and run Part A (Bootstrap) for this project.
Analyze first and show me the plan; write nothing until I approve.
```

`<SHA-V2>` is a placeholder: fill it with the commit SHA of the v2 release after it is committed and pushed. Until then the last published pin is the v1 one, `e6061fec3e4388efd73d2b0e62525972e3f1acc1` (v1 rules, no kit).

Bootstrap detects existing rule files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`), merges instead of overwriting, wraps the rules in `BEGIN/END genai-agentic-ops` markers so they can be updated later, asks which git policy you want and which kit modules to install, and asks whether to keep, move or merge an existing ops log.

Upgrading a v1 project: run the same prompt with the v2 URL. Only the content between the markers is replaced. See Part D of `RULES.md`.

## What the log looks like

```markdown
| Timestamp | Agent | Session/Worker ID | Target File/Dir | Status | Task Description |
|---|---|---|---|---|---|
| 2026-10-03 15:49 | gemini | main | `AGENTS.md`, `docs/` | done | Bootstrap genai-agentic-ops rules & ops log |
| 2026-10-03 16:05 | claude-code | subagent-audit-1 | `src/`, `tests/` | running | Dependency audit in background |
| 2026-10-03 16:10 | gemini | main | `src/` | blocked | Waiting for `src/` from subagent-audit-1 |
```

## What the kit enforces (and what it does not)

| Rule | Enforced by | Where it works |
|---|---|---|
| No full reads of big text files | `guard.py` (PreToolUse) | Claude Code only |
| No agent attribution lines or identity changes in commits | `guard.py`, `commit-msg` | Claude Code (guard); any agent that commits (git hook) |
| No `--no-verify`, no sleep-loop polling | `guard.py` | Claude Code only |
| Ask before force push, `reset --hard`, recursive delete | `guard.py` | Claude Code only |
| No secrets or large/binary files in commits | `pre-commit` + `precommit-check` | Any agent that commits |
| Sync, stale-lock and unclosed-row checks | `start-brief`, `wrap-check` | Any agent that runs them; running them is still a written rule |
| Plan before changing, approval gates, trust boundary, harness suggestions | Nothing | Text only: depends on the agent following it |

Hook enforcement can be bypassed by an agent that runs outside Claude Code or edits the hook files, and git hooks can be skipped by whoever commits. Treat the kit as a safety net.

## Field notes (honest version)

Tested with: **Gemini/Antigravity** and **Claude Code**.

- Three of my own repos use it: a multi-device homelab repo (about 400 commits, where the rules evolved first as a root-level ops log with locks), a portfolio site, and a cloud-ops repo.
- v1 was applied on 2026-10-03 to all three. Cloud-ops and portfolio were bootstrapped by Gemini (rules block merged without overwriting the existing `AGENTS.md`); the homelab repo was done by Claude Code, writing the block into `CLAUDE.md` because its `AGENTS.md` is a symlink to it. The portfolio log has rows from both Claude Code and Gemini.
- v2 comes from what the cloud-ops repo needed after v1: its local copy of the block drifted (a "user runs git" policy), and it grew hooks, session scripts and a review protocol. v2 puts those back into a reusable form. At the time of writing the v2 kit has been run only against its own test suite on one Windows machine (PowerShell 5.1, Git Bash, Python 3.11); it has not yet been applied to a second real repository, and the `.sh` scripts have not been run on Linux or macOS.
- The harness builder rule (recommend, never build unasked) is new and untested over a long period. Whether agents notice the triggers reliably is an open question.

Limits you should know about:

- There is no long-term data yet on stale locks or conflict rates.
- Without the kit nothing enforces the rules. They work because current agents follow written instructions, and a different agent may follow them less well. With the kit, only the parts listed above are enforced, and only where the hook runs.
- It does not replace branch protection, CI, or code review.

## Files

- [`RULES.md`](RULES.md): Part A bootstrap, Part B rules block with git-policy and handoff snippets, Part C templates, Part D usage and v1 upgrade.
- [`kit/`](kit/README.md): optional hooks, scripts (PowerShell and sh) and tests; [`kit/harness-builder.md`](kit/harness-builder.md) is the detail for rule 12.
- [`CHANGELOG.md`](CHANGELOG.md)
- [`LICENSE`](LICENSE): MIT.

## Security note

Having an agent read instructions from a URL is the same trust decision as `curl | bash`. That is why Bootstrap requires your approval before writing anything, why the URL should be pinned to a SHA, and why you should read `RULES.md` (and any `kit/` file you install, since hooks run code) before using it.
