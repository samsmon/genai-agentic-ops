#!/bin/bash
# Tests for the sh session tools: status-brief.sh, commit-mine.sh, review-queue.sh, triage-untracked.sh.
# Run: bash kit/tests/session-tools.tests.sh   (needs git; uses temporary repositories)
. "$(dirname "$0")/layout.sh"
BASE=$(mktemp -d)
trap 'rm -rf "$BASE"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
unset STATE_FILE OPS_FILE REVIEW_HEADING STATUS_WIP_GLOBS
fail=0
OUT=''; CODE=0
expect() { if [ "$2" = 0 ]; then echo "ok   $1"; else echo "FAIL $1"; fail=$((fail + 1)); fi; }
has() { printf '%s\n' "$OUT" | grep -Eq -- "$1"; }
hasnt() { ! has "$1"; }
g() { git -C "$1" "${@:2}" >/dev/null 2>&1; }
w() { mkdir -p "$(dirname "$1/$2")"; printf '%s\n' "${3:-x}" > "$1/$2"; }
run() { OUT=$("$@" 2>&1); CODE=$?; }
newrepo() { rm -rf "$BASE/r"; mkdir -p "$BASE/r"; R=$BASE/r; g "$R" init -q; }
hdr='| T | A | ID | Target | Status | Task |
|---|---|---|---|---|---|'

# ================================================================= status-brief.sh
S=$SC/status-brief.sh
newrepo
old=$(date -d '5 hours ago' '+%F %H:%M' 2>/dev/null || date -v-5H '+%F %H:%M'); new=$(date '+%F %H:%M')
mkdir -p "$R/docs" "$R/projects/p/discussion" "$R/projects/_template/discussion"
printf '# OPS\n%s\n| %s | claude | s1 | x | running | task-new |\n| %s | gemini | s2 | y | running | task-stale |\n| %s | codex | s3 | z | done | task-finished |\n## Archive\n| %s | a | m | x | running | archived-row |\n' "$hdr" "$new" "$old" "$new" "$old" > "$R/docs/CURRENT_OPS.md"
printf '# NOW\n\n**Last update:** today\n\n## Last focus\n\n**focus-one:** body\n\n## Next step\n- next-one\n- next-two\n\n## Awaiting review\n- a.md\n- b.md\n' > "$R/NOW.md"
printf -- '---\nstatus: wip\n---\nx\n' > "$R/projects/p/discussion/wip.md"
printf -- '---\nstatus: done\n---\nx\n' > "$R/projects/p/discussion/fin.md"
printf -- '---\nstatus: wip\n---\nx\n' > "$R/projects/_template/discussion/t.md"
g "$R" add -A; g "$R" commit -q -m init
w "$R" stray.txt
run sh "$S" status "$R"
[ $CODE = 0 ]; expect 'status-brief: exit 0' $?
has '\[MODE\] status' && has 'Done / In progress / Next / Blockers'; expect 'status-brief: status mode and four-part format' $?
has task-new && hasnt task-finished && hasnt archived-row; expect 'status-brief: running lock shown, done and archive rows not' $?
has 'task-stale.*<<STALE>>'; expect 'status-brief: lock older than 2 hours is STALE' $?
has 'wip\.md \(wip\)' && hasnt 'fin\.md' && hasnt _template; expect 'status-brief: wip discussion shown, done and template not' $?
has '\[REVIEW\] 2 item\(s\)'; expect 'status-brief: review count under Awaiting review' $?
has 'untracked: 1 file\(s\)'; expect 'status-brief: untracked reported' $?
hasnt '\[RESUME\]'; expect 'status-brief: status mode has no RESUME block' $?
run sh "$S" resume "$R"
has '\[RESUME\]' && has focus-one && has next-one; expect 'status-brief: resume shows focus and next step' $?
echo edit >> "$R/NOW.md"; run sh "$S" status "$R"
has 'tracked: 1 file\(s\) changed'; expect 'status-brief: tracked change reported' $?
git -C "$R" checkout -q NOW.md 2>/dev/null
printf '# S\n\n## Needs a look\n- c.md\n' > "$R/STATE.md"
OUT=$(STATE_FILE=STATE.md REVIEW_HEADING='Needs a look' sh "$S" status "$R" 2>&1)
has '\[REVIEW\] 1 item\(s\) awaiting review in STATE\.md'; expect 'status-brief: STATE_FILE and REVIEW_HEADING from the environment' $?
printf '# NOW\n\n## Belum di-review\n- a.md\n- b.md\n- c.md\n' > "$R/NOW.md"; run sh "$S" status "$R"
has '\[REVIEW\] 3 item\(s\)'; expect 'status-brief: the legacy heading Belum di-review is still accepted' $?
OUT=$(OPS_FILE=docs/OTHER.md sh "$S" status "$R" 2>&1); CODE=$?
[ $CODE = 0 ] && has 'no running/blocked rows' && hasnt task-new; expect 'status-brief: OPS_FILE from the environment (missing file: no rows, no crash)' $?
OUT=$(STATUS_WIP_GLOBS='nowhere/*.md' sh "$S" status "$R" 2>&1)
hasnt 'wip\.md'; expect 'status-brief: STATUS_WIP_GLOBS replaces the default folders' $?
rm "$R/NOW.md"; run sh "$S" resume "$R"
has 'NOW\.md MISSING'; expect 'status-brief: missing state file -> NOW.md MISSING in resume' $?
# hidden mode: files excluded from the project history are still read and not counted as untracked
printf '# NOW\n\n## Awaiting review\n- h.md\n' > "$R/NOW.md"
printf 'NOW.md\ndocs/CURRENT_OPS.md\n' >> "$R/.git/info/exclude"
g "$R" rm -q --cached NOW.md docs/CURRENT_OPS.md; g "$R" commit -q -m untrack
run sh "$S" status "$R"
has 'untracked: 2 file\(s\)'; expect 'status-brief: hidden mode: untracked count excludes the hidden files' $?
has task-new && has '\[REVIEW\] 1 item\(s\)'; expect 'status-brief: hidden mode: the hidden ops log and state file are still read' $?
(cd "$R" && sh "$S" status > "$BASE/o.txt" 2>&1); OUT=$(cat "$BASE/o.txt")
has '\[MODE\] status'; expect 'status-brief: default root is the current repository' $?

# ================================================================= commit-mine.sh
C=$SC/commit-mine.sh
cmenv() {
  rm -rf "$BASE/cm"; mkdir -p "$BASE/cm"
  git init --bare -q "$BASE/cm/bare.git"; git -C "$BASE/cm/bare.git" symbolic-ref HEAD refs/heads/main
  git clone -q "$BASE/cm/bare.git" "$BASE/cm/c1" 2>/dev/null; D=$BASE/cm/c1; g "$D" symbolic-ref HEAD refs/heads/main
  g "$D" config user.name t; g "$D" config user.email t@t
  w "$D" a.txt a; w "$D" sub/b.txt b; w "$D" .github/w.yml w
  g "$D" add -A; g "$D" commit -q -m init; g "$D" push -q -u origin main
  git clone -q "$BASE/cm/bare.git" "$BASE/cm/c2" 2>/dev/null; g "$BASE/cm/c2" config user.name t; g "$BASE/cm/c2" config user.email t@t
}
cmenv
run sh "$C" -m 'feat: x' --root "$D" .
[ $CODE = 1 ] && has 'too broad'; expect 'commit-mine: path "." is refused' $?
run sh "$C" -m 'feat: x' --root "$D" a.txt
[ $CODE = 1 ] && has 'no changes'; expect 'commit-mine: no changes -> exit 1' $?
w "$D" a.txt a2; w "$D" other.txt o
run sh "$C" -m 'feat: x' --dry-run --root "$D" a.txt
[ $CODE = 0 ] && has 'a\.txt' && has DRYRUN && [ "$(git -C "$D" rev-list --count HEAD)" = 1 ]; expect 'commit-mine: dry run shows the stat and commits nothing' $?
g "$D" reset -q
run sh "$C" -m 'feat: x' --dry-run --root "$D" a.txt,other.txt
[ $CODE = 0 ] && has 'a\.txt' && has 'other\.txt'; expect 'commit-mine: comma-separated path list' $?
g "$D" reset -q
(cd "$D" && sh "$C" -m 'feat: x' --dry-run a.txt > "$BASE/o.txt" 2>&1); CODE=$?; OUT=$(cat "$BASE/o.txt")
[ $CODE = 0 ] && has DRYRUN; expect 'commit-mine: runs without --root from inside the repository' $?
g "$D" reset -q
g "$D" add other.txt
run sh "$C" -m 'feat: x' --root "$D" a.txt
[ $CODE = 2 ] && has 'other\.txt' && has 'STOP:' && [ "$(git -C "$D" rev-list --count HEAD)" = 1 ]; expect "commit-mine: staged outside the paths -> STOP exit 2, nothing committed" $?
g "$D" reset -q
w "$D" sub/b.txt b2
run sh "$C" -m 'feat: edit sub

body' --root "$D" ./sub/
[ $CODE = 0 ] && has 'COMMIT:'; expect 'commit-mine: commit of a folder works' $?
[ "$(git -C "$D" show --name-only --format= HEAD | paste -sd, -)" = sub/b.txt ]; expect 'commit-mine: only the files of the path are committed' $?
git -C "$D" status --porcelain | grep -q 'a\.txt'; expect 'commit-mine: other files stay uncommitted' $?
w "$D" .github/w.yml w2
run sh "$C" -m 'ci: edit workflow' --root "$D" ./.github/
[ $CODE = 0 ] && [ "$(git -C "$D" show --name-only --format= HEAD | paste -sd, -)" = .github/w.yml ]; expect 'commit-mine: pitfall: ./.github/ keeps its leading dot' $?
w "$D" .github/w.yml w3
run sh "$C" -m 'ci: edit workflow again' --root "$D" '.github\w.yml'
[ $CODE = 0 ] && [ "$(git -C "$D" show --name-only --format= HEAD | paste -sd, -)" = .github/w.yml ]; expect 'commit-mine: pitfall: .github\w.yml with a backslash keeps its leading dot' $?
run sh "$C" -m 'feat: edit a' --push --root "$D" a.txt
[ $CODE = 0 ] && has 'PUSH: ok'; expect 'commit-mine: --push succeeds' $?
g "$BASE/cm/c2" fetch -q
[ "$(git -C "$BASE/cm/c2" rev-list --count origin/main)" = 5 ]; expect 'commit-mine: the remote received the commit' $?
C2=$BASE/cm/c2; g "$C2" pull -q --ff-only; w "$C2" r.txt r; g "$C2" add -A; g "$C2" commit -q -m r; g "$C2" push -q
w "$D" a.txt a3
run sh "$C" -m 'feat: edit a again' --push --root "$D" a.txt
[ $CODE = 2 ] && has 'new commit' && [ "$(git -C "$D" log -1 --format=%s)" = 'feat: edit a again' ]; expect 'commit-mine: newer remote -> STOP, local commit stays' $?
cmenv; w "$D" a.txt a2
run sh "$C" -m 'feat: x

Co-Authored-By: Bot <b@b>' --push --root "$D" a.txt
[ $CODE = 2 ] && has trailer && [ "$(git -C "$D" rev-list --count origin/main)" = 1 ]; expect 'commit-mine: agent trailer -> push cancelled, remote unchanged' $?
cmenv; w "$D" a.txt a2
OUT=$(GIT_AUTHOR_NAME=Bot GIT_AUTHOR_EMAIL=bot@x sh "$C" -m 'feat: x' --push --root "$D" a.txt 2>&1); CODE=$?
[ $CODE = 2 ] && has identity; expect 'commit-mine: different author identity -> push cancelled' $?
cmenv; printf 'AGENTS.md\n' >> "$D/.git/info/exclude"; w "$D" AGENTS.md rules
run sh "$C" -m 'docs: rules' --root "$D" AGENTS.md
[ $CODE = 1 ] && has 'agentic-sync commit'; expect 'commit-mine: hidden mode: an excluded path points to agentic-sync commit' $?

# ================================================================= review-queue.sh
Q=$SC/review-queue.sh
newrepo
w "$R" projects/p1/discussion/2026-10-01-claude-a.md '---
status: done
reviewed_by: []
---
x'
w "$R" projects/p1/discussion/2026-10-05-gemini-b.md '---
status: wip
reviewed_by: []
---
x'
w "$R" projects/p2/discussion/2026-10-02-claude-c.md '---
status: done
reviewed_by: [gemini]
---
x'
w "$R" research/2026-10-03-claude-d.md 'no front matter'
w "$R" NOW.md '# NOW

## Awaiting review
- projects/p1/discussion/2026-10-01-claude-a.md (by claude) - summary-a
- projects/p1/discussion/2026-10-05-gemini-b.md (by gemini) - summary-b
- projects/p2/discussion/2026-10-02-claude-c.md (by claude) - summary-c
- research/2026-10-03-claude-d.md (by claude) - summary-d
- projects/p3/discussion/2026-10-04-claude-gone.md (by claude) - summary-e
- text without a path

## Next step
- not a queue item.md'
run sh "$Q" "$R"
[ $CODE = 0 ]; expect 'review-queue: exit 0' $?
has '\[QUEUE\] 6 item\(s\)'; expect 'review-queue: counts 6 items' $?
hasnt 'not a queue item'; expect 'review-queue: items outside the review section are not counted' $?
has 'p1 +2'; expect 'review-queue: per project: p1 has two' $?
has 'claude +4'; expect 'review-queue: per agent: claude has 4' $?
has 'NOT-DONE +projects/p1/discussion/2026-10-05'; expect 'review-queue: status wip -> NOT-DONE' $?
has 'ALREADY-REVIEWED +projects/p2'; expect 'review-queue: reviewed_by filled -> ALREADY-REVIEWED' $?
has 'NO-FRONTMATTER +research/2026-10-03'; expect 'review-queue: no front matter -> NO-FRONTMATTER' $?
has 'MISSING +projects/p3'; expect 'review-queue: missing file -> MISSING' $?
has UNPARSED; expect 'review-queue: line without a path -> UNPARSED' $?
hasnt '(NOT-DONE|ALREADY-REVIEWED|NO-FRONTMATTER|MISSING) +projects/p1/discussion/2026-10-01'; expect 'review-queue: a healthy item is not flagged' $?
oldest=$(printf '%s\n' "$OUT" | sed -n '/\[OLDEST\]/,$p')
a=$(printf '%s\n' "$oldest" | grep -n 2026-10-01-claude-a | head -n 1 | cut -d: -f1); b=$(printf '%s\n' "$oldest" | grep -n 2026-10-05-gemini-b | head -n 1 | cut -d: -f1)
[ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]; expect 'review-queue: oldest first: 2026-10-01 before 2026-10-05' $?
w "$R" NOW.md '# NOW

## Belum di-review
- projects/p1/discussion/2026-10-01-claude-a.md (oleh claude) - ringkas'
run sh "$Q" "$R"
has '\[QUEUE\] 1 item\(s\)' && has 'claude +1'; expect 'review-queue: legacy heading Belum di-review and (oleh x) are accepted' $?
w "$R" STATE.md '# S

## Needs a look
- research/2026-10-03-claude-d.md (by x) - d'
OUT=$(STATE_FILE=STATE.md REVIEW_HEADING='Needs a look' sh "$Q" "$R" 2>&1)
has '\[QUEUE\] 1 item\(s\)'; expect 'review-queue: STATE_FILE and REVIEW_HEADING from the environment' $?
w "$R" NOW.md '# NOW

## Awaiting review'
run sh "$Q" "$R"
has '\[QUEUE\] 0 item\(s\)'; expect 'review-queue: empty queue -> 0 items' $?
rm "$R/NOW.md"; run sh "$Q" "$R"
[ $CODE = 0 ] && has 'NOW\.md MISSING'; expect 'review-queue: no state file -> NOW.md MISSING, exit 0' $?

# ================================================================= triage-untracked.sh
T=$SC/triage-untracked.sh
newrepo
printf '# OPS\n| T | A | ID | Target | Status | Task |\n|---|---|---|---|---|---|\n| 2026-10-29 10:00 | claude | sess-a | `work/mine` | running | x |\n| 2026-10-29 10:00 | gemini | sess-b | `work/old` | done | x |\n| 2026-10-29 10:00 | codex | sess-c | `./.config/tool/` | blocked | x |\n## Archive\n' > "$R/docs-ops.md"
mkdir -p "$R/docs"; mv "$R/docs-ops.md" "$R/docs/CURRENT_OPS.md"
w "$R" work/mine/a.py; w "$R" work/mine/b.md; w "$R" work/other/data.json; w "$R" temp_notes.md; w "$R" x.bak
w "$R" .config/tool/one.txt; w "$R" .config/tool/two.txt
head -c 2097152 /dev/zero > "$R/work/other/big.bin"
g "$R" add docs/CURRENT_OPS.md
run sh "$T" "$R"
[ $CODE = 0 ]; expect 'triage-untracked: exit 0' $?
has '\[UNTRACKED\] 8 file\(s\)'; expect 'triage-untracked: counts the untracked files' $?
has 'work/mine.*lock-owner: claude/sess-a'; expect 'triage-untracked: work/mine is marked with the running lock owner' $?
hasnt 'sess-b'; expect 'triage-untracked: a done lock is not an owner' $?
has 'temp \(2\)' && has 'temp_notes\.md' && has 'x\.bak'; expect 'triage-untracked: temp files proposed (temp_ and .bak)' $?
has 'big > 1024 KB \(1\)' && has 'big\.bin'; expect 'triage-untracked: big file flagged' $?
has 'data without a lock owner \(1\)'; expect 'triage-untracked: data without a lock owner proposed' $?
has '\.config/tool.*lock-owner: codex/sess-c'; expect 'triage-untracked: pitfall: a lock target with a leading dot (./.config/tool/) still matches its files' $?
[ -f "$R/temp_notes.md" ] && [ -f "$R/x.bak" ]; expect 'triage-untracked: deletes nothing' $?
printf '| T | A | ID | Target | Status | Task |\n|---|---|---|---|---|---|\n| 2026-10-29 10:00 | zed | sess-z | `work/other` | running | x |\n' > "$R/ops2.md"
OUT=$(OPS_FILE=ops2.md sh "$T" "$R" 2>&1)
has 'work/other.*lock-owner: zed/sess-z'; expect 'triage-untracked: OPS_FILE from the environment' $?
printf 'ops2.md\ntemp_notes.md\n' >> "$R/.git/info/exclude"
run sh "$T" "$R"
has '\[UNTRACKED\] 7 file\(s\)' && hasnt 'temp_notes\.md'; expect 'triage-untracked: hidden mode: excluded files are not counted' $?
run sh "$T" --big-kb 4096 "$R"
hasnt 'big\.bin'; expect 'triage-untracked: --big-kb raises the threshold' $?
rm -rf "$R/x.bak" "$R/work" "$R/.config" "$R/ops2.md" "$R/temp_notes.md"
run sh "$T" "$R"
has '\[UNTRACKED\] 0 file\(s\)'; expect 'triage-untracked: no untracked files -> 0' $?

[ $fail -eq 0 ]
