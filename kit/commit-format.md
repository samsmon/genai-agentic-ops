# Commit message format

Every commit message, written by an agent or suggested to the user, follows [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) in English, plus the seven rules from [Chris Beams](https://chris.beams.io/git-commit). The `commit-msg` hook runs `commit-msg-check.sh` and rejects what breaks a hard rule. Both git policies use the same format.

```
type(scope)!: subject

Body: what changed and why, wrapped at 72 columns.

BREAKING CHANGE: what breaks and how to migrate
Refs: #123
```

## Rules

| Rule | Check |
|---|---|
| `type(scope): subject`, one space after the colon. `scope` is optional, `!` before the colon marks a breaking change | Rejected if wrong. Nothing may come before the type, so a prefix such as `[agent]` is rejected |
| Type is one of `feat fix docs style refactor perf test build ci chore revert` | Rejected if unknown. Add project types with `git config agentic.commitTypes "ops deps"` or `COMMIT_EXTRA_TYPES` |
| The description starts with a lowercase letter and has no period at the end | Rejected |
| Imperative mood: "add", not "added" or "adds" | Warning, matched against a short list of common past and third-person verbs |
| Subject (whole first line) of 50 characters or fewer | Warning above 50, rejected above 72 |
| Blank line between subject and body | Rejected if missing |
| Body wrapped at 72 columns, explains what and why, not how | Warning for longer lines, except lines with a URL |
| `BREAKING CHANGE:` footer has a description | Rejected if empty |

Not checked: `Merge ...`, `Revert "..."`, and `fixup!`, `squash!`, `amend!` commits. Lines starting with `#` are ignored (git's own comments).

## Types

| Type | Use for |
|---|---|
| feat | A new feature for the user |
| fix | A bug fix |
| docs | Documentation only |
| style | Formatting, no change in meaning (whitespace, semicolons) |
| refactor | Code change that neither fixes a bug nor adds a feature |
| perf | A change that improves performance |
| test | Adding or correcting tests |
| build | Build system or dependencies |
| ci | CI configuration |
| chore | Maintenance that fits nowhere else |
| revert | Reverting an earlier commit |

## Examples

```
feat(auth): add Google OAuth callback
fix(api)!: return 404 for unknown order ids
docs: describe the overlay sync in the readme
chore(ops): rotate finished rows to the archive file
```

Rejected: `[agent] feat: add login`, `Feat: add login`, `feat: Add login.`, `feat:add login`, `update stuff`.

## Using the checker by hand

```
sh scripts/agentic-ops/commit-msg-check.sh .git/COMMIT_EDITMSG
powershell -NoProfile -Command "sh scripts/agentic-ops/commit-msg-check.sh msg.txt"
```

Exit 0 accepts (warnings go to stderr), exit 1 rejects, exit 2 is a usage error. `SKIP_COMMIT_FORMAT=1` skips the check; it is the user's call, not an agent's. The guard hook denies agent commands that set either variable.
