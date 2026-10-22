#!/bin/sh
# Handoff module check (read-only). Normally run by wrap-check.sh; can run alone.
# Usage: handoff-check.sh [--root DIR] [--agent NAME] [--today YYYY-MM-DD]
# env: STATE_FILE=NOW.md LOG_DIR=log REVIEW_HEADING='## Awaiting review' DISCUSSION_DIR=discussion
ROOT=''; AGENT=claude-code; TODAY=$(date +%F)
STATE_FILE="${STATE_FILE:-NOW.md}"; LOG_DIR="${LOG_DIR:-log}"
REVIEW_HEADING="${REVIEW_HEADING:-## Awaiting review}"; DISCUSSION_DIR="${DISCUSSION_DIR:-discussion}"
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT=$2; shift 2 ;;
    --agent) AGENT=$2; shift 2 ;;
    --today) TODAY=$2; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
done
[ -n "$ROOT" ] || ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
bad=0
ok() { echo "OK     $1"; }
no() { echo "FAIL   $1"; bad=$((bad + 1)); }

STATE="$ROOT/$STATE_FILE"
if [ ! -f "$STATE" ]; then
  no "STATE: $STATE_FILE not found"
elif grep -Eq "Last update:\*{0,2}[[:space:]]*$TODAY[[:space:]]+by[[:space:]]+$AGENT" "$STATE"; then
  ok "STATE: Last update = $TODAY by $AGENT"
else
  no "STATE: 'Last update' line is not '$TODAY by $AGENT'"
fi

LOG="$ROOT/$LOG_DIR/$(printf '%s' "$TODAY" | cut -c1-7).md"
if [ -f "$LOG" ] && grep -Fq -- "- $TODAY [$AGENT]" "$LOG"; then ok "LOG: line for $TODAY [$AGENT] present"
else no "LOG: no '- $TODAY [$AGENT]' line in the monthly log"
fi

files=$(find "$ROOT" -type f -name '*.md' -path "*/$DISCUSSION_DIR/*" ! -name '_*' ! -path '*/.git/*' ! -path '*/_template/*' 2>/dev/null | sort)
if [ -z "$files" ] || [ ! -f "$STATE" ]; then
  ok 'REVIEW: no discussion files to check'
else
  sec=$(awk -v h="$REVIEW_HEADING" 'index($0, h) == 1 { on = 1; print; next } on && /^## / { exit } on { print }' "$STATE")
  probs=''; nprob=0; total=0
  for f in $files; do
    total=$((total + 1)); name=$(basename "$f")
    fm=$(tr -d '\r' < "$f" | awk 'NR == 1 && $0 != "---" { exit } NR == 1 { next } /^---$/ { exit } { print }')
    if [ -z "$fm" ]; then probs="$probs; $name: no front matter"; nprob=$((nprob + 1)); continue; fi
    rb=$(printf '%s\n' "$fm" | sed -n 's/^reviewed_by:[[:space:]]*\[\(.*\)\].*/\1/p' | head -1)
    if ! printf '%s\n' "$fm" | grep -q '^reviewed_by:[[:space:]]*\['; then probs="$probs; $name: no reviewed_by"; nprob=$((nprob + 1)); continue; fi
    st=$(printf '%s\n' "$fm" | sed -n 's/^status:[[:space:]]*\([^[:space:]]*\).*/\1/p' | head -1)
    [ -n "$st" ] && [ "$st" != done ] && continue
    listed=0; printf '%s\n' "$sec" | grep -Fq -- "$name" && listed=1
    reviewed=0; [ -n "$(printf '%s' "$rb" | tr -d '[:space:]')" ] && reviewed=1
    if [ $reviewed = 0 ] && [ $listed = 0 ]; then probs="$probs; $name: not reviewed but missing from $STATE_FILE"; nprob=$((nprob + 1)); fi
    if [ $reviewed = 1 ] && [ $listed = 1 ]; then probs="$probs; $name: reviewed but still listed in $STATE_FILE"; nprob=$((nprob + 1)); fi
  done
  if [ $nprob -gt 0 ]; then no "REVIEW: $nprob discussion file(s) disagree with ${STATE_FILE}:$(printf '%s' "$probs" | cut -c2- | cut -c1-300)"
  else ok "REVIEW: $total discussion file(s) match $STATE_FILE"
  fi
fi

echo "[HANDOFF] $bad failed"
[ "$bad" -gt 0 ] && exit 1
exit 0
