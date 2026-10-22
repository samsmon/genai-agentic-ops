#!/bin/sh
# agentic-sync: "hidden mode". Keeps the agentic files (rules, pointer files, hooks, ops log) out of the project's
# git history while syncing them between devices through an overlay repository.
#
#   Overlay git dir : <project>/.git/agentic           (work tree: the project root)
#   Overlay branch  : agentic-ops (orphan; configurable)
#   Overlay remote  : the project's origin by default, or a separate (private) repo: init --remote <url>
#   File list       : <project>/.agentic-files          (one pathspec per line; itself tracked by the overlay)
#   Ignore          : <project>/.git/info/exclude       (local to this clone; run init once per clone)
#
# Usage: agentic-sync.sh <command> [options]
#   init   [--remote URL|NAME] [--branch NAME] [--overwrite] [--local-only]   set up this clone, restore files from the overlay
#   pull                                                                       fast-forward the overlay branch (never merges)
#   commit [-m MESSAGE]                                                        commit the listed files in the overlay
#   push                                                                       push the overlay branch (never forces)
#   status [--brief] [--fetch]                                                 what differs
#
# Exit codes: 0 ok, 1 rejected message or identity, 2 usage or not initialised, 3 agentic files already tracked in the
# project history (stop and ask), 4 local files would be overwritten (stop and ask), 5 overlay dirty or diverged
# (stop and ask), 6 overlay remote unreachable.
#
# A fresh clone has no copy of this script. Fetch it from the overlay first:
#   git fetch <overlay-url> agentic-ops && git show FETCH_HEAD:scripts/agentic-ops/agentic-sync.sh | sh -s -- init [--remote <overlay-url>]
set -f
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
SELF_DIR=$(cd "$(dirname "$0")" && pwd)
WORK=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "agentic-sync: run it inside a git work tree" >&2; exit 2; }
COMMON=$(cd "$WORK" && cd "$(git rev-parse --git-common-dir)" && pwd)
OVERLAY="$COMMON/agentic"
LIST="$WORK/.agentic-files"
RNAME=agentic
TAB=$(printf '	')
cd "$WORK" || exit 2

DEFAULT_LIST='# Files kept out of the project history and synced through the overlay. One pathspec per line, no spaces in paths.
AGENTS.md
CLAUDE.md
GEMINI.md
.cursorrules
docs/CURRENT_OPS.md
docs/CURRENT_OPS-archive.md
docs/HARNESS_DECLINED.md
.claude/
.cursor/
.codex/
.agents/
.agent/
.opencode/
.githooks/
scripts/agentic-ops/
.agentic-files'

og() { git --git-dir="$OVERLAY" --work-tree="$WORK" "$@"; }
oget() { [ -d "$OVERLAY" ] && git --git-dir="$OVERLAY" config --get "$1" 2>/dev/null; }
say() { printf '%s\n' "$*"; }
die() { code=$1; shift; printf '%s\n' "agentic-sync: $*" >&2; exit "$code"; }

patterns() {
  if [ -f "$LIST" ]; then src=$(cat "$LIST"); else src=$DEFAULT_LIST; fi
  printf '%s\n' "$src" | sed -e 's/\r$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d'
}

need_overlay() { [ -d "$OVERLAY" ] || die 2 "this clone is not initialised. Run: agentic-sync init"; }

write_exclude() {
  ex="$COMMON/info/exclude"
  mkdir -p "$COMMON/info"
  [ -f "$ex" ] || : > "$ex"
  tmp=$(mktemp)
  awk '/^# BEGIN agentic-ops/{skip=1} !skip{print} /^# END agentic-ops/{skip=0}' "$ex" > "$tmp"
  {
    cat "$tmp"
    echo "# BEGIN agentic-ops (managed by agentic-sync; do not edit this block)"
    patterns | while IFS= read -r p; do case $p in /*) echo "$p" ;; *) echo "/$p" ;; esac; done
    echo "# END agentic-ops"
  } > "$ex"
  rm -f "$tmp"
}

# patterns that exist on disk or are tracked by the overlay (git add fails on a pathspec that matches nothing)
live_patterns() {
  patterns | while IFS= read -r p; do
    if [ -e "$WORK/$p" ] || og ls-files --error-unmatch -- "$p" >/dev/null 2>&1; then echo "$p"; fi
  done
}

branch_name() { b=$(oget agentic.branch); echo "${b:-agentic-ops}"; }

fetch_overlay() {  # $1 = branch; returns 0 ok, 6 unreachable, 7 reachable but no such branch
  b=$1
  og ls-remote "$RNAME" >"$COMMON/agentic/.lsremote" 2>/dev/null || { rm -f "$COMMON/agentic/.lsremote"; return 6; }
  if ! grep -q "refs/heads/$b\$" "$COMMON/agentic/.lsremote"; then rm -f "$COMMON/agentic/.lsremote"; return 7; fi
  rm -f "$COMMON/agentic/.lsremote"
  og fetch -q "$RNAME" "+refs/heads/$b:refs/remotes/$RNAME/$b" 2>/dev/null || return 6
  return 0
}

cmd_init() {
  remote_arg=''; branch=''; overwrite=0; local_only=0
  while [ $# -gt 0 ]; do
    case $1 in
      --remote) remote_arg=$2; shift 2 ;;
      --branch) branch=$2; shift 2 ;;
      --overwrite) overwrite=1; shift ;;
      --local-only) local_only=1; shift ;;
      *) die 2 "init: unknown option $1" ;;
    esac
  done
  [ -n "$branch" ] || branch=$(branch_name)

  tracked=$(git ls-files -- $(patterns) 2>/dev/null)
  if [ -n "$tracked" ]; then
    say "These agentic files are already tracked in the project history:"
    printf '%s\n' "$tracked" | sed 's/^/  /'
    say "Hidden mode cannot hide tracked files. Removing them from the index (git rm --cached) leaves them in the history,"
    say "and rewriting history is not done without the user's decision. Stop and ask the user: keep them visible, or untrack them."
    exit 3
  fi

  if [ ! -d "$OVERLAY" ]; then
    mkdir -p "$OVERLAY"
    git --git-dir="$OVERLAY" init -q || die 2 "cannot create the overlay repository"
  fi
  git --git-dir="$OVERLAY" config core.bare false
  git --git-dir="$OVERLAY" config status.showUntrackedFiles no
  git --git-dir="$OVERLAY" config agentic.branch "$branch"
  n=$(git config user.name 2>/dev/null); e=$(git config user.email 2>/dev/null)
  [ -n "$n" ] && git --git-dir="$OVERLAY" config user.name "$n"
  [ -n "$e" ] && git --git-dir="$OVERLAY" config user.email "$e"

  url=''
  if [ -n "$remote_arg" ]; then
    case $remote_arg in
      */*|*:*|*\\*) url=$remote_arg ;;
      *) url=$(git remote get-url "$remote_arg" 2>/dev/null) || die 2 "unknown remote name: $remote_arg" ;;
    esac
  else
    url=$(oget "remote.$RNAME.url")
    [ -n "$url" ] || url=$(git remote get-url origin 2>/dev/null)
  fi
  if [ -n "$url" ]; then
    if oget "remote.$RNAME.url" >/dev/null; then git --git-dir="$OVERLAY" remote set-url "$RNAME" "$url"
    else git --git-dir="$OVERLAY" remote add "$RNAME" "$url"; fi
  fi

  restored=0
  if [ -n "$url" ] && [ "$local_only" = 0 ]; then
    fetch_overlay "$branch"; rc=$?
    if [ $rc = 6 ]; then
      say "The overlay remote is not reachable: $url"
      say "The project works without it, but the agentic files cannot be restored. Ask the owner for access, give another URL"
      say "with: init --remote <url>, or start a local-only overlay with: init --local-only"
      exit 6
    fi
    if [ $rc = 0 ]; then
      ref="refs/remotes/$RNAME/$branch"
      conflicts=''
      og ls-tree -r "$ref" > "$COMMON/agentic/.tree"
      while IFS= read -r l; do
        meta=${l%%"$TAB"*}; path=${l#*"$TAB"}
        sha=$(printf '%s' "$meta" | awk '{print $3}')
        if [ -e "$WORK/$path" ]; then
          lsha=$(og hash-object -- "$WORK/$path" 2>/dev/null)
          [ "$lsha" = "$sha" ] || conflicts="$conflicts $path"
        fi
      done < "$COMMON/agentic/.tree"
      rm -f "$COMMON/agentic/.tree"
      if [ -n "$conflicts" ] && [ "$overwrite" = 0 ]; then
        say "These local files differ from the overlay copy and would be replaced:"
        for c in $conflicts; do say "  $c"; done
        say "Stop and ask the user. To replace them (a backup goes to .git/agentic/backup-*): init --overwrite"
        exit 4
      fi
      if [ -n "$conflicts" ]; then
        bk="$OVERLAY/backup-$(date +%Y%m%d%H%M%S)"
        for c in $conflicts; do mkdir -p "$bk/$(dirname "$c")"; cp -p "$WORK/$c" "$bk/$c"; done
        say "Backed up ${conflicts# } to $bk"
      fi
      og update-ref "refs/heads/$branch" "$ref"
      og symbolic-ref HEAD "refs/heads/$branch"
      og reset -q
      og checkout -q -- . 2>/dev/null
      og branch -q --set-upstream-to="$RNAME/$branch" "$branch" 2>/dev/null
      restored=1
    fi
  fi
  [ "$restored" = 0 ] && og symbolic-ref HEAD "refs/heads/$branch"

  [ -f "$LIST" ] || printf '%s\n' "$DEFAULT_LIST" > "$LIST"
  write_exclude
  if [ -d "$WORK/.githooks" ] && [ -z "$(git config --get core.hooksPath)" ]; then git config core.hooksPath .githooks; fi

  say "agentic-sync: ready. overlay=$OVERLAY branch=$branch remote=${url:-none}"
  if [ "$restored" = 1 ]; then say "Restored the agentic files from the overlay."
  else say "No overlay branch on the remote yet (or local-only): this is the first device. Next: agentic-sync commit, then push."; fi
  say "The project's own git status stays clean; the files are ignored through .git/info/exclude in this clone."
}

cmd_pull() {
  need_overlay
  branch=$(branch_name)
  fetch_overlay "$branch"; rc=$?
  [ $rc = 6 ] && die 6 "the overlay remote is not reachable"
  [ $rc = 7 ] && { say "Nothing to pull: the remote has no $branch branch yet."; return 0; }
  ref="refs/remotes/$RNAME/$branch"
  if [ -n "$(og status --porcelain --untracked-files=no)" ]; then
    die 5 "the overlay has uncommitted changes. Run: agentic-sync commit, then pull again (stop and ask the user if unsure)"
  fi
  if ! og rev-parse -q --verify HEAD >/dev/null 2>&1; then
    die 5 "this overlay has no commits yet but the remote has $branch. Run: agentic-sync init (it restores the files and asks before replacing any)"
  fi
  if og merge-base --is-ancestor "$ref" HEAD 2>/dev/null; then say "Already up to date."; return 0; fi
  if og merge-base --is-ancestor HEAD "$ref" 2>/dev/null; then
    og merge --ff-only -q "$ref" || die 5 "fast-forward failed (local untracked files in the way?). Stop and ask the user."
    say "Pulled: fast-forwarded to $(og rev-parse --short HEAD)."
    return 0
  fi
  die 5 "the overlay and the remote have diverged. Not merging automatically: stop and ask the user how to reconcile."
}

cmd_commit() {
  need_overlay
  msg='chore: sync agentic files'
  while [ $# -gt 0 ]; do
    case $1 in -m) msg=$2; shift 2 ;; *) die 2 "commit: unknown option $1" ;; esac
  done
  mf=$(mktemp); printf '%s\n' "$msg" > "$mf"
  if printf '%s' "$msg" | grep -Eiq '(co-authored-by|signed-off-by|generated-by):|generated with'; then
    rm -f "$mf"; die 1 "the message carries an agent attribution line"
  fi
  if [ -f "$SELF_DIR/commit-msg-check.sh" ]; then
    sh "$SELF_DIR/commit-msg-check.sh" "$mf" || { rm -f "$mf"; exit 1; }
  fi
  ident="$(og var GIT_AUTHOR_IDENT 2>/dev/null) $(og var GIT_COMMITTER_IDENT 2>/dev/null)"
  if printf '%s' "$ident" | grep -Eiq 'anthropic|claude|gemini|antigravity|codex|openai|\[bot\]'; then
    rm -f "$mf"; die 1 "the overlay commit identity looks like an agent or bot: $ident"
  fi
  lp=$(mktemp); live_patterns > "$lp"
  if [ -s "$lp" ]; then og add -A --pathspec-from-file="$lp" || { rm -f "$mf" "$lp"; die 2 "git add failed"; }; fi
  rm -f "$lp"
  if og diff --cached --quiet 2>/dev/null && og rev-parse -q --verify HEAD >/dev/null 2>&1; then
    rm -f "$mf"; say "Nothing to commit."; return 0
  fi
  og commit -q -F "$mf" || { rm -f "$mf"; die 2 "git commit failed"; }
  rm -f "$mf"
  say "Committed $(og rev-parse --short HEAD) on $(branch_name)."
}

cmd_push() {
  need_overlay
  branch=$(branch_name)
  oget "remote.$RNAME.url" >/dev/null || die 2 "no overlay remote configured. Run: agentic-sync init --remote <url>"
  og rev-parse -q --verify HEAD >/dev/null 2>&1 || die 2 "nothing to push: no overlay commit yet. Run: agentic-sync commit"
  if og push -q -u "$RNAME" "$branch" 2>"$COMMON/agentic/.pusherr"; then
    rm -f "$COMMON/agentic/.pusherr"; say "Pushed $branch."; return 0
  fi
  err=$(cat "$COMMON/agentic/.pusherr"); rm -f "$COMMON/agentic/.pusherr"
  printf '%s\n' "$err" >&2
  case $err in
    *rejected*|*non-fast-forward*|*fetch\ first*) die 5 "the remote has commits you do not have. Run: agentic-sync pull (never force-push; stop and ask if it has diverged)" ;;
    *) die 6 "push failed (remote unreachable or no permission)" ;;
  esac
}

cmd_status() {
  brief=0; dofetch=0
  while [ $# -gt 0 ]; do
    case $1 in --brief) brief=1; shift ;; --fetch) dofetch=1; shift ;; *) die 2 "status: unknown option $1" ;; esac
  done
  if [ ! -d "$OVERLAY" ]; then
    if [ $brief = 1 ]; then say "OVERLAY: not initialised"; else say "Not initialised. Run: agentic-sync init"; fi
    return 0
  fi
  branch=$(branch_name); ref="refs/remotes/$RNAME/$branch"
  [ $dofetch = 1 ] && fetch_overlay "$branch" >/dev/null 2>&1
  pats=$(patterns | tr '\n' ' ')
  changed=$(og status --short --untracked-files=all -- $pats 2>/dev/null | wc -l | tr -d ' ')
  ahead=0; behind=0
  if og rev-parse -q --verify "$ref" >/dev/null 2>&1; then
    if og rev-parse -q --verify HEAD >/dev/null 2>&1; then
      ahead=$(og rev-list --count "$ref..HEAD"); behind=$(og rev-list --count "HEAD..$ref")
    else behind=$(og rev-list --count "$ref"); fi
  elif og rev-parse -q --verify HEAD >/dev/null 2>&1; then ahead=$(og rev-list --count HEAD); fi
  leaked=$(git ls-files -- $pats 2>/dev/null | wc -l | tr -d ' ')
  if [ $brief = 1 ]; then
    say "OVERLAY: $branch uncommitted=$changed ahead=$ahead behind=$behind (behind is as of the last fetch)$( [ "$leaked" != 0 ] && echo " TRACKED-IN-PROJECT=$leaked" )"
    return 0
  fi
  say "overlay: $OVERLAY"
  say "branch: $branch  remote: $(oget "remote.$RNAME.url" || echo none)"
  say "uncommitted agentic changes: $changed"
  [ "$changed" != 0 ] && og status --short --untracked-files=all -- $pats | sed 's/^/  /'
  say "overlay commits ahead of remote: $ahead, behind: $behind (as of the last fetch; use --fetch)"
  if [ "$leaked" != 0 ]; then say "WARNING: $leaked agentic file(s) are tracked in the project's own history:"; git ls-files -- $pats | sed 's/^/  /'; fi
  pstat=$(git status --short 2>/dev/null | wc -l | tr -d ' ')
  say "project working tree changes (should not list agentic files): $pstat"
}

cmd=${1:-}; [ $# -gt 0 ] && shift
case $cmd in
  init) cmd_init "$@" ;;
  pull) cmd_pull "$@" ;;
  commit) cmd_commit "$@" ;;
  push) cmd_push "$@" ;;
  status) cmd_status "$@" ;;
  *) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2 ;;
esac
