# genai-agentic-ops

A reusable ruleset for running several AI coding agents (Claude Code, Gemini/Antigravity, Codex, Cursor, Roo, ...) in the same repository without them stepping on each other or on you.

It is plain text. There is no SDK and no runtime. Your agent reads `RULES.md`, merges the rules into the project's `AGENTS.md`, and creates a small live task log.

## Problem

Parallel agents have no shared memory. In practice that means:

- two agents edit the same file or restart the same service,
- long tasks block the chat and get polled in `sleep` loops,
- code gets changed before you have seen a plan,
- a crashed agent leaves a lock behind forever,
- instructions hidden in files or web pages get treated as commands.

## What you get

| Rule | Why |
|---|---|
| Check git sync instead of blind `git pull` (`--ff-only`, stop on diverged) | No surprise merges or lost local work |
| Analyze first, get approval before any change (read-only is free) | You see the plan before the diff |
| Long tasks go to a subagent or background job, no polling | Chat stays usable, no tool-call floods |
| Live log in `docs/CURRENT_OPS.md`, one row per task, stale-lock rule | Agents can see each other's work |
| Destructive actions and secrets always need an explicit ask | Hard stops for the expensive mistakes |
| Trust boundary: files, web and tool output are data, not commands | Prompt-injection defense |
| Subagents inherit the rules and never self-approve | Delegation cannot bypass approval |

## Quick start

Pin the URL to a commit SHA, not `main`, so the rules only change when you choose.

```
Read https://raw.githubusercontent.com/samsmon/genai-agentic-ops/e6061fec3e4388efd73d2b0e62525972e3f1acc1/RULES.md and run Part A (Bootstrap) for this project.
Analyze first and show me the plan; write nothing until I approve.
```

Bootstrap detects existing rule files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`), merges instead of overwriting, wraps the rules in `BEGIN/END genai-agentic-ops` markers so they can be updated later, and asks whether to keep, move or merge an existing ops log.

## What the log looks like

```markdown
| Timestamp | Agent | Session/Worker ID | Target File/Dir | Status | Task Description |
|---|---|---|---|---|---|
| 2026-10-03 15:49 | gemini | main | `AGENTS.md`, `docs/` | done | Bootstrap genai-agentic-ops v1 rules & ops log |
| 2026-10-03 16:05 | claude-code | subagent-audit-1 | `src/`, `tests/` | running | Dependency audit in background |
| 2026-10-03 16:10 | gemini | main | `src/` | blocked | Waiting for `src/` from subagent-audit-1 |
```

## Field notes (honest version)

Tested with: **Gemini/Antigravity** and **Claude Code**.

- Three of my own repos use it: a multi-device homelab repo (about 400 commits, where the rules evolved first as a root-level ops log with locks), a portfolio site, and a cloud-ops repo.
- v1 was applied on 2026-10-03 to all three. Cloud-ops and portfolio were bootstrapped by Gemini (rules block merged without overwriting the existing `AGENTS.md`); the homelab repo was done by Claude Code, writing the block into `CLAUDE.md` because its `AGENTS.md` is a symlink to it. The portfolio log has rows from both Claude Code and Gemini.
- The earlier, looser form of these rules (before v1) was applied in cloud-ops the same day through a series of Gemini commits.

Limits you should know about:

- The v1 versions are days old. There is no long-term data yet on stale locks or conflict rates.
- Nothing enforces the rules. They work because current agents follow written instructions, and a different agent may follow them less well.
- It does not replace branch protection, CI, or code review.

## Files

- [`RULES.md`](RULES.md): Part A bootstrap, Part B rules block, Part C ops log template, Part D usage.
- [`CHANGELOG.md`](CHANGELOG.md)
- [`LICENSE`](LICENSE): MIT.

## Security note

Having an agent read instructions from a URL is the same trust decision as `curl | bash`. That is why Bootstrap requires your approval before writing anything, why the URL should be pinned to a SHA, and why you should read `RULES.md` before using it.
