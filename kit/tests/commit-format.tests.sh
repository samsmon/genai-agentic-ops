#!/bin/bash
# Tests for scripts/commit-msg-check.sh (Conventional Commits + Chris Beams) and its use by githooks/commit-msg.
# Run: bash kit/tests/commit-format.tests.sh   (needs git; uses temporary repositories)
KIT=$(cd "$(dirname "$0")/.." && pwd)
CHK="$KIT/scripts/commit-msg-check.sh"
HOOK="$KIT/githooks/commit-msg"
BASE=$(mktemp -d)
trap 'rm -rf "$BASE"' EXIT
export GIT_AUTHOR_NAME=tester GIT_AUTHOR_EMAIL=t@example.test GIT_COMMITTER_NAME=tester GIT_COMMITTER_EMAIL=t@example.test
fail=0
ERR=''; CODE=0
expect() { if [ "$2" = 0 ]; then echo "ok   $1"; else echo "FAIL $1"; fail=$((fail + 1)); fi; }
chk() { printf '%b' "$1" > "$BASE/m"; ERR=$(sh "$CHK" "$BASE/m" 2>&1 >/dev/null); CODE=$?; }
accept() { chk "$2"; [ $CODE = 0 ]; expect "accept: $1" $?; }
reject() { chk "$2"; [ $CODE = 1 ] && printf '%s' "$ERR" | grep -q -- "$3"; expect "reject: $1" $?; }
warns() { chk "$2"; [ $CODE = 0 ] && printf '%s' "$ERR" | grep -q -- "warning: .*$3"; expect "warn: $1" $?; }

# ---- accepted
accept 'plain type and subject' 'feat: add login\n'
accept 'scope' 'fix(api): handle empty body\n'
accept 'breaking mark' 'feat(auth)!: drop v1 tokens\n'
accept 'body and footers' 'fix: stop double submit\n\nThe form posted twice when the button was\npressed quickly.\n\nBREAKING CHANGE: the old endpoint is gone\nRefs: #12\nCloses: #13\n'
accept 'scope with slash and dot' 'build(deps/dev): bump pytest\n'
accept 'description starting with a digit' 'fix: 404 on missing order\n'
accept 'revert type' 'revert: remove login again\n'
accept 'no trailing newline' 'docs: describe overlay sync'
accept 'CRLF line endings' 'feat: add login\r\n\r\nbody line\r\n'
accept 'comment lines are ignored' 'feat: add login\n# Please enter the commit message\n# lines starting with # are dropped\n'
accept 'leading blank lines' '\n\nfeat: add login\n'
accept 'merge commit exempt' "Merge branch 'feature/login' into main\n"
accept 'revert commit exempt' 'Revert "feat: add login"\n\nThis reverts commit abcdef1.\n'
accept 'fixup exempt' 'fixup! feat: add login\n'
accept 'squash exempt' 'squash! feat: add login\n'
accept 'only comments (empty message)' '# nothing here\n'
accept 'long URL in the body is allowed' 'docs: link the spec\n\nSee https://www.conventionalcommits.org/en/v1.0.0/specification-of-everything-in-one-very-long-url-path\n'

# ---- rejected
reject 'bracket prefix before the type' '[claude] feat: add login\n' 'nothing may come before the type'
reject 'bracket prefix with scope' '[agent] fix(api): x\n' 'nothing may come before the type'
reject 'no type' 'add login\n' 'type(scope): description'
reject 'unknown type' 'wip: add login\n' 'unknown type "wip"'
reject 'capitalised type' 'Feat: add login\n' 'unknown type "Feat"'
reject 'missing space after colon' 'feat:add login\n' 'single space is required'
reject 'two spaces after colon' 'feat:  add login\n' 'exactly one space'
reject 'empty description' 'feat: \n' 'empty'
reject 'capitalised description' 'feat: Add login\n' 'lowercase'
reject 'trailing period' 'feat: add login.\n' 'period'
reject 'subject over 72 characters' 'feat: add a login screen with a remember me checkbox and a password reset link on it\n' 'hard limit is 72'
reject 'no blank line before the body' 'feat: add login\nbody starts right away\n' 'blank line'
reject 'empty BREAKING CHANGE' 'feat: add login\n\nBREAKING CHANGE:\n' 'BREAKING CHANGE needs a description'
reject 'wrong scope parentheses' 'feat(): add login\n' 'type(scope)'
reject 'free text' 'Update stuff\n' 'type(scope): description'

# ---- warnings only (exit 0)
warns 'subject over 50 characters' 'feat: add a login screen with a remember me checkbox\n' 'aim for 50'
warns 'past tense' 'feat: added login\n' 'imperative'
warns '-ing form' 'fix: fixing the login\n' 'imperative'
warns 'third person' 'fix: fixes the login\n' 'imperative'
warns 'body line over 72 columns' 'fix: stop double submit\n\nThis line is much longer than seventy-two columns and it keeps going on and on and on.\n' 'wrap'
chk 'feat: add login\n'; [ -z "$ERR" ]; expect 'clean message prints nothing' $?

# ---- configuration
printf 'ops: rotate rows\n' > "$BASE/m"
sh "$CHK" "$BASE/m" >/dev/null 2>&1; [ $? = 1 ]; expect 'custom type rejected by default' $?
COMMIT_EXTRA_TYPES='ops deps' sh "$CHK" "$BASE/m" >/dev/null 2>&1; expect 'COMMIT_EXTRA_TYPES adds a type' $?
mkdir -p "$BASE/r" && git -C "$BASE/r" init -q && git -C "$BASE/r" config agentic.commitTypes 'ops'
(cd "$BASE/r" && sh "$CHK" "$BASE/m" >/dev/null 2>&1); expect 'git config agentic.commitTypes adds a type' $?
printf 'Update stuff\n' > "$BASE/m"
SKIP_COMMIT_FORMAT=1 sh "$CHK" "$BASE/m" >/dev/null 2>&1; expect 'SKIP_COMMIT_FORMAT=1 skips the check' $?
sh "$CHK" >/dev/null 2>&1; [ $? = 2 ]; expect 'usage error without a file -> exit 2' $?
sh "$CHK" "$BASE/missing" >/dev/null 2>&1; [ $? = 2 ]; expect 'usage error with a missing file -> exit 2' $?

# ---- the git hook: attribution checks stay, format check added
export AGENTIC_OPS_DIR="$KIT/scripts"
hook() { printf '%b' "$1" > "$BASE/m"; sh "$HOOK" "$BASE/m" >/dev/null 2>&1; }
hook 'feat: add login\n'; expect 'hook: valid message passes' $?
hook 'Update stuff\n'; [ $? = 1 ]; expect 'hook: format violation rejected' $?
hook 'feat: add login\n\nCo-Authored-By: Someone <a@b.c>\n'; [ $? = 1 ]; expect 'hook: Co-Authored-By still rejected' $?
hook 'feat: add login\n\nGenerated with a tool\n'; [ $? = 1 ]; expect 'hook: Generated with still rejected' $?
hook 'feat: add login\n\nSigned-off-by: Someone <a@b.c>\n'; [ $? = 1 ]; expect 'hook: Signed-off-by still rejected' $?
ALLOW_AGENT_TRAILER=1 hook 'feat: add login\n\nCo-Authored-By: Someone <a@b.c>\n'; expect 'hook: ALLOW_AGENT_TRAILER=1 lets the trailer through' $?
ALLOW_AGENT_TRAILER=1 hook 'Update stuff\n'; [ $? = 1 ]; expect 'hook: ALLOW_AGENT_TRAILER=1 does not skip the format check' $?
SKIP_COMMIT_FORMAT=1 hook 'Update stuff\n'; expect 'hook: SKIP_COMMIT_FORMAT=1 skips the format check' $?
SKIP_COMMIT_FORMAT=1 hook 'Update stuff\n\nCo-Authored-By: Someone <a@b.c>\n'; [ $? = 1 ]; expect 'hook: SKIP_COMMIT_FORMAT=1 does not skip the trailer check' $?
printf 'feat: add login\n' > "$BASE/m"
(GIT_AUTHOR_NAME=Claude GIT_AUTHOR_EMAIL=noreply@anthropic.com sh "$HOOK" "$BASE/m" >/dev/null 2>&1); [ $? = 1 ]; expect 'hook: agent identity still rejected' $?
(AGENTIC_OPS_DIR="$BASE/nowhere" sh "$HOOK" "$BASE/m" 2>&1 >/dev/null | grep -q 'not found'); expect 'hook: missing checker -> warning, not a failure' $?
(AGENTIC_OPS_DIR="$BASE/nowhere" sh "$HOOK" "$BASE/m" >/dev/null 2>&1); expect 'hook: missing checker still exits 0' $?

# ---- through real git
R=$BASE/repo; git init -q "$R"; git -C "$R" config user.name tester; git -C "$R" config user.email t@example.test
git -C "$R" config core.hooksPath "$KIT/githooks"; echo a > "$R/a"; git -C "$R" add a
git -C "$R" commit -q -m 'Update stuff' >/dev/null 2>&1; [ $? != 0 ]; expect 'git commit: bad message is refused' $?
git -C "$R" commit -q -m 'feat: add a' >/dev/null 2>&1; expect 'git commit: good message is accepted' $?
echo b > "$R/b"; git -C "$R" add b
git -C "$R" commit -q -m 'fix: add b' -m 'Co-Authored-By: Someone <a@b.c>' >/dev/null 2>&1; [ $? != 0 ]; expect 'git commit: trailer is refused' $?
git -C "$R" commit -q -m $'fix: add b\n\nIt was missing.' >/dev/null 2>&1; expect 'git commit: subject and body accepted' $?
echo c > "$R/c"; git -C "$R" add c
git -C "$R" commit -q -m 'wip: add c' >/dev/null 2>&1; [ $? != 0 ]; expect 'git commit: unknown type refused' $?
git -C "$R" log --format=%s | grep -qx 'feat: add a'; expect 'git log: the accepted commit is in the history' $?

[ $fail = 0 ] && echo 'ALL TESTS PASSED' || echo "$fail FAILED"
[ $fail = 0 ]
