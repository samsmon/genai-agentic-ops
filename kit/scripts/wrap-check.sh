#!/bin/sh
# End-of-session check (read-only). Writes nothing.
# Usage: wrap-check.sh [--root DIR] [--agent NAME] [--today YYYY-MM-DD] [--git-policy user-only-git|agent-commits] [--ignore PAT[,PAT]]
# Checks: ops log (no running rows of this agent, at most 5 finished rows in the main table) and git state.
# When handoff-check.sh sits next to this script (handoff module), it runs too and its failures count.
ROOT=''; AGENT=claude-code; TODAY=$(date +%F); OPS_FILE="${OPS_FILE:-docs/CURRENT_OPS.md}"; POLICY=agent-commits; IGNORE=''
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT=$2; shift 2 ;;
    --agent) AGENT=$2; shift 2 ;;
    --today) TODAY=$2; shift 2 ;;
    --git-policy) POLICY=$2; shift 2 ;;
    --ignore) IGNORE=$2; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
done
[ -n "$ROOT" ] || ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
bad=0
ok() { echo "OK     $1"; }
no() { echo "FAIL   $1"; bad=$((bad + 1)); }

# 1-2. ops log
OPS="$ROOT/$OPS_FILE"
if [ ! -f "$OPS" ]; then
  no "OPS: $OPS_FILE not found"
else
  res=$(awk -F'|' -v agent="$(echo "$AGENT" | tr 'A-Z' 'a-z')" '
    /^## Archive/ { arch = 1; next }
    /^\|/ && NF >= 7 {
      st = $6; gsub(/[ `\t\r]/, "", st); st = tolower(st)
      ag = $3; gsub(/[ \t\r]/, "", ag); ag = tolower(ag)
      ts = $2; gsub(/^ +| +$/, "", ts)
      if (st == "running" && ag == agent) { mine++; if (first == "") { first = $0; sub(/\r$/, "", first) } }
      if (!arch && st != "running" && st != "blocked" && ts ~ /^[0-9]/) done++
    }
    END { printf "%d\t%d\t%s\n", mine, done, first }' "$OPS")
  mine=$(printf '%s' "$res" | cut -f1); done=$(printf '%s' "$res" | cut -f2); first=$(printf '%s' "$res" | cut -f3-)
  if [ "$mine" -gt 0 ]; then no "OPS: $mine running row(s) of $AGENT not closed: $first"; else ok "OPS: no running rows of $AGENT"; fi
  if [ "$done" -gt 5 ]; then no "OPS: $done finished rows in the main table (max 5); move older ones to the archive file"; else ok "OPS: $done finished rows in the main table (max 5)"; fi
fi

# 3. git
if ! git -C "$ROOT" rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  ok 'GIT: no upstream (skipped)'
else
  ahead=$(git -C "$ROOT" rev-list --count '@{u}..HEAD')
  dirty=''
  list=$(git -C "$ROOT" -c core.quotepath=off status --porcelain --untracked-files=no | cut -c4-)
  OLDIFS=$IFS
  IFS='
'
  for p in $list; do
    skip=0
    if [ -n "$IGNORE" ]; then
      IFS=','
      for pat in $IGNORE; do case "$p" in $pat) skip=1 ;; esac; done
      IFS='
'
    fi
    [ "$skip" = 0 ] && dirty="${dirty:+$dirty, }$p"
  done
  IFS=$OLDIFS
  ndirty=0; [ -n "$dirty" ] && ndirty=$(printf '%s' "$dirty" | awk -F', ' '{print NF}')
  if [ "$POLICY" = user-only-git ]; then
    ok "GIT: user-only-git, $ndirty changed file(s) and $ahead unpushed commit(s) are for the user to commit"
  elif [ "$ahead" -gt 0 ]; then no "GIT: $ahead commit(s) not pushed"
  elif [ "$ndirty" -gt 0 ]; then no "GIT: tracked changes not committed: $dirty. If they belong to another session, do not commit them: report to the user, then rerun with --ignore '<path>'."
  else ok 'GIT: clean and pushed'
  fi
fi

# 4. optional handoff module
if [ -f "$HERE/handoff-check.sh" ]; then
  out=$(sh "$HERE/handoff-check.sh" --root "$ROOT" --agent "$AGENT" --today "$TODAY")
  printf '%s\n' "$out" | grep -v '^\[HANDOFF\]'
  nf=$(printf '%s\n' "$out" | grep -c '^FAIL')
  bad=$((bad + nf))
fi

echo "[WRAP] $bad failed"
[ "$bad" -gt 0 ] && exit 1
exit 0
