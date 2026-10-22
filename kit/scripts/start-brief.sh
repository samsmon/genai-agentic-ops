#!/bin/sh
# Session start summary (read-only). Does not write, pull or summarize.
# Usage: start-brief.sh [root]   (env: OPS_FILE=docs/CURRENT_OPS.md, STATE_FILE=NOW.md)
# Sections: [GIT] sync, [OPS] running/blocked rows, [STATE] optional state file, [HOOK].
# Exit 2 (or a STOP: line) means stop and report to the user.
ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
OPS_FILE="${OPS_FILE:-docs/CURRENT_OPS.md}"
STATE_FILE="${STATE_FILE:-NOW.md}"
rc=0
G() { git -C "$ROOT" "$@"; }

epoch() {  # "YYYY-MM-DD HH:MM" (local) -> epoch seconds; empty on failure
  e=$(date -d "$1" +%s 2>/dev/null) && [ -n "$e" ] && { echo "$e"; return; }
  date -j -f '%Y-%m-%d %H:%M' "$1" +%s 2>/dev/null
}

echo '[GIT]'
GIT_TERMINAL_PROMPT=0 G -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 fetch --quiet >/dev/null 2>&1
if [ $? -ne 0 ]; then
  echo 'STOP:fetch failed (remote unreachable or missing)'
  rc=2
elif ! G rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  echo 'NO_UPSTREAM (no remote tracking branch, sync check skipped)'
else
  ahead=$(G rev-list --count '@{u}..HEAD')
  behind=$(G rev-list --count 'HEAD..@{u}')
  dirty=$(G status --porcelain --untracked-files=no | wc -l | tr -d ' ')
  if [ "$ahead" -gt 0 ] && [ "$behind" -gt 0 ]; then echo "STOP:diverged (ahead $ahead, behind $behind)"; rc=2
  elif [ "$ahead" -gt 0 ]; then echo "STOP:ahead ($ahead commit(s) not pushed)"; rc=2
  elif [ "$dirty" -gt 0 ]; then echo 'STOP:dirty (tracked changes not committed)'; rc=2
  elif [ "$behind" -gt 0 ]; then echo "BEHIND_CLEAN (behind $behind; safe: git pull --ff-only)"
  else echo 'SYNC_OK'
  fi
fi
G status -sb --untracked-files=no
un=$(G ls-files --others --exclude-standard)
if [ -n "$un" ]; then
  n=$(printf '%s\n' "$un" | wc -l | tr -d ' ')
  shown=$(printf '%s\n' "$un" | awk -F/ '{print ($2 == "" ? $1 : $1 "/" $2)}' | awk '!s[$0]++' | head -5 | paste -sd, - | sed 's/,/, /g')
  echo "untracked: $n file(s) (info, not STOP): $shown"
fi

echo '[OPS]'
OPS="$ROOT/$OPS_FILE"
if [ ! -f "$OPS" ]; then
  echo "$OPS_FILE MISSING"
  rc=2
else
  now=$(date +%s)
  out=$(awk -F'|' -v now="$now" '
    /^## Archive/ { arch = 1; next }
    /^\|/ && NF >= 7 {
      st = $6; gsub(/[ `\t\r]/, "", st); st = tolower(st)
      if (st != "running" && st != "blocked") next
      ts = $2; gsub(/^ +| +$/, "", ts)
      line = $0; sub(/\r$/, "", line)
      print st "\t" ts "\t" (arch ? 1 : 0) "\t" line
    }' "$OPS")
  if [ -z "$out" ]; then
    echo '(none)'
  else
    printf '%s\n' "$out" | while IFS="$(printf '\t')" read -r st ts arch line; do
      mark=''
      if [ "$st" = running ]; then
        e=$(epoch "$ts")
        if [ -z "$e" ]; then mark='  <<TIMESTAMP?>>'
        elif [ $((now - e)) -gt 7200 ]; then mark='  <<STALE>>'
        fi
      fi
      [ "$arch" = 1 ] && mark="$mark  <<IN-ARCHIVE>>"
      echo "$line$mark"
    done
  fi
fi

if [ -f "$ROOT/$STATE_FILE" ]; then
  echo '[STATE]'
  cat "$ROOT/$STATE_FILE"
fi

echo '[HOOK]'
h=$(G config core.hooksPath 2>/dev/null)
if [ "$h" = .githooks ]; then echo 'core.hooksPath=.githooks OK'
else echo "core.hooksPath=$h NOT ACTIVE (run: git config core.hooksPath .githooks)"
fi
exit $rc
