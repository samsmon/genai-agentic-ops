#!/bin/sh
# Sort the review queue in the state file (read-only): per project, per agent, anomalies and the oldest items.
# Usage: review-queue.sh [--top N] [root]
# Anomalies: file missing, front matter unreadable, status not done, reviewed_by already filled but still listed.
# Env: STATE_FILE (default NOW.md), REVIEW_HEADING (default "Awaiting review"; "Belum di-review" is always accepted too).
# Item format: "- path/to/file.md (by agent) - description"; "(oleh agent)" is accepted too.
# Exit is always 0: this is a report, not a gate (the gate is wrap-check).
TOP=10
while [ $# -gt 0 ]; do
  case "$1" in --top) TOP=$2; shift 2 ;; *) break ;; esac
done
ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
STATE_FILE="${STATE_FILE:-NOW.md}"
REVIEW_HEADING="${REVIEW_HEADING:-Awaiting review}"
TAB=$(printf '\t')
NOW="$ROOT/$STATE_FILE"

if [ ! -f "$NOW" ]; then echo "$STATE_FILE MISSING"; exit 0; fi
HEADS=$(printf '## %s\t## Awaiting review\t## Belum di-review' "$REVIEW_HEADING")
items=$(awk -v hs="$HEADS" 'BEGIN { n = split(hs, H, "\t") }
  /^## / { l = $0; sub(/\r$/, "", l); sub(/[ \t]+$/, "", l); on = 0; for (i = 1; i <= n; i++) if (l == H[i]) on = 1; next }
  on && /^- / { sub(/\r$/, ""); print }' "$NOW")
count=0
[ -n "$items" ] && count=$(printf '%s\n' "$items" | wc -l | tr -d ' ')
echo "[QUEUE] $count item(s)"
[ "$count" -gt 0 ] || exit 0

day_epoch() { date -d "$1" +%s 2>/dev/null || date -j -f '%Y-%m-%d' "$1" +%s 2>/dev/null; }
mtime_day() {
  m=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null)
  date -d "@$m" +%F 2>/dev/null || date -r "$m" +%F 2>/dev/null
}
today=$(day_epoch "$(date +%F)")
RE='^-[[:space:]]+`?([^[:space:]`()]+\.md)`?([[:space:]]+\((by|oleh)[[:space:]]+([^)]+)\))?[[:space:]]*[-:]?[[:space:]]*(.*)$'
ROWS=$(mktemp); trap 'rm -f "$ROWS"' EXIT

printf '%s\n' "$items" | while IFS= read -r l; do
  rel=$(printf '%s\n' "$l" | sed -nE "s/$RE/\\1/p" | tr '\\' '/')
  if [ -z "$rel" ]; then
    printf '?\t?\t?\t-1\tUNPARSED\t%s\n' "$(printf '%s' "$l" | cut -c3-)"
    continue
  fi
  agent=$(printf '%s\n' "$l" | sed -nE "s/$RE/\\4/p" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  [ -n "$agent" ] || agent='?'
  desc=$(printf '%s\n' "$l" | sed -nE "s/$RE/\\5/p" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')
  [ ${#desc} -gt 90 ] && desc="$(printf '%s' "$desc" | cut -c1-90)..."
  case "$rel" in projects/*/*) project=$(printf '%s' "$rel" | cut -d/ -f2) ;; *) project=$(printf '%s' "$rel" | cut -d/ -f1) ;; esac
  flags=''; age=-1
  dm=$(printf '%s' "$rel" | grep -Eo '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -n 1)
  full="$ROOT/$rel"
  if [ ! -f "$full" ]; then
    flags='MISSING'
  else
    head=$(head -n 20 "$full" | tr -d '\r')
    st=$(printf '%s\n' "$head" | grep -m1 -E '^status:[[:space:]]*[^[:space:]]')
    rb=$(printf '%s\n' "$head" | grep -m1 -E '^reviewed_by:[[:space:]]*\[.*\]')
    if [ -z "$st" ] && [ -z "$rb" ]; then
      flags='NO-FRONTMATTER'
    else
      if [ -n "$st" ] && ! printf '%s\n' "$st" | grep -Eq '^status:[[:space:]]*done([^A-Za-z0-9_]|$)'; then flags='NOT-DONE'; fi
      if [ -n "$rb" ]; then
        inner=$(printf '%s' "$rb" | sed -E 's/^reviewed_by:[[:space:]]*\[(.*)\].*$/\1/; s/[[:space:]]//g')
        [ -n "$inner" ] && flags="${flags:+$flags,}ALREADY-REVIEWED"
      fi
    fi
    d=${dm:-$(mtime_day "$full")}
    de=$(day_epoch "$d")
    [ -n "$de" ] && age=$(( (today - de) / 86400 ))
  fi
  if [ "$age" -lt 0 ] && [ -n "$dm" ]; then
    de=$(day_epoch "$dm"); [ -n "$de" ] && age=$(( (today - de) / 86400 ))
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$project" "$agent" "$rel" "$age" "${flags:--}" "$desc"
done > "$ROWS"

echo '[PROJECT]'
cut -f1 "$ROWS" | sort | uniq -c | sort -k1,1nr | awk '{ c = $1; $1 = ""; sub(/^ /, ""); printf "  %-22s %s\n", $0, c }'
echo '[AGENT]'
cut -f2 "$ROWS" | sort | uniq -c | sort -k1,1nr | awk '{ c = $1; $1 = ""; sub(/^ /, ""); printf "  %-22s %s\n", $0, c }'

echo '[FLAG] anomalies (fix before reviewing)'
bad=$(awk -F'\t' '$5 != "-" { printf "  %s  %s\n", $5, $3 }' "$ROWS")
if [ -z "$bad" ]; then echo '  (none)'; else printf '%s\n' "$bad"; fi

echo "[OLDEST] $TOP oldest item(s)"
awk -F'\t' '$4 >= 0' "$ROWS" | sort -t"$TAB" -k4,4nr | head -n "$TOP" | awk -F'\t' '{ printf "  %3sd  %s  [%s]  %s\n", $4, $3, $2, $6 }'
exit 0
