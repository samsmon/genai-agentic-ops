$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Sc 'commit-mine.ps1')).Path
$base = Join-Path $env:TEMP ("cmt-" + [guid]::NewGuid())
$fail = 0
function Expect([string]$name, $ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function G([string]$d, [string[]]$a) { & git -C $d @a 2>$null | Out-Null }
function Cfg([string]$d) { G $d @('config', 'user.name', 't'); G $d @('config', 'user.email', 't@t') }
function W([string]$d, [string]$f, [string]$t = 'x') { $p = Join-Path $d $f; New-Item -ItemType Directory (Split-Path $p) -Force | Out-Null; Set-Content $p $t -Encoding UTF8 }
function CM([string[]]$cmArgs, [string]$d, [bool]$withRoot = $true) {
  if ($withRoot) { $o = & powershell -NoProfile -File $script @cmArgs -Root $d }
  else { Push-Location $d; $o = & powershell -NoProfile -File $script @cmArgs; Pop-Location }
  return @{ code = $LASTEXITCODE; out = ($o -join "`n") }
}
function New-Env {
  Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory $base | Out-Null
  $bare = Join-Path $base 'bare.git'; $c1 = Join-Path $base 'c1'; $c2 = Join-Path $base 'c2'
  G $base @('init', '--bare', '-q', $bare); G $bare @('symbolic-ref', 'HEAD', 'refs/heads/main')
  G $base @('clone', '-q', $bare, $c1); G $c1 @('symbolic-ref', 'HEAD', 'refs/heads/main'); Cfg $c1
  W $c1 'a.txt' 'a'; W $c1 'sub\b.txt' 'b'; W $c1 '.github\w.yml' 'w'
  G $c1 @('add', '-A'); G $c1 @('commit', '-q', '-m', 'init'); G $c1 @('push', '-q', '-u', 'origin', 'main')
  G $base @('clone', '-q', $bare, $c2); Cfg $c2
  return @{ c1 = $c1; c2 = $c2 }
}
try {
  $e = New-Env; $d = $e.c1
  $r = CM @('-Message', 'feat: x', '-Paths', '.') $d
  Expect 'path "." is refused' (($r.code -eq 1) -and ($r.out -match 'too broad'))
  $r = CM @('-Message', 'feat: x', '-Paths', 'a.txt') $d
  Expect 'no changes -> exit 1' (($r.code -eq 1) -and ($r.out -match 'no changes'))

  W $d 'a.txt' 'a2'; W $d 'other.txt' 'o'
  $r = CM @('-Message', 'feat: x', '-Paths', 'a.txt', '-DryRun') $d
  Expect 'dry run shows the stat and commits nothing' (($r.code -eq 0) -and ($r.out -match 'a\.txt') -and ($r.out -match 'DRYRUN') -and ((& git -C $d rev-list --count HEAD) -eq '1'))
  G $d @('reset', '-q')
  $r = CM @('-Message', 'feat: x', '-Paths', 'a.txt,other.txt', '-DryRun') $d
  Expect 'comma-separated path list' (($r.code -eq 0) -and ($r.out -match 'a\.txt') -and ($r.out -match 'other\.txt'))
  G $d @('reset', '-q')

  # pitfall: $PSScriptRoot is empty in a param default when a parameter is Mandatory -> the root is computed in the body (run without -Root, from inside the repository)
  $r = CM @('-Message', 'feat: x', '-Paths', 'a.txt', '-DryRun') $d $false
  Expect 'pitfall: runs without -Root (root computed in the body, not from $PSScriptRoot)' (($r.code -eq 0) -and ($r.out -match 'DRYRUN'))
  G $d @('reset', '-q')
  $src = Get-Content -Raw -LiteralPath $script
  Expect 'pitfall: no param default uses $PSScriptRoot' ($src -notmatch '\[string\]\$Root\s*=\s*\(?\s*Join-Path\s+\$PSScriptRoot')
  # pitfall: a function named Git shadows git.exe (and recurses); the helper is Invoke-Git
  Expect 'pitfall: no function named Git, helper is Invoke-Git' (($src -notmatch '(?im)^\s*function\s+Git\b') -and ($src -match 'function Invoke-Git'))

  # staged files of another session
  G $d @('add', 'other.txt')
  $r = CM @('-Message', 'feat: x', '-Paths', 'a.txt') $d
  Expect 'staged outside the paths -> STOP exit 2' (($r.code -eq 2) -and ($r.out -match 'other\.txt') -and ($r.out -match 'STOP:'))
  Expect 'the other session''s staged file is not committed' ((& git -C $d rev-list --count HEAD) -eq '1')
  G $d @('reset', '-q')

  # pathspec commit of a folder, no other file dragged along
  W $d 'sub\b.txt' 'b2'
  $r = CM @('-Message', "feat: edit sub`n`nbody", '-Paths', './sub/') $d
  Expect 'commit of a folder works' (($r.code -eq 0) -and ($r.out -match 'COMMIT:'))
  Expect 'only the files of the path are committed' ((((& git -C $d show --name-only --format= HEAD) -join ',') -eq 'sub/b.txt'))
  Expect 'other files stay uncommitted' ((& git -C $d status --porcelain) -match 'a\.txt')

  # pitfall: a character-set trim of './' strips leading dots; a path under .github must keep its dot
  W $d '.github\w.yml' 'w2'
  $r = CM @('-Message', 'ci: edit workflow', '-Paths', './.github/') $d
  Expect 'pitfall: ./.github/ keeps its leading dot' (($r.code -eq 0) -and (((& git -C $d show --name-only --format= HEAD) -join ',') -eq '.github/w.yml'))
  W $d '.github\w.yml' 'w3'
  $r = CM @('-Message', 'ci: edit workflow again', '-Paths', '.github\w.yml') $d
  Expect 'pitfall: .github\w.yml with a backslash keeps its leading dot' (($r.code -eq 0) -and (((& git -C $d show --name-only --format= HEAD) -join ',') -eq '.github/w.yml'))
  Expect 'pitfall: the source does not use TrimStart with ./' ($src -notmatch "TrimStart\(\s*'\./'")

  # push
  $r = CM @('-Message', 'feat: edit a', '-Paths', 'a.txt', '-Push') $d
  Expect '-Push succeeds' (($r.code -eq 0) -and ($r.out -match 'PUSH: ok'))
  G $e.c2 @('fetch', '-q')
  Expect 'the remote received the commit' ((& git -C $e.c2 rev-list --count origin/main) -eq '5')

  # remote has new commits -> STOP
  G $e.c2 @('pull', '-q', '--ff-only'); W $e.c2 'r.txt' 'r'; G $e.c2 @('add', '-A'); G $e.c2 @('commit', '-q', '-m', 'r'); G $e.c2 @('push', '-q')
  W $d 'a.txt' 'a3'
  $r = CM @('-Message', 'feat: edit a again', '-Paths', 'a.txt', '-Push') $d
  Expect 'newer remote -> STOP, local commit stays' (($r.code -eq 2) -and ($r.out -match 'new commit') -and ((& git -C $d log -1 --format=%s) -eq 'feat: edit a again'))

  # agent trailer in the message -> push cancelled
  $e = New-Env; $d = $e.c1
  W $d 'a.txt' 'a2'
  $r = CM @('-Message', "feat: x`n`nCo-Authored-By: Bot <b@b>", '-Paths', 'a.txt', '-Push') $d
  Expect 'agent trailer -> push cancelled' (($r.code -eq 2) -and ($r.out -match 'trailer'))
  Expect 'trailer: the remote did not change' ((& git -C $d rev-list --count origin/main) -eq '1')

  # different identity -> push cancelled
  $e = New-Env; $d = $e.c1
  W $d 'a.txt' 'a2'
  $env:GIT_AUTHOR_NAME = 'Bot'; $env:GIT_AUTHOR_EMAIL = 'bot@x'
  $r = CM @('-Message', 'feat: x', '-Paths', 'a.txt', '-Push') $d
  Remove-Item Env:GIT_AUTHOR_NAME, Env:GIT_AUTHOR_EMAIL -ErrorAction SilentlyContinue
  Expect 'different author identity -> push cancelled' (($r.code -eq 2) -and ($r.out -match 'identity'))

  # hidden mode: a path excluded from the project history is not committed here
  $e = New-Env; $d = $e.c1
  Add-Content (Join-Path $d '.git\info\exclude') "`nAGENTS.md`n"
  W $d 'AGENTS.md' 'rules'
  $r = CM @('-Message', 'docs: rules', '-Paths', 'AGENTS.md') $d
  Expect 'hidden mode: an excluded path points to agentic-sync commit' (($r.code -eq 1) -and ($r.out -match 'agentic-sync commit'))
} finally {
  Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item Env:GIT_AUTHOR_NAME, Env:GIT_AUTHOR_EMAIL -ErrorAction SilentlyContinue
}
if ($fail -gt 0) { exit 1 } else { exit 0 }
