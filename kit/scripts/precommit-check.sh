#!/bin/sh
# Called by .githooks/pre-commit. No model; silent when it passes.
# Usage: precommit-check.sh [--root DIR] [--staged-file LIST] [--rules-file AGENTS.md] [--max-rules-bytes N]
# Blocks: large or media/binary files, and likely secrets in added lines (values are never printed).
# Warns: rules file larger than --max-rules-bytes.
# Overrides, on the user's say-so only: ALLOW_BIG_FILES=1, ALLOW_SECRET_PATTERN=1.
# SECRET_SCAN_SKIP='dir/*,other/*' skips the secret scan for those paths (shell glob patterns).
ROOT=''; LIST=''; RULES=AGENTS.md; MAXRULES=16384
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT=$2; shift 2 ;;
    --staged-file) LIST=$2; shift 2 ;;
    --rules-file) RULES=$2; shift 2 ;;
    --max-rules-bytes) MAXRULES=$2; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
done
[ -n "$ROOT" ] || ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
[ -n "$LIST" ] && [ -f "$LIST" ] || exit 0
rc=0
files=$(tr -d '\r' < "$LIST" | sed '/^$/d')
[ -n "$files" ] || exit 0

if printf '%s\n' "$files" | grep -Fxq -- "$RULES" && [ -f "$ROOT/$RULES" ]; then
  len=$(wc -c < "$ROOT/$RULES" | tr -d ' ')
  [ "$len" -gt "$MAXRULES" ] && echo "WARNING: $RULES is $len B, over $MAXRULES B. Move rarely used blocks into a doc and link to it."
fi

[ -e "$ROOT/.git" ] || exit $rc

OLDIFS=$IFS
IFS='
'
for f in $files; do
  [ -f "$ROOT/$f" ] || continue
  len=$(wc -c < "$ROOT/$f" | tr -d ' ')
  if [ "$len" -gt 5242880 ] || printf '%s' "$f" | grep -Eiq '\.(mp4|mkv|avi|mov|wmv|zip|rar|7z|iso|exe|dll|dmp|flac|mp3|sqlite|sqlite3|db)$'; then
    echo "COMMIT REJECTED: large file or media/binary dump staged: $f ($((len / 1024)) KB). Keep it outside the repo or in .gitignore. Exception is the user's call: rerun with ALLOW_BIG_FILES=1."
    [ "$ALLOW_BIG_FILES" = 1 ] || rc=1
  fi
done
IFS=$OLDIFS

# Secret scan on added lines. PCRE gives the same patterns as the PowerShell version; fall back to ERE without lookaheads.
if echo x | grep -P x >/dev/null 2>&1; then GP='grep -P'; LITERAL='(?i)(api[_-]?key|secret|passwd|password|token)\s*[:=]\s*["'"'"']?(?=[A-Za-z0-9/+_.-]{24,})(?=[A-Za-z0-9/+_.-]*[A-Za-z])(?=[A-Za-z0-9/+_.-]*\d)[A-Za-z0-9/+_.-]{24,}'
else GP='grep -E'; LITERAL=''   # no PCRE: the literal-secret check below falls back to ERE plus a digit/letter test
fi
LITERAL_ERE='(api[_-]?key|secret|passwd|password|token)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9/+_.-]{24,}'
added=$(git -C "$ROOT" -c core.quotepath=off diff --cached -U0 --no-color 2>/dev/null | awk '
  /^\+\+\+ b\// { cur = substr($0, 7); next }
  /^\+\+\+/ { next }
  /^\+/ { print cur "\t" substr($0, 2) }')
[ -n "$added" ] || exit $rc
hits=''
scan() {  # $1 label, $2 regex
  [ -n "$2" ] || return
  printf '%s\n' "$added" | while IFS="$(printf '\t')" read -r path line; do
    skipped=0
    if [ -n "$SECRET_SCAN_SKIP" ]; then
      OLD=$IFS; IFS=','
      for s in $SECRET_SCAN_SKIP; do case "$path" in $s) skipped=1 ;; esac; done
      IFS=$OLD
    fi
    [ $skipped = 1 ] && continue
    printf '%s' "$line" | $GP -q -- "$2" && echo "$path | $1"
  done
}
scan_literal_ere() {  # PCRE-free fallback for the literal-secret pattern
  printf '%s
' "$added" | while IFS="$(printf '	')" read -r path line; do
    skipped=0
    if [ -n "$SECRET_SCAN_SKIP" ]; then
      OLD=$IFS; IFS=','
      for s in $SECRET_SCAN_SKIP; do case "$path" in $s) skipped=1 ;; esac; done
      IFS=$OLD
    fi
    [ $skipped = 1 ] && continue
    m=$(printf '%s' "$line" | grep -Eio -- "$LITERAL_ERE" | head -1)
    [ -n "$m" ] || continue
    v=${m#*[:=]}
    printf '%s' "$v" | grep -q '[0-9]' && printf '%s' "$v" | grep -q '[A-Za-z]' && echo "$path | literal secret value"
  done
}
hits=$( {
  scan 'Anthropic key' 'sk-ant-[A-Za-z0-9_-]{20,}'
  scan 'AWS access key id' 'AKIA[0-9A-Z]{16}'
  scan 'private key' '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  scan 'GitHub token' 'gh[pousr]_[A-Za-z0-9]{30,}'
  scan 'Slack token' 'xox[baprs]-[A-Za-z0-9-]{10,}'
  scan 'Google API key' 'AIza[0-9A-Za-z_-]{35}'
  if [ -n "$LITERAL" ]; then scan 'literal secret value' "$LITERAL"; else scan_literal_ere; fi
} | sort -u )
if [ -n "$hits" ]; then
  printf '%s\n' "$hits" | while IFS= read -r h; do echo "COMMIT REJECTED: possible secret in an added line: $h (value not shown)"; done
  echo "Remove the value and keep it outside the repo. False positive is the user's call: rerun with ALLOW_SECRET_PATTERN=1."
  [ "$ALLOW_SECRET_PATTERN" = 1 ] || rc=1
fi
exit $rc
