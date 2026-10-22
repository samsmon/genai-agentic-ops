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
| Git policy you choose (v2): `agent-commits` gives agents full git control (commit, push, branch, PR, merge) while force push, `reset --hard` and history rewrites still ask; `user-only-git` keeps git in your hands | Decide once who runs git |
| Commit messages are Conventional Commits in English, checked by a git hook (new in v2.2) | Readable history, and no prefix or trailer that names an agent |
| Hidden mode (new in v2.2, default): the agentic files stay out of the project's history and sync through an overlay repository | A clean project repository, and the same rules on every device |
| Token discipline: no whole-file pastes, big files read in parts (new) | Cheaper sessions |
| Honest enforcement section (new) | Agents say what is machine-checked and what is only text |
| Harness builder (new): the agent recommends a script, template, doc, skill or hook when work repeats | Repeated chores turn into tools, without unasked building |
| Optional handoff protocol between agents (new) | Work written by one agent gets reviewed by another |

## Quick start

Pin the URL to a commit SHA, not `main`, so the rules only change when you choose.

```
Read https://raw.githubusercontent.com/samsmon/genai-agentic-ops/5baef69cde25b196ad2c0cb19fc9595fa50e80ab/RULES.md and run Part A (Bootstrap) for this project.
Analyze first and show me the plan; write nothing until I approve.
```

The v1 pin, `e6061fec3e4388efd73d2b0e62525972e3f1acc1` (v1 rules, no kit), stays valid for projects that remain on v1.

Bootstrap detects existing rule files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.cursorrules`), merges instead of overwriting, wraps the rules in `BEGIN/END genai-agentic-ops` markers so they can be updated later, asks which git policy you want (it recommends `agent-commits` for your own repositories), whether the agentic files stay hidden from the project history (default) and where the overlay lives, which kit modules to install, and whether to keep, move or merge an existing ops log.

Upgrading a v1 project: run the same prompt with the v2 URL. Only the content between the markers is replaced. See Part D of `RULES.md`, which also lists what changes from v2.0 and v2.1 to v2.2 (the pin above is v2.0.0; the v2.2 pin is filled in here after it is committed).

## What the log looks like

```markdown
| Timestamp | Agent | Session/Worker ID | Target File/Dir | Status | Task Description |
|---|---|---|---|---|---|
| 2026-10-03 15:49 | gemini | main | `AGENTS.md`, `docs/` | done | Bootstrap genai-agentic-ops rules & ops log |
| 2026-10-03 16:05 | claude-code | subagent-audit-1 | `src/`, `tests/` | running | Dependency audit in background |
| 2026-10-03 16:10 | gemini | main | `src/` | blocked | Waiting for `src/` from subagent-audit-1 |
```

## Git policy and hidden mode (v2.2)

| | `agent-commits` (recommended for your own repositories) | `user-only-git` |
|---|---|---|
| Commit, push, create branches, open PRs, merge | Agent, without asking again (checks must pass; branch protection still applies) | You |
| Force push, `reset --hard`, `clean -fd`, delete branches or tags, rewrite history, bypass protection | Agent asks first | Agent does not run them |
| Author and committer | Always your configured identity; never an agent or bot, never `Co-Authored-By`, `Signed-off-by` or `Generated-by` | Same |
| Commit message | Conventional Commits, English, checked by the `commit-msg` hook | Same, for the messages the agent suggests |

Hidden mode keeps `AGENTS.md`, the pointer files, the ops log, the hook folders and `scripts/agentic-ops/` out of the project history. They live in a separate overlay repository (`.git/agentic`, branch `agentic-ops`) and are hidden from the project's git by `.git/info/exclude`, so the project's `git status` and `git log` stay clean. `agentic-sync` restores them on another device: clone the project, run `init` once. Limits: a public remote shows the overlay branch (use a private repository for the overlay), cloud agents and CI only see what the project commits, and the exclude is per clone. Full detail: [`kit/README.md`](kit/README.md#hidden-mode-a-project-history-without-agent-files).

## What the kit enforces (and what it does not)

| Rule | Enforced by | Where it works |
|---|---|---|
| No full reads of big text files | Guard (PreToolUse), read check | Claude Code only: other tools' read hooks lack the fields to do this safely |
| Conventional Commits format (no prefix before the type, lowercase imperative subject, 72-character limit) | `commit-msg` git hook, `commit-msg-check.sh` | Any agent that commits |
| No agent attribution lines or identity changes in commits | Guard on shell commands; `commit-msg` git hook | Guard: Claude Code, Codex, Cursor, OpenCode, Antigravity (adapters, see matrix); git hook: any agent that commits |
| No hook-bypass flag, no sleep-loop polling | Guard on shell commands | Same tools as the row above |
| Ask before force push, `reset --hard`, recursive delete | Guard on shell commands | Claude Code, Cursor, Antigravity can ask; Codex and OpenCode block with a "confirm with the user" message |
| No secrets or large/binary files in commits | `pre-commit` + `precommit-check` | Any agent that commits |
| Sync, stale-lock and unclosed-row checks, oversize rules-file warning | `start-brief`, `wrap-check`, `precommit-check` | Any agent that runs them; running them is still a written rule |
| Plan before changing, approval gates, trust boundary, harness suggestions | Nothing | Text only: depends on the agent following it |

### Which tools it works with

One neutral policy core, one thin adapter per tool. "Documented" means the adapter follows the tool's official docs and passes tests with payloads copied from them; "tested live" means the real tool was run with the hook installed. Details, sources and access dates: [`kit/README.md`](kit/README.md) and [`kit/compat.md`](kit/compat.md).

| Tool | Reads `AGENTS.md` | Guard hook | Status |
|---|---|---|---|
| Claude Code | Via `CLAUDE.md` with `@AGENTS.md` | Yes | Documented. Live: the origin copy of the guard ran in real sessions; the refactored version is payload-tested only |
| Codex | Yes | Yes (cannot ask) | Documented, not tested live |
| Cursor | Yes | Yes (shell commands) | Documented, not tested live |
| OpenCode | Yes | Plugin | Experimental (shell tool argument name undocumented), not tested live |
| Antigravity | Yes (rule files are truncated above 24,000 bytes) | Yes | Experimental (deny output shape inferred), not tested live |

If a tool has no adapter or its hook does not fire, you still get the git hooks, the scripts and the written rules. Hook enforcement can be bypassed by an agent that edits the hook files, and git hooks can be skipped by whoever commits. Treat the kit as a safety net.

## Field notes (honest version)

Used for real, with the rules text (`AGENTS.md`), by: **Gemini/Antigravity** and **Claude Code**. The hook adapters for Codex, Cursor, OpenCode and Antigravity follow the vendors' docs and are tested with documented payloads only; none has been run inside its real tool yet (see the matrix above).

- Three of my own repos use it: a multi-device homelab repo (about 400 commits, where the rules evolved first as a root-level ops log with locks), a portfolio site, and a cloud-ops repo.
- v1 was applied on 2026-10-03 to all three. Cloud-ops and portfolio were bootstrapped by Gemini (rules block merged without overwriting the existing `AGENTS.md`); the homelab repo was done by Claude Code, writing the block into `CLAUDE.md` because its `AGENTS.md` is a symlink to it. The portfolio log has rows from both Claude Code and Gemini.
- v2 comes from what the cloud-ops repo needed after v1: its local copy of the block drifted (a "user runs git" policy), and it grew hooks, session scripts and a review protocol. v2 puts those back into a reusable form. At the time of writing the v2 kit has been run only against its own test suite on one Windows machine (PowerShell 5.1, Git Bash, Python 3.11); it has not yet been applied to a second real repository, and the `.sh` scripts have not been run on Linux or macOS.
- The harness builder rule (recommend, never build unasked) is new and untested over a long period. Whether agents notice the triggers reliably is an open question.

Limits you should know about:

- There is no long-term data yet on stale locks or conflict rates.
- Without the kit nothing enforces the rules. They work because current agents follow written instructions, and a different agent may follow them less well. With the kit, only the parts listed above are enforced, and only where the hook runs.
- Rule files have size limits in some tools: Antigravity truncates any single file over 24,000 bytes and Codex stops at 32 KiB combined by default. The v2 rules block is under 8,000 characters (about 10,000 with the git-policy, hidden-mode and handoff snippets filled in), and your whole `AGENTS.md` counts. `start-brief` and `precommit-check` warn.
- It does not replace branch protection, CI, or code review.

## Files

- [`RULES.md`](RULES.md): Part A bootstrap, Part B rules block with git-policy and handoff snippets, Part C templates, Part D usage and v1 upgrade.
- [`kit/`](kit/README.md): optional hooks (Claude Code, Codex, Cursor, OpenCode, Antigravity adapters over one core), scripts (PowerShell and sh, including `agentic-sync` for hidden mode and the commit message checker) and tests; [`kit/commit-format.md`](kit/commit-format.md) has the commit rules; [`kit/compat.md`](kit/compat.md) has the sources; [`kit/harness-builder.md`](kit/harness-builder.md) is the detail for rule 12.
- [`CHANGELOG.md`](CHANGELOG.md)
- [`LICENSE`](LICENSE): MIT.

## Security note

Having an agent read instructions from a URL is the same trust decision as `curl | bash`. That is why Bootstrap requires your approval before writing anything, why the URL should be pinned to a SHA, and why you should read `RULES.md` (and any `kit/` file you install, since hooks run code) before using it.
