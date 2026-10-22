#!/bin/sh
# Check a commit message file against Conventional Commits 1.0.0 and the seven Chris Beams rules.
# Usage: commit-msg-check.sh <message-file>
#   exit 0 = accepted (warnings may print), exit 1 = rejected, exit 2 = usage error.
# Called by githooks/commit-msg; PowerShell can call it too:  sh scripts/agentic-ops/commit-msg-check.sh <file>
# Extra types:   git config agentic.commitTypes "ops wip"      or   COMMIT_EXTRA_TYPES="ops wip"
# Skip the check (the user's call only):   SKIP_COMMIT_FORMAT=1
# Rules and reasons: kit/commit-format.md
set -f
msg=$1
if [ -z "$msg" ] || [ ! -f "$msg" ]; then
  echo "usage: commit-msg-check.sh <message-file>" >&2
  exit 2
fi
[ "${SKIP_COMMIT_FORMAT:-}" = "1" ] && exit 0

cfg=$(git config --get agentic.commitTypes 2>/dev/null)
all="feat fix docs style refactor perf test build ci chore revert $cfg ${COMMIT_EXTRA_TYPES:-}"
types=''
allowed=''
for t in $all; do
  case "|$types|" in *"|$t|"*) continue ;; esac
  types="${types:+$types|}$t"
  allowed="${allowed:+$allowed }$t"
done

out=$(awk -v types="$types" -v allowed="$allowed" '
{ line = $0; sub(/\r$/, "", line) }
line ~ /^#/ { next }
{ L[++n] = line }
END {
  s = 1
  while (s <= n && L[s] ~ /^[ \t]*$/) s++
  if (s > n) exit 0
  subj = L[s]
  if (subj ~ /^Merge / || subj ~ /^Revert "/ || subj ~ /^(fixup|squash|amend)! /) exit 0
  re = "^(" types ")(\\([A-Za-z0-9._/,-]+\\))?!?: "
  if (subj !~ re) {
    if (subj ~ /^\[[^]]*\]/) print "E nothing may come before the type, not even a bracketed prefix. Use: type(scope): description"
    else if (subj ~ ("^(" types ")(\\([A-Za-z0-9._/,-]+\\))?!?:[^ ]")) print "E a single space is required after the colon"
    else if (subj ~ /^[A-Za-z]+(\([^)]*\))?!?:/) { t = subj; sub(/[(!:].*$/, "", t); print "E unknown type \"" t "\" (allowed: " allowed ")" }
    else print "E the subject must look like: type(scope): description"
  } else {
    match(subj, re)
    desc = substr(subj, RLENGTH + 1)
    if (desc ~ /^[ \t]*$/) print "E the description after the colon is empty"
    else {
      if (desc ~ /^[ \t]/) print "E use exactly one space after the colon"
      if (desc ~ /^[A-Z]/) print "E the description must start with a lowercase letter"
      if (desc ~ /[.]$/) print "E the subject must not end with a period"
      w = desc; sub(/[ ,:;(].*$/, "", w)
      if (w ~ /^(added|fixed|updated|removed|changed|implemented|created|deleted|moved|renamed|refactored|adding|fixing|updating|removing|changing|implementing|creating|deleting|moving|renaming|refactoring|adds|fixes|updates|removes|changes|implements|creates|deletes|moves|renames|refactors)$/)
        print "W use the imperative mood (\"add\", not \"" w "\")"
    }
    len = length(subj)
    if (len > 72) print "E the subject is " len " characters; the hard limit is 72 (aim for 50)"
    else if (len > 50) print "W the subject is " len " characters; aim for 50 or fewer"
  }
  if (s + 1 <= n && L[s + 1] !~ /^[ \t]*$/) print "E a blank line is required between the subject and the body"
  wide = 0
  for (i = s + 1; i <= n; i++) {
    if (L[i] ~ /^BREAKING[ -]CHANGE:[ \t]*$/) print "E BREAKING CHANGE needs a description after the colon"
    if (length(L[i]) > 72 && L[i] !~ /:\/\//) wide++
  }
  if (wide > 0) print "W " wide " body line(s) are longer than 72 characters; wrap them"
}
' "$msg")

rc=0
errs=$(printf '%s\n' "$out" | sed -n 's/^E //p')
warns=$(printf '%s\n' "$out" | sed -n 's/^W //p')
if [ -n "$warns" ]; then
  printf '%s\n' "$warns" | while IFS= read -r w; do echo "warning: $w" >&2; done
fi
if [ -n "$errs" ]; then
  echo "COMMIT REJECTED: the message does not follow Conventional Commits." >&2
  printf '%s\n' "$errs" | while IFS= read -r e; do echo "  - $e" >&2; done
  echo "Format: type(scope): subject  (blank line, then a body wrapped at 72 columns). Types: $allowed. Details: kit/commit-format.md" >&2
  rc=1
fi
exit $rc
