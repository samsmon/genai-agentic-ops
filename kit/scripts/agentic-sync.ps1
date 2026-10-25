# agentic-sync (PowerShell): "hidden mode". Keeps the agentic files (rules, pointer files, hooks, ops log) out of the
# project's git history while syncing them between devices through an overlay repository. Same behaviour as agentic-sync.sh.
#
#   Overlay git dir : <project>/.git/agentic           (work tree: the project root)
#   Overlay branch  : agentic-ops (orphan; -Branch to change)
#   Overlay remote  : the project's origin by default, or a separate (private) repo: init -Remote <url>
#   File list       : <project>/.agentic-files          (one pathspec per line; itself tracked by the overlay)
#   Ignore          : <project>/.git/info/exclude       (local to this clone; run init once per clone)
#
# Usage: agentic-sync.ps1 <init|pull|commit|push|status> [-Remote URL|NAME] [-Branch NAME] [-Overwrite] [-LocalOnly]
#                                                         [-Message TEXT] [-Brief] [-Fetch]
# Exit codes: 0 ok, 1 rejected message or identity, 2 usage or not initialised, 3 agentic files already tracked in the
# project history (stop and ask), 4 local files would be overwritten (stop and ask), 5 overlay dirty or diverged
# (stop and ask), 6 overlay remote unreachable.
# A fresh clone has no copy of this script: fetch it from the overlay first (see agentic-sync.sh header), or copy it from the kit.
param(
  [Parameter(Position = 0)][string]$Command = '',
  [string]$Remote = '',
  [string]$Branch = '',
  [switch]$Overwrite,
  [switch]$LocalOnly,
  [string]$Message = 'chore: sync agentic files',
  [switch]$Brief,
  [switch]$Fetch
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Remove-Item Env:GIT_DIR, Env:GIT_WORK_TREE, Env:GIT_INDEX_FILE -ErrorAction SilentlyContinue
$SelfDir = $PSScriptRoot
$Work = (& git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $Work) { [Console]::Error.WriteLine('agentic-sync: run it inside a git work tree'); exit 2 }
$Work = ([string]$Work).Trim()
Set-Location -LiteralPath $Work
$CommonRel = (& git rev-parse --git-common-dir).Trim()
$Common = (Resolve-Path -LiteralPath $CommonRel).Path
$Overlay = Join-Path $Common 'agentic'
$ListFile = Join-Path $Work '.agentic-files'
$RName = 'agentic'
$Utf8 = New-Object System.Text.UTF8Encoding($false)

$DefaultList = @(
  '# Files kept out of the project history and synced through the overlay. One pathspec per line, no spaces in paths.',
  'AGENTS.md', 'CLAUDE.md', 'GEMINI.md', '.cursorrules',
  'docs/CURRENT_OPS.md', 'docs/CURRENT_OPS-archive.md', 'docs/HARNESS_DECLINED.md',
  '.claude/', '.cursor/', '.codex/', '.agents/', '.agent/', '.opencode/', '.githooks/', 'scripts/agentic-ops/', '.agentic-files'
)

function OG { & git "--git-dir=$Overlay" "--work-tree=$Work" @args }
function OGet([string]$key) {
  if (-not (Test-Path -LiteralPath $Overlay)) { return '' }
  $v = & git "--git-dir=$Overlay" config --get $key 2>$null
  if ($LASTEXITCODE -ne 0) { return '' }
  return ([string]$v).Trim()
}
function Say([string]$m) { Write-Output $m }
function Die([int]$code, [string]$m) { [Console]::Error.WriteLine("agentic-sync: $m"); exit $code }
# bytecode caches are never part of the overlay
$NoisePathspecs = @(':(exclude,glob)**/__pycache__/**', ':(exclude,glob)**/*.pyc')

# sh is not on PATH on a default Windows setup; Git for Windows ships it
function FindSh {
  $c = Get-Command sh -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { return $c.Source }
  $roots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs')) | Where-Object { $_ }
  foreach ($r in $roots) {
    foreach ($rel in 'Git\bin\sh.exe', 'Git\usr\bin\sh.exe') {
      $p = Join-Path $r $rel
      if (Test-Path -LiteralPath $p) { return $p }
    }
  }
  return $null
}

function Patterns {
  if (Test-Path -LiteralPath $ListFile) { $src = Get-Content -LiteralPath $ListFile -Encoding UTF8 } else { $src = $DefaultList }
  @($src | ForEach-Object { $_.TrimEnd("`r") } | Where-Object { $_ -notmatch '^\s*#' -and $_ -notmatch '^\s*$' })
}
function BranchName { $b = OGet 'agentic.branch'; if ($b) { $b } else { 'agentic-ops' } }
function NeedOverlay { if (-not (Test-Path -LiteralPath $Overlay)) { Die 2 'this clone is not initialised. Run: agentic-sync init' } }

function WriteExclude {
  $ex = Join-Path $Common 'info/exclude'
  New-Item -ItemType Directory -Force -Path (Join-Path $Common 'info') | Out-Null
  $keep = @(); $skip = $false
  if (Test-Path -LiteralPath $ex) {
    foreach ($l in (Get-Content -LiteralPath $ex -Encoding UTF8)) {
      if ($l -match '^# BEGIN agentic-ops') { $skip = $true }
      if (-not $skip) { $keep += $l }
      if ($l -match '^# END agentic-ops') { $skip = $false }
    }
  }
  $block = @('# BEGIN agentic-ops (managed by agentic-sync; do not edit this block)')
  foreach ($p in (Patterns)) { if ($p.StartsWith('/')) { $block += $p } else { $block += "/$p" } }
  $block += '# END agentic-ops'
  [IO.File]::WriteAllText($ex, ((@($keep) + $block) -join "`n") + "`n", $Utf8)
}

function LivePatterns {
  foreach ($p in (Patterns)) {
    $null = OG ls-files --error-unmatch -- $p 2>$null
    if ((Test-Path -LiteralPath (Join-Path $Work $p)) -or $LASTEXITCODE -eq 0) { $p }
  }
}

# returns 0 ok, 6 unreachable, 7 reachable but no such branch
function FetchOverlay([string]$b) {
  $out = OG ls-remote $RName 2>$null
  if ($LASTEXITCODE -ne 0) { return 6 }
  if (-not (@($out) | Where-Object { $_ -match "refs/heads/$([regex]::Escape($b))$" })) { return 7 }
  $null = OG fetch -q $RName "+refs/heads/${b}:refs/remotes/$RName/$b" 2>$null
  if ($LASTEXITCODE -ne 0) { return 6 }
  return 0
}

function CmdInit {
  $branch = $Branch; if (-not $branch) { $branch = BranchName }
  $tracked = @(& git ls-files -- (Patterns) 2>$null)
  if ($tracked.Count -gt 0) {
    Say 'These agentic files are already tracked in the project history:'
    $tracked | ForEach-Object { Say "  $_" }
    Say 'Hidden mode cannot hide tracked files. Removing them from the index (git rm --cached) leaves them in the history,'
    Say "and rewriting history is not done without the user's decision. Stop and ask the user: keep them visible, or untrack them."
    exit 3
  }
  if (-not (Test-Path -LiteralPath $Overlay)) {
    New-Item -ItemType Directory -Force -Path $Overlay | Out-Null
    & git "--git-dir=$Overlay" init -q
    if ($LASTEXITCODE -ne 0) { Die 2 'cannot create the overlay repository' }
  }
  & git "--git-dir=$Overlay" config core.bare false
  & git "--git-dir=$Overlay" config status.showUntrackedFiles no
  & git "--git-dir=$Overlay" config agentic.branch $branch
  $n = (& git config user.name 2>$null); $e = (& git config user.email 2>$null)
  if ($n) { & git "--git-dir=$Overlay" config user.name $n }
  if ($e) { & git "--git-dir=$Overlay" config user.email $e }

  $url = ''
  if ($Remote) {
    if ($Remote -match '[/\\:]') { $url = $Remote }
    else {
      $url = (& git remote get-url $Remote 2>$null)
      if ($LASTEXITCODE -ne 0 -or -not $url) { Die 2 "unknown remote name: $Remote" }
    }
  } else {
    $url = OGet "remote.$RName.url"
    if (-not $url) { $url = (& git remote get-url origin 2>$null); if ($LASTEXITCODE -ne 0) { $url = '' } }
  }
  $url = ([string]$url).Trim()
  if ($url) {
    if (OGet "remote.$RName.url") { & git "--git-dir=$Overlay" remote set-url $RName $url } else { & git "--git-dir=$Overlay" remote add $RName $url }
  }

  $restored = $false
  if ($url -and -not $LocalOnly) {
    $rc = FetchOverlay $branch
    if ($rc -eq 6) {
      Say "The overlay remote is not reachable: $url"
      Say 'The project works without it, but the agentic files cannot be restored. Ask the owner for access, give another URL'
      Say 'with: init -Remote <url>, or start a local-only overlay with: init -LocalOnly'
      exit 6
    }
    if ($rc -eq 0) {
      $ref = "refs/remotes/$RName/$branch"
      $conflicts = @()
      foreach ($l in (OG ls-tree -r $ref)) {
        $tab = $l.IndexOf("`t"); if ($tab -lt 0) { continue }
        $sha = ($l.Substring(0, $tab) -split '\s+')[2]; $path = $l.Substring($tab + 1)
        $full = Join-Path $Work $path
        if (Test-Path -LiteralPath $full) {
          $lsha = (OG hash-object -- $full 2>$null)
          if (([string]$lsha).Trim() -ne $sha) { $conflicts += $path }
        }
      }
      if ($conflicts.Count -gt 0 -and -not $Overwrite) {
        Say 'These local files differ from the overlay copy and would be replaced:'
        $conflicts | ForEach-Object { Say "  $_" }
        Say 'Stop and ask the user. To replace them (a backup goes to .git/agentic/backup-*): init -Overwrite'
        exit 4
      }
      if ($conflicts.Count -gt 0) {
        $bk = Join-Path $Overlay ('backup-' + (Get-Date -Format 'yyyyMMddHHmmss'))
        foreach ($c in $conflicts) {
          $dst = Join-Path $bk $c
          New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
          Copy-Item -LiteralPath (Join-Path $Work $c) -Destination $dst
        }
        Say "Backed up $($conflicts -join ' ') to $bk"
      }
      $null = OG update-ref "refs/heads/$branch" $ref
      $null = OG symbolic-ref HEAD "refs/heads/$branch"
      $null = OG reset -q
      $null = OG checkout -q -- . 2>$null
      $null = OG branch -q "--set-upstream-to=$RName/$branch" $branch 2>$null
      $restored = $true
    }
  }
  if (-not $restored) { $null = OG symbolic-ref HEAD "refs/heads/$branch" }

  if (-not (Test-Path -LiteralPath $ListFile)) { [IO.File]::WriteAllText($ListFile, ($DefaultList -join "`n") + "`n", $Utf8) }
  WriteExclude
  if ((Test-Path -LiteralPath (Join-Path $Work '.githooks')) -and -not (& git config --get core.hooksPath 2>$null)) { & git config core.hooksPath .githooks }

  $shown = $url; if (-not $shown) { $shown = 'none' }
  Say "agentic-sync: ready. overlay=$Overlay branch=$branch remote=$shown"
  if ($restored) { Say 'Restored the agentic files from the overlay.' }
  else { Say 'No overlay branch on the remote yet (or local-only): this is the first device. Next: agentic-sync commit, then push.' }
  Say "The project's own git status stays clean; the files are ignored through .git/info/exclude in this clone."
}

function CmdPull {
  NeedOverlay
  $branch = BranchName
  $rc = FetchOverlay $branch
  if ($rc -eq 6) { Die 6 'the overlay remote is not reachable' }
  if ($rc -eq 7) { Say "Nothing to pull: the remote has no $branch branch yet."; return }
  $ref = "refs/remotes/$RName/$branch"
  if (@(OG status --porcelain --untracked-files=no).Count -gt 0) {
    Die 5 'the overlay has uncommitted changes. Run: agentic-sync commit, then pull again (stop and ask the user if unsure)'
  }
  $null = OG rev-parse -q --verify HEAD 2>$null
  if ($LASTEXITCODE -ne 0) { Die 5 "this overlay has no commits yet but the remote has $branch. Run: agentic-sync init (it restores the files and asks before replacing any)" }
  $null = OG merge-base --is-ancestor $ref HEAD 2>$null
  if ($LASTEXITCODE -eq 0) { Say 'Already up to date.'; return }
  $null = OG merge-base --is-ancestor HEAD $ref 2>$null
  if ($LASTEXITCODE -eq 0) {
    $null = OG merge --ff-only -q $ref 2>$null
    if ($LASTEXITCODE -ne 0) { Die 5 'fast-forward failed (local untracked files in the way?). Stop and ask the user.' }
    Say ("Pulled: fast-forwarded to " + (OG rev-parse --short HEAD))
    return
  }
  Die 5 'the overlay and the remote have diverged. Not merging automatically: stop and ask the user how to reconcile.'
}

function CmdCommit {
  NeedOverlay
  $mf = [IO.Path]::GetTempFileName()
  [IO.File]::WriteAllText($mf, $Message + "`n", $Utf8)
  try {
    if ($Message -match '(?i)(co-authored-by|signed-off-by|generated-by):|generated with') { Die 1 'the message carries an agent attribution line' }
    $chk = Join-Path $SelfDir 'commit-msg-check.sh'
    if (Test-Path -LiteralPath $chk) {
      $shExe = FindSh
      if ($shExe) {
        & $shExe $chk $mf
        if ($LASTEXITCODE -ne 0) { exit 1 }
      } else { [Console]::Error.WriteLine('warning: sh not found (PATH, Program Files\Git\bin, Program Files\Git\usr\bin); the commit message format was not checked') }
    }
    $ident = "$(OG var GIT_AUTHOR_IDENT 2>$null) $(OG var GIT_COMMITTER_IDENT 2>$null)"
    if ($ident -match '(?i)anthropic|claude|gemini|antigravity|codex|openai|\[bot\]') { Die 1 "the overlay commit identity looks like an agent or bot: $ident" }
    $lp = [IO.Path]::GetTempFileName()
    $live = @(LivePatterns)
    if ($live.Count -gt 0) {
      [IO.File]::WriteAllText($lp, (($live + $NoisePathspecs) -join "`n") + "`n", $Utf8)
      $null = OG add -A "--pathspec-from-file=$lp" 2>$null
      if ($LASTEXITCODE -ne 0) { Remove-Item $lp -ErrorAction SilentlyContinue; Die 2 'git add failed' }
    }
    Remove-Item $lp -ErrorAction SilentlyContinue
    $null = OG rev-parse -q --verify HEAD 2>$null
    $hasHead = ($LASTEXITCODE -eq 0)
    $null = OG diff --cached --quiet 2>$null
    if ($LASTEXITCODE -eq 0 -and $hasHead) { Say 'Nothing to commit.'; return }
    $null = OG commit -q -F $mf 2>$null
    if ($LASTEXITCODE -ne 0) { Die 2 'git commit failed' }
    Say ("Committed " + (OG rev-parse --short HEAD) + " on " + (BranchName) + ".")
  } finally { Remove-Item $mf -ErrorAction SilentlyContinue }
}

function CmdPush {
  NeedOverlay
  $branch = BranchName
  if (-not (OGet "remote.$RName.url")) { Die 2 'no overlay remote configured. Run: agentic-sync init -Remote <url>' }
  $null = OG rev-parse -q --verify HEAD 2>$null
  if ($LASTEXITCODE -ne 0) { Die 2 'nothing to push: no overlay commit yet. Run: agentic-sync commit' }
  $err = OG push -q -u $RName $branch 2>&1
  if ($LASTEXITCODE -eq 0) { Say "Pushed $branch."; return }
  $text = ($err | ForEach-Object { "$_" }) -join "`n"
  [Console]::Error.WriteLine($text)
  if ($text -match 'rejected|non-fast-forward|fetch first') { Die 5 'the remote has commits you do not have. Run: agentic-sync pull (never force-push; stop and ask if it has diverged)' }
  Die 6 'push failed (remote unreachable or no permission)'
}

function CmdStatus {
  if (-not (Test-Path -LiteralPath $Overlay)) {
    if ($Brief) { Say 'OVERLAY: not initialised' } else { Say 'Not initialised. Run: agentic-sync init' }
    return
  }
  $branch = BranchName; $ref = "refs/remotes/$RName/$branch"
  if ($Fetch) { $null = FetchOverlay $branch }
  $pats = @(Patterns)
  $changed = @(OG status --short --untracked-files=all -- $pats $NoisePathspecs 2>$null)
  $ahead = 0; $behind = 0
  $null = OG rev-parse -q --verify HEAD 2>$null; $hasHead = ($LASTEXITCODE -eq 0)
  $null = OG rev-parse -q --verify $ref 2>$null; $hasRef = ($LASTEXITCODE -eq 0)
  if ($hasRef -and $hasHead) { $ahead = [int](OG rev-list --count "$ref..HEAD"); $behind = [int](OG rev-list --count "HEAD..$ref") }
  elseif ($hasRef) { $behind = [int](OG rev-list --count $ref) }
  elseif ($hasHead) { $ahead = [int](OG rev-list --count HEAD) }
  $leaked = @(& git ls-files -- $pats 2>$null)
  if ($Brief) {
    $extra = ''; if ($leaked.Count -gt 0) { $extra = " TRACKED-IN-PROJECT=$($leaked.Count)" }
    Say "OVERLAY: $branch uncommitted=$($changed.Count) ahead=$ahead behind=$behind (behind is as of the last fetch)$extra"
    return
  }
  $url = OGet "remote.$RName.url"; if (-not $url) { $url = 'none' }
  Say "overlay: $Overlay"
  Say "branch: $branch  remote: $url"
  Say "uncommitted agentic changes: $($changed.Count)"
  $changed | ForEach-Object { Say "  $_" }
  Say "overlay commits ahead of remote: $ahead, behind: $behind (as of the last fetch; use -Fetch)"
  if ($leaked.Count -gt 0) { Say "WARNING: $($leaked.Count) agentic file(s) are tracked in the project's own history:"; $leaked | ForEach-Object { Say "  $_" } }
  Say ("project working tree changes (should not list agentic files): " + @(& git status --short).Count)
}

switch ($Command) {
  'init' { CmdInit }
  'pull' { CmdPull }
  'commit' { CmdCommit }
  'push' { CmdPush }
  'status' { CmdStatus }
  default { Get-Content -LiteralPath $PSCommandPath -TotalCount 15 | ForEach-Object { [Console]::Error.WriteLine(($_ -replace '^# ?', '')) }; exit 2 }
}
exit 0
