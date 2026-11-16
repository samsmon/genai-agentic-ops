# Pull request format

Pull requests are opt-in. Open one only when the user asks for a pull request. Without that request a branch is merged locally, with the method the repository already uses, and pushed as the git policy allows; this holds for repositories with CI too.

When the user does ask for a pull request, everything below applies, so that every pull request looks the same whoever opened it.

## Title

A Conventional Commits subject, the same rules as [commit-format.md](commit-format.md): `type(scope): subject`, lowercase description, no period, 50 characters or fewer (rejected above 72).

## Body

```
## Why
The problem or the goal, in one or two sentences.

## Changes
- What changed, one bullet per area.

## Verification
- Commands run and their results. Say what was not verified.

## Risks and follow-ups
- Optional. What could break, and what is left for later.
```

| Rule | Check |
|---|---|
| `## Why`, `## Changes` and `## Verification` are present and have content | Rejected if missing or empty. A section that holds only the template comment counts as empty |
| No agent attribution: no `Co-Authored-By`, `Signed-off-by`, "Generated with" line or robot emoji | Rejected |
| Title follows the commit subject rules | Rejected if wrong; warning above 50 characters |
| English, like commit messages | Not checked |
| Other sections may be added | Allowed |

## Steps

1. Put the work on a branch. Commit and push as the git policy allows.
2. Write the body to a file and check it: `python scripts/agentic-ops/pr-check.py --title "<title>" --body-file <file>`. `--template` prints the skeleton.
3. Open the pull request with that title and body (`gh pr create --title ... --body-file ...`). Do not use `--fill`.
4. Wait for the checks. Merge only when they pass. If a check fails, say so and stop, also when the same check already fails on the default branch: fix it or let the user decide.
5. Merge the pull request with the method the repository already uses (look at `git log` for merge commits or squashes). Then update the local default branch with `git pull --ff-only`.
6. Deleting the branch is a destructive operation: ask first.

A review comment says what was checked and what is left open. "LGTM" alone is not a review.

## Checking by hand

```
python scripts/agentic-ops/pr-check.py --title "fix(api): return 404 for unknown ids" --body-file body.md
python scripts/agentic-ops/pr-check.py --pr 12
python scripts/agentic-ops/pr-check.py --template
```

Exit 0 passes (warnings may print), exit 1 fails, exit 2 is a usage error. `--pr` needs the GitHub CLI.

The checker only reads text. It does not open, block or merge anything.
