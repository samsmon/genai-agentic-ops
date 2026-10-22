#!/bin/bash
# Tests for agentic-sync.sh (hidden mode). Run: bash kit/tests/sync.tests.sh   (needs git; uses temporary repositories)
KIT=$(cd "$(dirname "$0")/.." && pwd)
SYNC="$KIT/scripts/agentic-sync.sh"
BASE=$(mktemp -d)
trap 'rm -rf "$BASE"' EXIT
export GIT_AUTHOR_NAME=tester GIT_AUTHOR_EMAIL=t@example.test GIT_COMMITTER_NAME=tester GIT_COMMITTER_EMAIL=t@example.test
fail=0
OUT=''; CODE=0
expect() { if [ "$2" = 0 ]; then echo "ok   $1"; else echo "FAIL $1"; fail=$((fail + 1)); fi; }
has() { printf '%s\n' "$OUT" | grep -Eq -- "$1"; }
g() { git -C "$1" "${@:2}" >/dev/null 2>&1; }
sync() { local d=$1; shift; OUT=$(cd "$d" && sh "$SYNC" "$@" 2>&1); CODE=$?; }

# a project: bare origin + clone with two committed files and a set of agentic files in the working tree
mkproject() {  # $1 = name; sets BARE, C1
  local n=$1
  BARE=$BASE/$n.git; C1=$BASE/$n
  git init --bare -q "$BARE"; git -C "$BARE" symbolic-ref HEAD refs/heads/main
  git clone -q "$BARE" "$C1" 2>/dev/null; git -C "$C1" symbolic-ref HEAD refs/heads/main
  git -C "$C1" config user.name tester; git -C "$C1" config user.email t@example.test
  mkdir -p "$C1/src"
  echo 'hello' > "$C1/README.md"; echo 'code' > "$C1/src/a.txt"
  g "$C1" add -A; g "$C1" commit -q -m 'chore: init'; g "$C1" push -q -u origin main
  mkdir -p "$C1/docs" "$C1/.claude" "$C1/scripts/agentic-ops" "$C1/.githooks"
  echo 'rules v1' > "$C1/AGENTS.md"; echo '@AGENTS.md' > "$C1/CLAUDE.md"
  echo 'ops' > "$C1/docs/CURRENT_OPS.md"; echo '{}' > "$C1/.claude/settings.json"
  echo 'x' > "$C1/scripts/agentic-ops/tool.sh"; echo '#!/bin/sh' > "$C1/.githooks/pre-commit"
}
wrapc() { OUT=$(sh "$KIT/scripts/wrap-check.sh" --root "$1" --agent claude-code --today 2026-01-01 "${@:2}" 2>&1); }
project_clean() { [ -z "$(git -C "$1" status --porcelain)" ]; }

# ---- first device
mkproject p1
sync "$C1" init
[ $CODE = 0 ] && has 'ready'; expect 'init: first device -> exit 0, ready' $?
[ -f "$C1/.agentic-files" ] && [ -d "$C1/.git/agentic" ]; expect 'init: list file and overlay git dir created' $?
project_clean "$C1"; expect 'init: project git status stays clean (files ignored via .git/info/exclude)' $?
grep -q 'BEGIN agentic-ops' "$C1/.git/info/exclude" && ! grep -q 'agentic' "$C1/.gitignore" 2>/dev/null; expect 'init: ignore lives in info/exclude, no .gitignore entry' $?
[ "$(git -C "$C1" config --get core.hooksPath)" = '.githooks' ]; expect 'init: core.hooksPath set because .githooks exists' $?
sync "$C1" init
[ $CODE = 0 ]; expect 'init: running it twice is safe' $?
n=$(grep -c 'BEGIN agentic-ops' "$C1/.git/info/exclude"); [ "$n" = 1 ]; expect 'init: exclude block written once' $?

sync "$C1" status --brief
has 'uncommitted=[1-9]'; expect 'status --brief: new agentic files reported as uncommitted' $?
sync "$C1" commit -m 'chore: add agentic files'
[ $CODE = 0 ] && has 'Committed'; expect 'commit: valid Conventional Commits message accepted' $?
sync "$C1" commit -m 'Update stuff'
[ $CODE = 1 ]; expect 'commit: non-conforming message rejected' $?
sync "$C1" commit -m '[claude] chore: add rules'
[ $CODE = 1 ]; expect 'commit: bracket prefix rejected' $?
echo 'rules v2' > "$C1/AGENTS.md"
sync "$C1" commit -m $'docs: update rules\n\nCo-Authored-By: Someone <a@b.c>'
[ $CODE = 1 ]; expect 'commit: agent attribution trailer rejected' $?
OUT=$(cd "$C1" && GIT_AUTHOR_NAME=Claude GIT_AUTHOR_EMAIL=noreply@anthropic.com sh "$SYNC" commit -m 'docs: update rules' 2>&1); CODE=$?
[ $CODE = 1 ]; expect 'commit: agent identity rejected' $?
project_clean "$C1"; expect 'project status still clean after editing an agentic file' $?
sync "$C1" commit -m 'docs: update rules'
[ $CODE = 0 ]; expect 'commit: second commit with the edit' $?
wrapc "$C1"
has 'FAIL +OVERLAY: [0-9]+ overlay commit'; expect 'wrap-check: unpushed overlay commits -> FAIL' $?
wrapc "$C1" --git-policy user-only-git
has 'OK +OVERLAY: user-only-git'; expect 'wrap-check: user-only-git -> overlay state is information' $?
sync "$C1" commit
[ $CODE = 0 ] && has 'Nothing to commit'; expect 'commit: nothing changed -> nothing to commit' $?
sync "$C1" push
[ $CODE = 0 ] && has 'Pushed'; expect 'push: overlay branch pushed' $?
git -C "$BARE" show-ref --verify -q refs/heads/agentic-ops; expect 'push: remote has the agentic-ops branch' $?
wrapc "$C1"
has 'OK +OVERLAY: clean and pushed'; expect 'wrap-check: committed and pushed overlay -> OK' $?
[ -z "$(git -C "$BARE" ls-tree -r main --name-only | grep -E 'AGENTS|CLAUDE|CURRENT_OPS|\.claude|\.githooks|agentic')" ]; expect 'project branch main on the remote holds no agentic file' $?
[ -z "$(git -C "$C1" log main --name-only --format= | grep -E 'AGENTS|CLAUDE|CURRENT_OPS|\.claude|\.githooks|agentic')" ]; expect 'project history has no agentic file' $?
git -C "$BARE" ls-tree -r agentic-ops --name-only | grep -q '^AGENTS.md$'; expect 'overlay branch holds AGENTS.md' $?
git -C "$BARE" ls-tree -r agentic-ops --name-only | grep -q '^src/a.txt$'; r=$?; [ $r != 0 ]; expect 'overlay branch holds only listed files, not project code' $?

# ---- second device
C2=$BASE/p1-device2
git clone -q "$BARE" "$C2" 2>/dev/null; git -C "$C2" config user.name tester; git -C "$C2" config user.email t@example.test
[ ! -e "$C2/AGENTS.md" ]; expect 'device 2: a plain clone has no agentic files' $?
sync "$C2" init
[ $CODE = 0 ] && has 'Restored'; expect 'device 2: init restores from the overlay' $?
[ "$(cat "$C2/AGENTS.md")" = 'rules v2' ] && [ -f "$C2/.claude/settings.json" ] && [ -f "$C2/scripts/agentic-ops/tool.sh" ]; expect 'device 2: files restored with the latest content' $?
project_clean "$C2"; expect 'device 2: project status clean after restore' $?
echo 'rules v3' > "$C1/AGENTS.md"
wrapc "$C1"
has 'FAIL +OVERLAY: [0-9]+ agentic file\(s\) not committed'; expect 'wrap-check: uncommitted agentic file -> FAIL' $?
sync "$C1" commit -m 'docs: rules v3'; sync "$C1" push
sync "$C2" pull
[ $CODE = 0 ] && [ "$(cat "$C2/AGENTS.md")" = 'rules v3' ]; expect 'device 2: pull fast-forwards and updates the file' $?
sync "$C2" pull
[ $CODE = 0 ] && has 'up to date'; expect 'device 2: pull again -> up to date' $?

# ---- diverged: no automatic merge, no force
echo 'from c1' > "$C1/docs/CURRENT_OPS.md"; sync "$C1" commit -m 'chore(ops): c1 row'; sync "$C1" push
echo 'from c2' > "$C2/docs/CURRENT_OPS.md"; sync "$C2" commit -m 'chore(ops): c2 row'
sync "$C2" push
[ $CODE = 5 ]; expect 'push: remote has newer commits -> exit 5, not forced' $?
sync "$C2" pull
[ $CODE = 5 ] && has 'diverged'; expect 'pull: diverged -> exit 5, asks the user' $?
[ "$(cat "$C2/docs/CURRENT_OPS.md")" = 'from c2' ]; expect 'pull: diverged leaves local file untouched' $?
sync "$C2" status --brief
has 'ahead=1'; expect 'status --brief: ahead count' $?
OUT=$(sh "$KIT/scripts/start-brief.sh" "$C2" 2>&1)
has '\[OVERLAY\]' && has 'OVERLAY: agentic-ops uncommitted=[0-9]+ ahead=1'; expect 'start-brief: [OVERLAY] section shown once the overlay exists' $?

# ---- local file differs from the overlay copy
C3=$BASE/p1-device3
git clone -q "$BARE" "$C3" 2>/dev/null; git -C "$C3" config user.name tester; git -C "$C3" config user.email t@example.test
echo 'my own rules' > "$C3/AGENTS.md"
sync "$C3" init
[ $CODE = 4 ] && has 'AGENTS.md'; expect 'init: differing local file -> exit 4, listed' $?
[ "$(cat "$C3/AGENTS.md")" = 'my own rules' ]; expect 'init: differing local file not touched' $?
sync "$C3" init --overwrite
[ $CODE = 0 ] && [ "$(cat "$C3/AGENTS.md")" = 'rules v3' ] && ls -d "$C3"/.git/agentic/backup-* >/dev/null 2>&1; expect 'init --overwrite: replaced and backed up' $?
[ "$(cat "$C3"/.git/agentic/backup-*/AGENTS.md)" = 'my own rules' ]; expect 'init --overwrite: backup holds the old content' $?

# ---- agentic files already tracked in the project
mkproject p2
g "$C1" add AGENTS.md; g "$C1" commit -q -m 'docs: add rules'
sync "$C1" init
[ $CODE = 3 ] && has 'AGENTS.md'; expect 'init: tracked in the project history -> exit 3' $?
[ ! -d "$C1/.git/agentic" ]; expect 'init: nothing created when it stops with exit 3' $?
! grep -q 'agentic-ops' "$C1/.git/info/exclude" 2>/dev/null; expect 'init: exclude untouched when it stops with exit 3' $?

# ---- separate overlay remote (private repo)
mkproject p3
OV=$BASE/p3-overlay.git; git init --bare -q "$OV"
sync "$C1" init --remote "$OV"
[ $CODE = 0 ]; expect 'separate remote: init ok' $?
sync "$C1" commit -m 'chore: add agentic files'; sync "$C1" push
git -C "$OV" show-ref --verify -q refs/heads/agentic-ops; expect 'separate remote: overlay branch lands in the overlay repo' $?
! git -C "$BARE" show-ref --verify -q refs/heads/agentic-ops; expect 'separate remote: project remote has no overlay branch' $?
C4=$BASE/p3-device2
git clone -q "$BARE" "$C4" 2>/dev/null
sync "$C4" init --remote "$OV"
[ $CODE = 0 ] && [ "$(cat "$C4/AGENTS.md")" = 'rules v1' ]; expect 'separate remote: second device restores from the overlay repo' $?

# ---- unreachable remote, local only, no remote
mkproject p4
sync "$C1" init --remote "$BASE/does-not-exist.git"
[ $CODE = 6 ]; expect 'unreachable overlay remote -> exit 6' $?
sync "$C1" init --remote "$BASE/does-not-exist.git" --local-only
[ $CODE = 0 ]; expect 'init --local-only works without the remote' $?
sync "$C1" push
[ $CODE != 0 ]; expect 'push to an unreachable remote fails (exit nonzero)' $?
BARE2=$BASE/p5-none; mkdir -p "$BARE2"; git init -q "$BARE2"; echo 'rules' > "$BARE2/AGENTS.md"
sync "$BARE2" init
[ $CODE = 0 ]; expect 'init: project without any remote works' $?
sync "$BARE2" commit -m 'chore: add agentic files'
[ $CODE = 0 ]; expect 'commit: project without any remote works' $?
sync "$BARE2" push
[ $CODE = 2 ]; expect 'push: no overlay remote -> exit 2 with a hint' $?

# ---- not initialised, usage
mkproject p6
sync "$C1" pull
[ $CODE = 2 ]; expect 'pull before init -> exit 2' $?
OUT=$(sh "$KIT/scripts/start-brief.sh" "$C1" 2>&1)
! has '\[OVERLAY\]'; expect 'start-brief: no [OVERLAY] section before init' $?
sync "$C1" status --brief
has 'not initialised'; expect 'status --brief before init -> not initialised' $?
sync "$C1" bogus
[ $CODE = 2 ]; expect 'unknown command -> usage, exit 2' $?

[ $fail = 0 ] && echo 'ALL TESTS PASSED' || echo "$fail FAILED"
[ $fail = 0 ]
