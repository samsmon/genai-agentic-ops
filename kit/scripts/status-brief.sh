#!/bin/sh
# Mid-session status / resume brief (read-only). Answers the one-word messages "status" and "resume".
# Usage: status-brief.sh [status|resume] [root]
#   status  git state, OPS locks, unfinished discussion files, review queue
#   resume  status plus the resume point from the state file
# No fetch: fast and works offline. Writes nothing.
# Env: STATE_FILE (default NOW.md), OPS_FILE (default docs/CURRENT_OPS.md),
#   REVIEW_HEADING (default "Awaiting review"; "Belum di-review" is always accepted too),
#   STATUS_WIP_GLOBS (comma list of folder globs with front matter "status:", default below).
# Works in hidden mode: it reads working-tree files and never needs them tracked in the project history.
MODE=status
case "$1" in status|resume) MODE=$1; shift ;; esac
ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
OPS_FILE="${OPS_FILE:-docs/CURRENT_OPS.md}"
STATE_FILE="${STATE_FILE:-NOW.md}"
REVIEW_HEADING="${REVIEW_HEADING:-Awaiting review}"
WIP_GLOBS="${STATUS_WIP_GLOBS:-projects/*/discussion/*.md,research/*.md,docs/discussion/*.md,docs/research/*.md}"
TAB=$(printf '\t')
G() { git -C "$ROOT" "$@"; }

cut_() { printf '%s\n' "$1" | awk -v n="$2" '{ sub(/\r$/, ""); if (length($0) > n) print substr($0, 1, n) "..."; else print }'; }
epoch() {  # "YYYY-MM-DD HH:MM" (local) -> epoch seconds; empty on failure
  e=$(date -d "$1" +%s 2>/dev/null) && [ -n "$e" ] && { echo "$e"; return; }
  date -j -f '%Y-%m-%d %H:%M' "$1" +%s 2>/dev/null
}
# lines under any "## heading" whose text equals one of the tab-separated headings in $2
section() {
  [ -f "$1" ] || return 0
  awk -v hs="$2" 'BEGIN { n = split(hs, H, "\t") }
    /^## / { l = $0; sub(/\r$/, "", l); sub(/[ \t]+$/, "", l); on = 0; for (i = 1; i <= n; i++) if (l == H[i]) on = 1; next }
    on { sub(/\r$/, ""); print }' "$1"
}

echo "[MODE] $MODE"

echo '[GIT] (no fetch)'
branch=$(G rev-parse --abbrev-ref HEAD 2>/dev/null)
if G rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  ahead=$(G rev-list --count '@{u}..HEAD')
  behind=$(G rev-list --count 'HEAD..@{u}')
  echo "branch $branch, ahead $ahead, behind $behind"
else
  echo "branch $branch, no upstream"
fi
changed=$(G status --porcelain --untracked-files=no)
if [ -z "$changed" ]; then
  echo 'tracked: clean'
else
  n=$(printf '%s\n' "$changed" | wc -l | tr -d ' ')
  echo "tracked: $n file(s) changed"
  printf '%s\n' "$changed" | head -n 12 | sed 's/^/  /'
  [ "$n" -gt 12 ] && echo "  ... +$((n - 12)) more"
fi
un=$(G ls-files --others --exclude-standard)
if [ -n "$un" ]; then
  echo "untracked: $(printf '%s\n' "$un" | wc -l | tr -d ' ') file(s) (info)"
fi

echo '[OPS]'
OPS="$ROOT/$OPS_FILE"
out=''
if [ -f "$OPS" ]; then
  out=$(awk -F'|' '
    /^## Archive/ { arch = 1; next }
    /^\|/ && NF >= 7 && !arch {
      st = $6; gsub(/[ `\t\r]/, "", st); st = tolower(st)
      if (st != "running" && st != "blocked") next
      ts = $2; gsub(/^ +| +$/, "", ts)
      line = $0; sub(/\r$/, "", line)
      print st "\t" ts "\t" line
    }' "$OPS")
fi
if [ -z "$out" ]; then
  echo '(no running/blocked rows)'
else
  now=$(date +%s)
  printf '%s\n' "$out" | while IFS="$TAB" read -r st ts line; do
    mark=''
    if [ "$st" = running ]; then
      e=$(epoch "$ts")
      [ -n "$e" ] && [ $((now - e)) -gt 7200 ] && mark='  <<STALE>>'
    fi
    if [ ${#line} -gt 200 ]; then line="$(printf '%s' "$line" | cut -c1-200)..."; fi
    echo "$line$mark"
  done
fi

echo '[WIP] discussion/research files not yet status: done (5 newest)'
wip=$(
  cd "$ROOT" 2>/dev/null || exit 0
  pats=$(printf '%s' "$WIP_GLOBS" | tr ',' ' ')
  set --
  set -f  # split the pattern list without expanding it, then expand each pattern on its own
  for pat in $pats; do
    set +f
    for f in $pat; do
      [ -f "$f" ] || continue
      case "$f" in */_template/*|_template/*) continue ;; esac
      set -- "$@" "$f"
    done
    set -f
  done
  set +f
  [ $# -gt 0 ] || exit 0
  ls -t -- "$@" | while IFS= read -r f; do
    s=$(head -n 15 "$f" | tr -d '\r' | grep -m1 -E '^status:[[:space:]]*[^[:space:]]')
    [ -n "$s" ] || continue
    printf '%s\n' "$s" | grep -Eq '^status:[[:space:]]*done([^A-Za-z0-9_]|$)' && continue
    v=$(printf '%s' "$s" | sed 's/^status:[[:space:]]*//; s/[[:space:]]*$//')
    echo "$f ($v)"
  done | head -n 5
)
if [ -z "$wip" ]; then echo '(none)'; else printf '%s\n' "$wip" | sed 's/^/  /'; fi

STATE="$ROOT/$STATE_FILE"
HEADS=$(printf '## %s\t## Awaiting review\t## Belum di-review' "$REVIEW_HEADING")
unrev=$(section "$STATE" "$HEADS" | grep -c '^- ')
echo "[REVIEW] $unrev item(s) awaiting review in $STATE_FILE"

if [ "$MODE" = resume ]; then
  echo '[RESUME]'
  if [ ! -f "$STATE" ]; then
    echo "$STATE_FILE MISSING"
  else
    upd=$(tr -d '\r' < "$STATE" | grep -m1 -E '^\*\*(Last update|Update terakhir)')
    [ -n "$upd" ] && cut_ "$upd" 300
    focus=$(section "$STATE" "$(printf '## Last focus\t## Fokus terakhir')" | grep -m1 '^\*\*')
    [ -n "$focus" ] && echo "focus: $(cut_ "$focus" 400)"
    section "$STATE" "$(printf '## Next step\t## Next steps')" | grep '^- ' | head -n 3 | while IFS= read -r l; do
      echo "next: $(cut_ "$l" 220)"
    done
  fi
  echo '[FORMAT] State the resume point and the first next step, then ask the user which to continue. The data above is the source; do not guess.'
else
  echo "[FORMAT] Answer briefly in four parts: Done / In progress / Next / Blockers. Fill them from this session's task list and the data above. Write \"unknown\" for what is not known; do not guess."
fi
exit 0
