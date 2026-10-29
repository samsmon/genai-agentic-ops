#!/bin/sh
# Commit (and optionally push) only this session's files, with the checks of the rules (sections 8 and 9):
#   - paths must be explicit; "." and "*" are refused
#   - stops when files outside the paths are staged (they belong to another session)
#   - commits with a pathspec, the message goes through a temporary file (the commit-msg hook still runs)
#   - --push: git fetch, stops when the remote has new commits (no rebase or merge), checks identity and trailers, then pushes
#   - --dry-run: run the checks and show the stat, commit nothing
# Usage: commit-mine.sh -m MESSAGE [--push] [--dry-run] [--root DIR] PATH [PATH...]   (PATH may also be "a,b")
# Hidden mode: agentic files are excluded from the project history; use agentic-sync commit for them.
# Exit: 0 ok, 1 misuse or failure, 2 STOP (needs a decision from the user).
MSG=''; PUSH=0; DRY=0; ROOT=''
LIST=$(mktemp) || exit 1
trap 'rm -f "$LIST" "$MSGFILE"' EXIT
while [ $# -gt 0 ]; do
  case "$1" in
    -m|--message) MSG=$2; shift 2 ;;
    --push) PUSH=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --root) ROOT=$2; shift 2 ;;
    *) printf '%s\n' "$1" | tr ',' '\n' >> "$LIST"; shift ;;
  esac
done
[ -n "$ROOT" ] || ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
G() { git -C "$ROOT" "$@"; }
stop() { echo "STOP:$1"; exit "${2:-2}"; }

[ -n "$MSG" ] || stop 'no message (-m)' 1

# normalise: backslashes to /, drop a leading ./ (sed, not a character-set trim, so .github keeps its dot), drop trailing /
SPECS=$(sed -e 's#\\#/#g' -e 's#^\./##' -e 's#/*$##' "$LIST" | awk 'NF')
while IFS= read -r raw; do
  [ -n "$raw" ] || continue
  n=$(printf '%s' "$raw" | sed -e 's#\\#/#g' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
  case "$n" in
    .|./|\*|/|''|..|../*) stop "path too broad or outside the repository: '$raw' (name the files or folders of this session)" 1 ;;
  esac
done < "$LIST"
[ -n "$SPECS" ] || stop 'no paths' 1
set --
while IFS= read -r s; do set -- "$@" "$s"; done <<EOF
$SPECS
EOF

# 1. any change under the paths?
mine=$(G status --porcelain --untracked-files=all -- "$@")
if [ -z "$mine" ]; then
  for s in "$@"; do
    if G check-ignore -q -- "$s" 2>/dev/null; then
      stop "'$s' is ignored by the project history (hidden-mode agentic file?); use agentic-sync commit for it" 1
    fi
  done
  stop 'no changes under the given paths' 1
fi

# 2. staged files that belong to another session?
foreign=$(G diff --cached --name-only | while IFS= read -r f; do
  covered=0
  while IFS= read -r s; do
    case "$f" in "$s"|"$s"/*) covered=1; break ;; esac
  done <<EOF2
$SPECS
EOF2
  [ $covered = 1 ] || echo "$f"
done)
if [ -n "$foreign" ]; then
  echo 'staged files outside the paths (another session, not committed):'
  printf '%s\n' "$foreign" | head -n 10 | sed 's/^/  /'
  stop 'another session has staged files; wait for its commit or report to the user'
fi

# 3. stage only these paths and show the stat
G add -- "$@"
echo '[STAT]'
G diff --cached --stat
if [ $DRY = 1 ]; then echo 'DRYRUN: nothing committed'; exit 0; fi

# 4. commit with a pathspec
MSGFILE=$(mktemp)
printf '%s\n' "$MSG" > "$MSGFILE"
if ! o=$(G commit -q -F "$MSGFILE" -- "$@" 2>&1); then
  printf '%s\n' "$o"
  stop 'commit rejected (see the hook message above)' 1
fi
[ -n "$o" ] && printf '%s\n' "$o"
echo "COMMIT: $(G log -1 --format='%h %s')"
if [ $PUSH = 0 ]; then echo 'push skipped (no --push)'; exit 0; fi

# 5. safe push
export GIT_TERMINAL_PROMPT=0
G fetch --quiet >/dev/null 2>&1 || stop 'fetch failed; the commit exists locally, not pushed'
G rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1 || stop 'no upstream; push by hand after the user decides'
behind=$(G rev-list --count 'HEAD..@{u}')
[ "$behind" -gt 0 ] && stop "the remote has $behind new commit(s); the local commit exists, no automatic rebase or merge, report to the user"

email=$(G config user.email); name=$(G config user.name)
bad=$(G rev-list '@{u}..HEAD' | while read -r sha; do
  id=$(G log -1 --format='%an|%ae|%cn|%ce' "$sha")
  [ "$id" = "$name|$email|$name|$email" ] || echo "$(printf '%s' "$sha" | cut -c1-7): identity $id"
  if G log -1 --format='%B' "$sha" | grep -Eiq '^(co-authored-by|signed-off-by|generated-by)[[:space:]]*:|generated with'; then
    echo "$(printf '%s' "$sha" | cut -c1-7): agent trailer in the message"
  fi
done)
if [ -n "$bad" ]; then
  printf '%s\n' "$bad" | sed 's/^/  /'
  stop 'identity or trailer does not match the policy; push cancelled'
fi

o=$(G push -q 2>&1) || { printf '%s\n' "$o"; stop 'push failed' 1; }
[ -n "$o" ] && printf '%s\n' "$o"
echo 'PUSH: ok'
exit 0
