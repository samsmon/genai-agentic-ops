# Changelog

## v1.0.1 - 2026-10-03
- README field notes: v1 now applied to all three repos (homelab via `CLAUDE.md`, since `AGENTS.md` is a symlink there). `RULES.md` unchanged, so existing SHA pins stay valid.

## v1.0.0 - 2026-10-03

- Initial release of the ruleset (`RULES.md`, marker version `v1`).
- Part A bootstrap: analyze first, approval before writing, merge without overwrite, ops-log migration (keep / move / merge).
- Part B rules block: git sync check, approval gate, delegation without polling, live ops log with stale-lock rule, safety list, trust boundary, subagent inheritance, parallel-agent worktrees.
- Part C ops log template.
- README, MIT license, this changelog.
