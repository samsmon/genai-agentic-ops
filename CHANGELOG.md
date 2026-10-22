# Changelog

## v2.1.0 - unreleased (date and SHA are filled in when committed)
- The pin `5baef69cde25b196ad2c0cb19fc9595fa50e80ab` stays valid for v2.0.0. The Part B rules block is byte-for-byte unchanged in this release (marker stays `v2`), so a project bootstrapped from that pin has the same block as one bootstrapped from this version; only Part A, the kit and the docs change.
- Guard works beyond Claude Code. New agent-neutral core `kit/core/policy.py` (all guard decisions in one pure function) and thin adapters: `kit/claude/hooks/guard.py` (now calls the core, same behavior), `kit/adapters/codex/`, `kit/adapters/cursor/`, `kit/adapters/opencode/`, `kit/adapters/antigravity/`. Each adapter has its own README.
- Honest compatibility matrix in `kit/README.md` and `README.md`, sources and access dates in `kit/compat.md`. Codex and Cursor adapters follow the official docs; OpenCode and Antigravity are marked experimental (undocumented shell argument name; inferred deny output shape). None of the four has been run inside its real tool yet.
- Codex and OpenCode cannot ask the user, so "ask" decisions are blocked with a "get the user's confirmation" message (configurable).
- Rules-file size warning: `start-brief` and `precommit-check` (PowerShell and sh) warn when `AGENTS.md` is over 24,000 bytes, the point where Antigravity truncates a rule file. The block test caps Part B at 8,000 characters.
- Part A: per-tool pointer lines (`CLAUDE.md` gets `@AGENTS.md`; Codex, Cursor and OpenCode need nothing; `GEMINI.md` only if it already exists), per-tool install layout for the adapters, and the size note.
- Tests: `test_policy.py` (core), `test_adapters.py` plus `opencode-plugin.test.mjs` (adapters, with documented payloads in `kit/tests/fixtures/`), size-warning cases in the script suites.

## v2.0.0 - 2026-10-22 (pin: `5baef69cde25b196ad2c0cb19fc9595fa50e80ab`)
- `RULES.md` marker version `v1` -> `v2`. The v1 file and its SHA pin stay valid for projects that remain on v1.
- Bootstrap now asks for a git policy (`user-only-git` or `agent-commits`) and which kit modules to install. Rules block gets sections 9 (git policy, snippet B1/B2), 10 (token discipline), 11 (enforcement, honest about what is text), 12 (harness builder). Optional handoff section 13 (snippet B3).
- Ops log: keep at most 5 finished rows in the main table, rotate older ones to `docs/CURRENT_OPS-archive.md` (not read at session start). Part C adds the archive template. Rule 3 no longer says to commit rows itself; that follows the git policy.
- Harness builder: when work repeats (second occurrence, "every time", a deterministic manual procedure, a recurring mistake) the agent adds one recommendation block to its report instead of building. Declined suggestions go to `docs/HARNESS_DECLINED.md`. Detail in `kit/harness-builder.md`.
- New `kit/`: Claude Code hooks (`guard.py`, `session_start.py`), git hooks (`commit-msg`, `pre-commit`), `start-brief`, `wrap-check`, `precommit-check` in PowerShell and sh, optional `handoff-check`, and tests (PowerShell, Python, bash).
- README: updated rule table, enforcement table, honest field notes for v2.
- Bootstrap handles damaged markers (found by a dry run on a real repo whose `BEGIN` line was missing): END without BEGIN is replaced from the `## Agent Rules` heading to END; BEGIN without END or a bare heading makes the agent stop and ask; no second block is ever appended. Covered by `kit/tests/test_rules_block.py`.

## v1.0.1 - 2026-10-03
- README field notes: v1 now applied to all three repos (homelab via `CLAUDE.md`, since `AGENTS.md` is a symlink there). `RULES.md` unchanged, so existing SHA pins stay valid.

## v1.0.0 - 2026-10-03

- Initial release of the ruleset (`RULES.md`, marker version `v1`).
- Part A bootstrap: analyze first, approval before writing, merge without overwrite, ops-log migration (keep / move / merge).
- Part B rules block: git sync check, approval gate, delegation without polling, live ops log with stale-lock rule, safety list, trust boundary, subagent inheritance, parallel-agent worktrees.
- Part C ops log template.
- README, MIT license, this changelog.
