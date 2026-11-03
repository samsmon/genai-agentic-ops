# Chief and workers: delegating heavy work to a cheaper model

Reference for rule 2 ("Chief and workers") in `RULES.md`. It is not installed by `install.py` and is not in `kit/MANIFEST`. Nothing here is enforced by a hook or a script: the chief follows it because the rule says so. The threshold values have not been tuned on real projects yet.

## Roles

- **Chief**: the session the user talks to. It plans, decides whether to delegate, writes the spec, picks the worker, verifies the result and is the only one that reports to the user. Any agent can be the chief.
- **Worker**: an agent the chief starts for one bounded task, usually on a cheaper model. It works inside the spec, reports `DONE` or `BLOCKED` with evidence, and never approves its own work.

## When to delegate

The default is to do the work yourself. Delegation costs tokens too: the worker starts cold and the chief has to write a spec. It pays off only when the task is big.

| Step | Rule |
|---|---|
| 0 | Questions, small fixes (about 15 lines or less), design decisions, debugging that needs judgment and reviews are never delegated. No estimate needed. |
| 1 | For a task that looks big, read the usage figures if the host exposes them (see "Reading usage"). |
| 2 | Estimate the cost of the task as a percentage of the 5-hour usage window. |
| 3 | Compare it with the threshold below. Above it: delegate. At or below it: do it yourself. |
| 4 | Write one line saying which threshold applied and why, then write the spec. |
| 5 | After the task, read the figures again and note estimated against actual. |

The threshold is elastic, like a scaling policy with two tiers:

| Condition | Threshold |
|---|---|
| Default | 5% of the 5-hour window |
| 5-hour window at 70% used or more, or weekly limit at 80% or more | 2% of the 5-hour window |

When the quota is nearly spent, smaller tasks move to workers. When there is plenty left, the chief keeps more of the work.

### Reading usage

If the host exposes plan limits, read them before and after the task. Observed on 2026-11-03 in the Claude desktop app: the `get_usage` tool of the session-management server returns the percent used (an integer) and the reset time for the 5-hour and weekly windows, and the context window of the session. Other hosts may expose nothing. Percentages are whole numbers, so a change under 1% is invisible.

### Size as a proxy

When no usage figures are available, treat the task as above the threshold if any of these holds:

1. A mechanical edit across about 10 or more files (rename, migration, pattern change).
2. A test or build loop expected to repeat, with long output.
3. A wide read sweep (many files or logs) where only the conclusion is needed.
4. A batch that will run longer than about 2 minutes.
5. Bulk generation (many tests, documents or translations).

### Calibration note

After a delegated task, keep one line in the closing report, for example:

```
2026-11-03 | rename getUser to fetchUser, 25 files | est 8% | actual 1% | worker: cheap tier | verify passed
```

A run of lines like this shows whether the estimates are too high or too low. Adjust the habit, not the thresholds, until there is enough data.

## The spec

```
Goal: <one sentence>
Allowed Files: <explicit list; no reading or editing outside it>
Verify Command: <one command, exit 0 means success>
Evidence required: short diff and the verify output
Rules: follow RULES.md; do not approve your own work; report DONE or BLOCKED
```

Every delegation prompt also points the worker at the project's rules file (rule 7: subagents inherit all rules).

## Verification by the chief

1. Run the verify command yourself. Do not trust the worker's report of it.
2. Run `git diff --stat` and compare the files with `Allowed Files`. A file outside the list fails the check: revert that change, then finish the rest yourself.
3. If something fails, reject once with one concrete fix instruction. If it fails again, take over. No third round.
4. Test green and scope clean: approve at once. No cosmetic review rounds.
5. Record the task in `docs/CURRENT_OPS.md` as `subagent-<purpose>-<n>` (rule 3) and report to the user in a few lines.

## Choosing a worker

| Work | Worker |
|---|---|
| Analysis, reading, summarising | A headless run of another agent CLI in a read-only mode, answer to a file. See `kit/headless-delegation.md`. |
| Editing code | A subagent of the chief's own tool on a cheaper model, which can edit natively. |

Why the split: `kit/headless-delegation.md` records that headless CLI runs were denied file edits because they cannot ask for permission, and that skipping permissions is not acceptable. A narrow allow rule in the other CLI's settings is the only reasonable route to headless writes, and that decision belongs to the user. A worker on another vendor's model also draws on that vendor's quota, not the chief's.

## Examples

Percentages are illustrative.

| Situation | Decision |
|---|---|
| "Why does this regex fail?" | Rule 0: answer directly, no estimate. |
| Rename an API across 25 files, window at 10% used, estimate 8% | Above 5%: delegate. Spec lists the 25 files, verify is the test command. Chief runs the tests and `git diff --stat`, approves. |
| Medium task, estimate 3%, window at 72% used | Tier 2 applies (threshold 2%): delegate. |
| Worker reports `DONE` but the tests fail | One reject with a concrete fix. Still failing: chief takes over. |
| `git diff --stat` shows a file outside `Allowed Files` | Approval refused. Revert the extra change, finish the rest as chief. |
| Chief cannot read usage, task is tests for 12 modules | Size proxy 1 and 5 apply: delegate. No calibration line. |
| Task needs code edits but only a headless read-only CLI is available | Analysis goes to the CLI; edits go to a same-tool subagent or the chief. |

## Limits

- The estimate is a guess. Treat it as a way to avoid obviously wasteful runs, not as a budget.
- Usage figures are whole percentages and exist only on some hosts.
- Enforcement is text. If you want a hard stop, add a hook or a scope-check script; that is a separate change (rule 12).
- The first run of a worker pays a cold-start cost; many tiny delegations cost more than doing the work in place.

## Not verified

- Whether the thresholds fit real projects. They are a starting point.
- Headless write-mode delegation with a narrow allow rule.
- Behaviour on hosts that expose no usage figures beyond the size proxy.
