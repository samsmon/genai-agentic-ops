#!/bin/sh
# Group untracked files (read-only): per folder, size, age, guessed kind, and match with the running ops-log locks.
# Usage: triage-untracked.sh [--big-kb N] [--top N] [root]
# Deletes nothing and does not edit .gitignore; it only proposes. The decision is the user's.
# Env: OPS_FILE (default docs/CURRENT_OPS.md). Hidden-mode agentic files are excluded from "untracked" by .git/info/exclude.
BIGKB=1024; TOP=12
while [ $# -gt 0 ]; do
  case "$1" in
    --big-kb) BIGKB=$2; shift 2 ;;
    --top) TOP=$2; shift 2 ;;
    *) break ;;
  esac
done
ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
OPS_FILE="${OPS_FILE:-docs/CURRENT_OPS.md}"

files=$(git -C "$ROOT" -c core.quotepath=false ls-files --others --exclude-standard)
count=0
[ -n "$files" ] && count=$(printf '%s\n' "$files" | wc -l | tr -d ' ')
echo "[UNTRACKED] $count file(s)"
[ "$count" -gt 0 ] || exit 0

OWN=$(mktemp); ROWS=$(mktemp); trap 'rm -f "$OWN" "$ROWS"' EXIT
# targets of running/blocked locks (candidate owners): target <TAB> agent/id
if [ -f "$ROOT/$OPS_FILE" ]; then
  awk -F'|' '
    /^## Archive/ { arch = 1; next }
    /^\|/ && NF >= 7 && !arch {
      st = $6; gsub(/[ `\t\r]/, "", st); st = tolower(st)
      if (st != "running" && st != "blocked") next
      who = $3 "/" $4; gsub(/^ +| +$/, "", who); gsub(/ *\/ */, "/", who)
      s = $5
      while (match(s, /`[^`]+`/)) {
        t = substr(s, RSTART + 1, RLENGTH - 2); s = substr(s, RSTART + RLENGTH)
        gsub(/\\/, "/", t); sub(/^\.\//, "", t); sub(/\/+$/, "", t)
        if (t != "" && t !~ /^\.\./ && t !~ /^[A-Za-z]:/ && t !~ /^\/\//) print t "\t" who
      }
    }' "$ROOT/$OPS_FILE" > "$OWN"
fi

mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }
now=$(date +%s)
printf '%s\n' "$files" | while IFS= read -r f; do
  p="$ROOT/$f"
  [ -f "$p" ] || continue
  bytes=$(wc -c < "$p" | tr -d ' ')
  m=$(mtime "$p"); days=0
  [ -n "$m" ] && days=$(( (now - m) / 86400 ))
  printf '%s\t%s\t%s\n' "$f" "$bytes" "$days"
done > "$ROWS"

awk -F'\t' -v bigkb="$BIGKB" -v top="$TOP" '
  FILENAME == ARGV[1] { own[++no] = $1; who[no] = $2; next }
  {
    f = $1; bytes = $2; days = $3
    n = split(f, P, "/")
    group = (n >= 3) ? P[1] "/" P[2] : P[1]
    name = P[n]; lname = tolower(name)
    ext = ""; if (match(lname, /\.[^.]*$/)) ext = substr(lname, RSTART)
    kind = "other"
    if (lname ~ /^(temp|tmp)[_-]/ || ext ~ /^\.(tmp|bak|log|orig|swp)$/ || lname ~ /~$/) kind = "temp"
    else if (bytes > bigkb * 1024) kind = "big"
    else if (ext ~ /^\.(json|csv|tsv|db|sqlite|xlsx|docx|zip)$/) kind = "data"
    else if (ext ~ /^\.(py|ps1|sh|cmd)$/) kind = "script"
    else if (ext ~ /^\.(md|txt)$/) kind = "notes"
    owner = ""
    for (i = 1; i <= no; i++) if (f == own[i] || index(f, own[i] "/") == 1) { owner = who[i]; break }
    total++
    cnt[group]++; kb[group] += bytes / 1024; kc[group, kind]++
    if (!((group, kind) in seenk)) { seenk[group, kind] = 1; kl[group] = kl[group] (kl[group] == "" ? "" : " ") kind }
    if (owner != "" && index(ol[group] ",", "," owner ",") == 0) ol[group] = ol[group] (ol[group] == "" ? "" : ",") owner
    if (!(group in gi)) { gi[group] = 1; groups[++ng] = group }
    if (owner == "") noowner++
    if (kind == "temp") { nt++; if (nt <= 5) tl[nt] = f "  (" days " days)" }
    if (kind == "big") { nb++; if (nb <= 5) bl[nb] = f "  " sprintf("%.1f", bytes / 1024) " KB" }
    if (kind == "data" && owner == "") { nd++; if (nd <= 5) dl[nd] = f }
  }
  END {
    # order groups by count, descending (selection sort; the list is short)
    for (i = 1; i <= ng; i++) for (j = i + 1; j <= ng; j++) if (cnt[groups[j]] > cnt[groups[i]]) { t = groups[i]; groups[i] = groups[j]; groups[j] = t }
    print "[GROUP] folder: count, total KB, kinds"
    for (i = 1; i <= ng && i <= top; i++) {
      g = groups[i]; ks = ""
      m = split(kl[g], K, " ")
      for (j = 1; j <= m; j++) ks = ks (ks == "" ? "" : " ") K[j] "=" kc[g, K[j]]
      printf "  %-42s %3d file(s) %9.1f KB  %s%s\n", g, cnt[g], kb[g], ks, (ol[g] != "" ? "  lock-owner: " ol[g] : "")
    }
    print "[PROPOSE] proposals only, nothing is executed"
    if (nt) { printf "  temp (%d): check, then delete or add to .gitignore\n", nt; for (i = 1; i <= nt && i <= 5; i++) print "    " tl[i] }
    if (nb) { printf "  big > %d KB (%d): do not stage; .gitignore or move out of the repository\n", bigkb, nb; for (i = 1; i <= nb && i <= 5; i++) print "    " bl[i] }
    if (nd) { printf "  data without a lock owner (%d): .gitignore if it is run output, commit if it is a source\n", nd; for (i = 1; i <= nd && i <= 5; i++) print "    " dl[i] }
    printf "  no lock owner: %d of %d file(s) (never touch files that have an owner from another session)\n", noowner, total
  }
' "$OWN" "$ROWS"
exit 0
