# Harness builder

Rule 12 in `RULES.md` makes the agent **recommend** a harness when work repeats. This file holds the detail. A harness is anything that makes repeated work cheaper or safer next time: a script, a template, a doc, a skill/slash command, a hook.

The agent never builds one unasked. A recommendation is one short block in the closing report; the user approves, declines, or ignores it.

## Triggers

Recommend when at least one is true:

| # | Trigger | Example |
|---|---|---|
| a | The same kind of task is already in the ops log or happened earlier in the session (second time or more) | Third "rename the exported PDFs and move them to `out/`" |
| b | The user says "every time", "usually", "always", "each week" | "Each Monday I want the stale-branch list" |
| c | You just did a deterministic multi-step procedure by hand | Seven commands to rotate a log and update an index |
| d | The same mistake happened again and a machine could have caught it | A secret nearly committed twice |

Do not recommend on a hunch. If you cannot name which trigger fired, say nothing.

## Choosing the type

Pick the lightest type that does the job.

| Type | Use when | Not when | Typical home |
|---|---|---|---|
| Script | Steps are deterministic, no judgment needed | The output needs interpretation each time | `scripts/` |
| Template | A file structure repeats and only the content changes | Structure varies per use | `templates/` or `_template/` |
| Doc / rule | The repeat is missing knowledge, not an action | There is something to execute | `docs/` or the rules file (keep that file small) |
| Skill / slash command | The flow is fixed but needs judgment, or the user wants a one-word trigger | A script alone would do | `.claude/commands/`, `.agent/workflows/`, or the tool's skill folder |
| Hook | The step must never be forgotten and a machine can check it | Only advisory, or the check is slow or flaky | `.claude/hooks/`, `.githooks/` |

Rules of thumb: script before skill, doc before hook, hook only for things that hurt when forgotten. A skill that wraps a script is fine: the script does the work, the skill says when to run it.

## When NOT to build one

- One-off work with no sign it recurs.
- The procedure changes every time; the harness would be stale by the next use.
- Build and maintenance cost is more than the saving over roughly the next five uses.
- An equivalent already exists (grep the repo's `scripts/`, commands and docs first).
- The user already declined the same thing (check `docs/HARNESS_DECLINED.md`).

## Recommendation format

One block, at the end of the task report, at most one per task:

```
Harness suggestion: <what repeats, in one line> | Type: <script|template|doc|skill|hook> | Saves: <est. time or tokens per use> | Effort: <est. to build and test> | Where: <proposed path>
```

Example:

```
Harness suggestion: weekly stale-branch report done by hand 3 times | Type: script | Saves: ~5 min and ~3k tokens per run | Effort: ~20 min incl. test | Where: scripts/stale-branches.sh
```

Estimates are rough and labelled as such. If the saving is not clearly larger than the effort, do not suggest it.

## After the suggestion

- **Approved:** treat it as a normal change. Plan first (rule 1), log it in CURRENT_OPS, delegate if it is long (rule 2), verify with a test or dry run (rule 5). Keep the harness small and put a one-line "how to run" in its header.
- **Declined:** append one line to `docs/HARNESS_DECLINED.md` and do not suggest it again unless the user asks:
  `2026-10-22 | stale-branch report script | not needed, done by CI`
- **Ignored:** do not repeat in the same session. If the trigger fires again in a later session, one more suggestion is fine.

Before suggesting, search the declined file instead of reading it whole: `grep -i "<keyword>" docs/HARNESS_DECLINED.md`.

## Proposal template (optional, for bigger harnesses)

When the harness is big enough to need approval of its design, use this instead of the one-line block:

```
Proposal: <name>
Repeats: <trigger and evidence: which tasks, how often>
Type: <type> and why not a lighter one
Behaviour: <inputs, outputs, side effects>
Safety: <what it must never do; what needs confirmation>
Cost: build <est.>, maintain <est.>; saves <est.> per use
Test: <how it will be verified>
Files: <paths to create or change>
```
