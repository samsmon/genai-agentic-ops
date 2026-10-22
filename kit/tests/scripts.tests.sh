#!/bin/bash
# Tests for the sh versions: start-brief.sh, wrap-check.sh, handoff-check.sh, precommit-check.sh, commit-msg.
# Run: bash kit/tests/scripts.tests.sh   (needs git; uses temporary repositories)
KIT=$(cd "$(dirname "$0")/.." && pwd)
BASE=$(mktemp -d)
trap 'rm -rf "$BASE"' EXIT
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
fail=0
OUT=''; CODE=0
expect() { if [ "$2" = 0 ]; then echo "ok   $1"; else echo "FAIL $1"; fail=$((fail + 1)); fi; }
has() { printf '%s\n' "$OUT" | grep -Eq -- "$1"; }
hasnt() { ! has "$1"; }
g() { git -C "$1" "${@:2}" >/dev/null 2>&1; }
HDR=$'| Timestamp | Agent | ID | Target | Status | Task |\n|---|---|---|---|---|---|'
row() { printf '| %s | %s | main | x | %s | %s |\n' "$1" "${4:-claude-code}" "$2" "$3"; }

new_env() {  # $1 = extra rows for the main table
  rm -rf "$BASE/w"; mkdir -p "$BASE/w"
  BARE=$BASE/w/bare.git; C1=$BASE/w/c1; C2=$BASE/w/c2
  git init --bare -q "$BARE"; git -C "$BARE" symbolic-ref HEAD refs/heads/main
  git clone -q "$BARE" "$C1" 2>/dev/null; git -C "$C1" symbolic-ref HEAD refs/heads/main
  mkdir -p "$C1/docs"
  printf '# NOW\nstate-body\n' > "$C1/NOW.md"
  printf '# OPS\n%s\n%s## Archive\n%s\n| 2026-01-01 00:00 | a | m | x | done | archived-row |\n' "$HDR" "$1" "$HDR" > "$C1/docs/CURRENT_OPS.md"
  g "$C1" add -A; g "$C1" commit -q -m init; g "$C1" push -q -u origin main
  git clone -q "$BARE" "$C2" 2>/dev/null
}
commit_in() { echo "$2" > "$1/$2"; g "$1" add -A; g "$1" commit -q -m "$2"; }
brief() { OUT=$(sh "$KIT/scripts/start-brief.sh" "$1" 2>&1); CODE=$?; }

# ---- start-brief.sh
new_env; brief "$C1"
[ $CODE = 0 ] && has SYNC_OK; expect 'start-brief: in sync -> SYNC_OK, exit 0' $?
has 'state-body'; expect 'start-brief: state file shown' $?
has 'NOT ACTIVE'; expect 'start-brief: hook not active reported' $?
g "$C1" config core.hooksPath .githooks; brief "$C1"
has 'core.hooksPath=.githooks OK'; expect 'start-brief: hook active -> OK' $?
new_env; commit_in "$C2" b.txt; g "$C2" push -q; brief "$C1"
[ $CODE = 0 ] && has BEHIND_CLEAN; expect 'start-brief: behind and clean -> BEHIND_CLEAN' $?
new_env; commit_in "$C1" a.txt; brief "$C1"
[ $CODE = 2 ] && has 'STOP:ahead'; expect 'start-brief: ahead -> STOP:ahead, exit 2' $?
new_env; commit_in "$C2" b.txt; g "$C2" push -q; commit_in "$C1" a.txt; brief "$C1"
[ $CODE = 2 ] && has 'STOP:diverged'; expect 'start-brief: diverged -> exit 2' $?
new_env; echo changed >> "$C1/NOW.md"; brief "$C1"
[ $CODE = 2 ] && has 'STOP:dirty'; expect 'start-brief: tracked change -> STOP:dirty' $?
new_env; echo u > "$C1/new.txt"; brief "$C1"
[ $CODE = 0 ] && has SYNC_OK && has 'new\.txt'; expect 'start-brief: untracked only -> SYNC_OK, noted' $?
rows="$(row '2026-10-11 10:00' running task-running)
$(row '2026-10-11 09:00' done task-done)
$(row '2026-10-11 08:00' blocked task-blocked)
"
new_env "$rows"; brief "$C1"
has task-running && has task-blocked && hasnt task-done && hasnt archived-row; expect 'start-brief: OPS shows running/blocked only' $?
new_env "$(row "$(date -d '3 hours ago' '+%F %H:%M' 2>/dev/null || date -v-3H '+%F %H:%M')" running old-one)
"; brief "$C1"
has 'old-one.*<<STALE>>'; expect 'start-brief: running over 2 h -> STALE' $?
new_env "$(row "$(date '+%F %H:%M')" running fresh-one)
"; brief "$C1"
has fresh-one && hasnt STALE; expect 'start-brief: fresh row -> no STALE' $?
new_env "$(row sometime running odd-one)
"; brief "$C1"
has 'odd-one.*<<TIMESTAMP\?>>'; expect 'start-brief: bad timestamp -> TIMESTAMP?' $?
new_env "$(row '2026-10-11 10:00' Running upper-case)
"; brief "$C1"
has upper-case; expect 'start-brief: capitalised Running still shown' $?
new_env; brief "$C1"
has '\(none\)'; expect 'start-brief: empty -> (none)' $?
new_env; row '2026-10-11 10:00' running hidden-in-archive >> "$C1/docs/CURRENT_OPS.md"; brief "$C1"
has 'hidden-in-archive.*<<IN-ARCHIVE>>'; expect 'start-brief: running under Archive flagged' $?
new_env; rm "$C1/docs/CURRENT_OPS.md"; brief "$C1"
[ $CODE = 2 ] && has 'CURRENT_OPS\.md MISSING'; expect 'start-brief: log missing -> exit 2' $?
new_env; rm -rf "$BARE"; brief "$C1"
[ $CODE = 2 ] && has 'STOP:fetch' && has state-body; expect 'start-brief: fetch failure -> exit 2, sections still printed' $?

# ---- wrap-check.sh (installed layout: copied next to handoff-check.sh when needed)
INST=$BASE/inst
install_scripts() { rm -rf "$INST"; mkdir -p "$INST"; cp "$KIT/scripts/wrap-check.sh" "$INST/"; [ "$1" = handoff ] && cp "$KIT/handoff/handoff-check.sh" "$INST/"; }
wrap() { OUT=$(sh "$INST/wrap-check.sh" --root "$1" --agent claude-code --today 2026-10-11 "${@:2}" 2>&1); CODE=$?; }
install_scripts
new_env; wrap "$C1"
[ $CODE = 0 ] && has '\[WRAP\] 0 failed'; expect 'wrap-check: all good -> exit 0' $?
new_env "$(row '2026-10-11 10:00' running t)
"; wrap "$C1"
[ $CODE = 1 ] && has 'FAIL.*OPS'; expect 'wrap-check: own running row -> FAIL' $?
new_env "$(row '2026-10-11 10:00' Running t)
"; wrap "$C1"
[ $CODE = 1 ]; expect 'wrap-check: capitalised Running still FAIL' $?
new_env "$(row '2026-10-11 10:00' running t gemini)
"; wrap "$C1"
[ $CODE = 0 ]; expect "wrap-check: another agent's running row -> pass" $?
six=''; for i in 1 2 3 4 5 6; do six="$six$(row '2026-10-11 10:00' done t)
"; done
new_env "$six"; wrap "$C1"
[ $CODE = 1 ] && has 'FAIL.*OPS'; expect 'wrap-check: 6 finished rows -> FAIL' $?
five=''; for i in 1 2 3 4 5; do five="$five$(row '2026-10-11 10:00' done t)
"; done
new_env "$five"; wrap "$C1"
[ $CODE = 0 ]; expect 'wrap-check: 5 finished rows -> pass' $?
new_env; row '2026-10-11 10:00' running t >> "$C1/docs/CURRENT_OPS.md"; wrap "$C1"
[ $CODE = 1 ]; expect 'wrap-check: own running row under Archive -> FAIL' $?
new_env; commit_in "$C1" z.txt; wrap "$C1"
[ $CODE = 1 ] && has 'FAIL.*GIT'; expect 'wrap-check: unpushed commit -> FAIL git' $?
wrap "$C1" --git-policy user-only-git
[ $CODE = 0 ] && has 'user-only-git'; expect 'wrap-check: unpushed under user-only-git -> pass' $?
new_env; echo edit >> "$C1/docs/CURRENT_OPS.md"; wrap "$C1"
[ $CODE = 1 ] && has 'FAIL.*GIT'; expect 'wrap-check: uncommitted tracked change -> FAIL git' $?
new_env; mkdir "$C1/other"; echo a > "$C1/other/doc.txt"; g "$C1" add -A; g "$C1" commit -q -m o; g "$C1" push -q; echo more >> "$C1/other/doc.txt"
wrap "$C1"
[ $CODE = 1 ] && has 'FAIL.*GIT.*other/doc\.txt'; expect 'wrap-check: other-session change -> FAIL naming the file' $?
wrap "$C1" --ignore 'other/*'
[ $CODE = 0 ]; expect 'wrap-check: --ignore pattern -> pass' $?
wrap "$C1" --ignore 'x/*,other/*'
[ $CODE = 0 ]; expect 'wrap-check: --ignore comma-separated -> pass' $?
new_env; install_scripts handoff; wrap "$C1"
[ $CODE = 1 ] && has 'FAIL.*STATE' && has 'FAIL.*LOG'; expect 'wrap-check: handoff installed, no Last update/log -> FAIL' $?

# ---- handoff-check.sh
HC=$BASE/hc
hc_env() {  # $1 = Last update date, $2 = 1 to write today's log line
  rm -rf "$HC"; mkdir -p "$HC/log"
  printf '# NOW\n\n**Last update:** %s by claude-code\n\n## Next step\n- x\n' "${1:-2026-10-11}" > "$HC/NOW.md"
  { echo '# Log'; [ "${2:-1}" = 1 ] && echo '- 2026-10-11 [claude-code] x: summary'; } > "$HC/log/2026-10.md"
}
add_disc() {  # $1 name, $2 reviewed list, $3 status, $4 1 if listed in NOW.md
  mkdir -p "$HC/projects/x/discussion"
  printf -- '---\ndate: 2026-10-11\nstatus: %s\nreviewed_by: %s\n---\nbody\n' "${3:-done}" "${2:-[]}" > "$HC/projects/x/discussion/$1"
  [ "${4:-1}" = 1 ] && printf '\n## Awaiting review\n- projects/x/discussion/%s (by claude-code)\n' "$1" >> "$HC/NOW.md"
}
hcheck() { OUT=$(sh "$KIT/handoff/handoff-check.sh" --root "$HC" --agent "${1:-claude-code}" --today 2026-10-11 2>&1); CODE=$?; }
hc_env; hcheck
[ $CODE = 0 ] && has '\[HANDOFF\] 0 failed'; expect 'handoff: all good -> exit 0' $?
hc_env 2026-10-09; hcheck
[ $CODE = 1 ] && has 'FAIL.*STATE'; expect 'handoff: stale Last update -> FAIL' $?
hc_env; hcheck gemini
[ $CODE = 1 ] && has 'FAIL.*STATE' && has 'FAIL.*LOG'; expect 'handoff: other agent -> FAIL STATE and LOG' $?
hc_env 2026-10-11 0; hcheck
[ $CODE = 1 ] && has 'FAIL.*LOG'; expect 'handoff: no log line -> FAIL' $?
hc_env; add_disc a.md '[]' done 1; hcheck
[ $CODE = 0 ] && has 'OK.*REVIEW'; expect 'handoff: unreviewed and listed -> pass' $?
hc_env; add_disc a.md '[]' done 0; hcheck
[ $CODE = 1 ] && has 'FAIL.*REVIEW'; expect 'handoff: unreviewed but not listed -> FAIL' $?
hc_env; add_disc a.md '[gemini]' done 1; hcheck
[ $CODE = 1 ] && has 'FAIL.*REVIEW'; expect 'handoff: reviewed but still listed -> FAIL' $?
hc_env; add_disc a.md '[gemini]' done 0; hcheck
[ $CODE = 0 ]; expect 'handoff: reviewed and not listed -> pass' $?
hc_env; add_disc a.md '[]' wip 0; hcheck
[ $CODE = 0 ]; expect 'handoff: wip file skipped -> pass' $?

# ---- precommit-check.sh
PC=$BASE/pc
pc_env() { rm -rf "$PC"; mkdir -p "$PC"; git -C "$PC" init -q; }
pc() {  # $1 = file name, $2 = content; stages it and runs the check
  pc_env; printf '%s' "$2" > "$PC/$1"; g "$PC" add -A
  printf '%s\n' "$1" > "$BASE/staged.txt"
  OUT=$(sh "$KIT/scripts/precommit-check.sh" --root "$PC" --staged-file "$BASE/staged.txt" 2>&1); CODE=$?
}
fake="sk-ant-$(printf 'a1%.0s' $(seq 15))"
pc a.md "key $fake"
[ $CODE = 1 ] && has 'possible secret' && ! printf '%s' "$OUT" | grep -Fq "$fake"; expect 'precommit: Anthropic key -> REJECTED, value not shown' $?
pc b.md "id AKIA$(printf 'B2%.0s' $(seq 8))"
[ $CODE = 1 ]; expect 'precommit: AWS access key id -> 1' $?
pc c.md "api_key = $(printf 'Zx9%.0s' $(seq 10))"
[ $CODE = 1 ]; expect 'precommit: long literal api_key -> 1' $?
pc d.md 'plain prose with no secrets'
[ $CODE = 0 ] && [ -z "$OUT" ]; expect 'precommit: plain text -> 0 and silent' $?
pc f.md 'password: abcdefghijklmnopqrstuvwxyzabcdef'
[ $CODE = 0 ]; expect 'precommit: long all-letter value is not a secret -> 0' $?
pc e.md 'token: abc'
[ $CODE = 0 ]; expect 'precommit: short token -> 0' $?
pc video.mp4 x
[ $CODE = 1 ] && has 'large file'; expect 'precommit: media extension -> 1' $?
pc_env; head -c 6291456 /dev/zero > "$PC/big.dat"; g "$PC" add -A; echo big.dat > "$BASE/staged.txt"
OUT=$(sh "$KIT/scripts/precommit-check.sh" --root "$PC" --staged-file "$BASE/staged.txt" 2>&1); CODE=$?
[ $CODE = 1 ]; expect 'precommit: file over 5 MB -> 1' $?
OUT=$(ALLOW_BIG_FILES=1 sh "$KIT/scripts/precommit-check.sh" --root "$PC" --staged-file "$BASE/staged.txt" 2>&1); CODE=$?
[ $CODE = 0 ] && has 'large file'; expect 'precommit: ALLOW_BIG_FILES=1 -> 0' $?
pc_env; mkdir "$PC/private"; printf 'SOME_API_KEY=%s' "$(printf 'q1%.0s' $(seq 20))" > "$PC/private/keys.env"; g "$PC" add -A; echo private/keys.env > "$BASE/staged.txt"
OUT=$(SECRET_SCAN_SKIP='private/*' sh "$KIT/scripts/precommit-check.sh" --root "$PC" --staged-file "$BASE/staged.txt" 2>&1); CODE=$?
[ $CODE = 0 ]; expect 'precommit: SECRET_SCAN_SKIP path -> 0' $?
pc_env; head -c 500 /dev/zero | tr '\0' x > "$PC/AGENTS.md"; echo AGENTS.md > "$BASE/staged.txt"
OUT=$(sh "$KIT/scripts/precommit-check.sh" --root "$PC" --staged-file "$BASE/staged.txt" --max-rules-bytes 100 2>&1); CODE=$?
[ $CODE = 0 ] && has WARNING; expect 'precommit: big rules file -> 0 + WARNING' $?

# ---- commit-msg hook
msg=$BASE/msg
printf 'feat: x\n' > "$msg"; sh "$KIT/githooks/commit-msg" "$msg" >/dev/null 2>&1
expect 'commit-msg: clean message -> pass' $?
printf 'feat: x\n\nCo-Authored-By: Someone <a@b.c>\n' > "$msg"; sh "$KIT/githooks/commit-msg" "$msg" >/dev/null 2>&1
[ $? = 1 ]; expect 'commit-msg: Co-Authored-By -> rejected' $?
ALLOW_AGENT_TRAILER=1 sh "$KIT/githooks/commit-msg" "$msg" >/dev/null 2>&1
expect 'commit-msg: ALLOW_AGENT_TRAILER=1 -> pass' $?
printf 'feat: x\n' > "$msg"
pc_env; (cd "$PC" && GIT_AUTHOR_NAME='Claude' GIT_AUTHOR_EMAIL='noreply@anthropic.com' sh "$KIT/githooks/commit-msg" "$msg" >/dev/null 2>&1)
[ $? = 1 ]; expect 'commit-msg: agent identity -> rejected' $?

[ $fail = 0 ] && echo 'ALL TESTS PASSED' || echo "$fail FAILED"
[ $fail = 0 ]
