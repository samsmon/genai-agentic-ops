$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Sc 'agentic-sync.ps1')).Path
$base = Join-Path $env:TEMP ("synctest-" + [guid]::NewGuid())
New-Item -ItemType Directory $base | Out-Null
$env:GIT_AUTHOR_NAME = 't'; $env:GIT_AUTHOR_EMAIL = 't@example.test'; $env:GIT_COMMITTER_NAME = 't'; $env:GIT_COMMITTER_EMAIL = 't@example.test'
$utf8 = New-Object Text.UTF8Encoding $false
function G([string]$d, [string[]]$a) { & git -C $d @a 2>$null | Out-Null }
function Put([string]$path, [string]$text) {
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $path) | Out-Null
  [IO.File]::WriteAllText($path, $text + "`n", $utf8)
}
function Sync([string]$d, [string[]]$a) {
  Push-Location $d
  $o = & powershell -NoProfile -File $script @a 2>&1
  $c = $LASTEXITCODE
  Pop-Location
  return @{ code = $c; out = (($o | ForEach-Object { "$_" }) -join "`n") }
}
function New-Project([string]$name) {
  $bare = Join-Path $base "$name.git"; $c1 = Join-Path $base $name
  G $base @('init', '--bare', '-q', $bare); G $bare @('symbolic-ref', 'HEAD', 'refs/heads/main')
  G $base @('clone', '-q', $bare, $c1); G $c1 @('symbolic-ref', 'HEAD', 'refs/heads/main')
  G $c1 @('config', 'user.name', 't'); G $c1 @('config', 'user.email', 't@example.test')
  Put (Join-Path $c1 'README.md') 'hello'; Put (Join-Path $c1 'src\a.txt') 'code'
  G $c1 @('add', '-A'); G $c1 @('commit', '-q', '-m', 'chore: init'); G $c1 @('push', '-q', '-u', 'origin', 'main')
  Put (Join-Path $c1 'AGENTS.md') 'rules v1'; Put (Join-Path $c1 'CLAUDE.md') '@AGENTS.md'
  Put (Join-Path $c1 'docs\CURRENT_OPS.md') 'ops'; Put (Join-Path $c1 '.claude\settings.json') '{}'
  Put (Join-Path $c1 'scripts\agentic-ops\tool.sh') 'x'; Put (Join-Path $c1 '.githooks\pre-commit') '#!/bin/sh'
  return @{ bare = $bare; c1 = $c1 }
}
$fail = 0
function Expect([string]$name, [bool]$ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function Clean([string]$d) { return -not (@(& git -C $d status --porcelain)).Count }
try {
  $p = New-Project 'p1'
  $r = Sync $p.c1 @('init')
  Expect 'init: first device -> exit 0, ready' (($r.code -eq 0) -and ($r.out -match 'ready'))
  Expect 'init: list file and overlay git dir created' ((Test-Path (Join-Path $p.c1 '.agentic-files')) -and (Test-Path (Join-Path $p.c1 '.git\agentic')))
  Expect 'init: project git status stays clean' (Clean $p.c1)
  Expect 'init: ignore lives in info/exclude' ((Get-Content (Join-Path $p.c1 '.git\info\exclude') -Raw) -match 'BEGIN agentic-ops')
  $r = Sync $p.c1 @('init')
  $n = ([regex]::Matches((Get-Content (Join-Path $p.c1 '.git\info\exclude') -Raw), 'BEGIN agentic-ops')).Count
  Expect 'init: twice is safe, exclude block written once' (($r.code -eq 0) -and ($n -eq 1))

  $r = Sync $p.c1 @('commit', '-Message', 'chore: add agentic files')
  Expect 'commit: valid message accepted' (($r.code -eq 0) -and ($r.out -match 'Committed'))
  $r = Sync $p.c1 @('commit', '-Message', 'Update stuff')
  Expect 'commit: non-conforming message rejected' ($r.code -eq 1)
  $r = Sync $p.c1 @('commit', '-Message', '[claude] chore: add rules')
  Expect 'commit: bracket prefix rejected' ($r.code -eq 1)
  Put (Join-Path $p.c1 'AGENTS.md') 'rules v2'
  $r = Sync $p.c1 @('commit', '-Message', "docs: update rules`n`nCo-Authored-By: Someone <a@b.c>")
  Expect 'commit: agent attribution trailer rejected' ($r.code -eq 1)
  Expect 'project status still clean after editing an agentic file' (Clean $p.c1)
  $r = Sync $p.c1 @('commit', '-Message', 'docs: update rules')
  Expect 'commit: second commit with the edit' ($r.code -eq 0)
  # bytecode caches never enter the overlay and never count as an uncommitted change
  Put (Join-Path $p.c1 '.claude\hooks\__pycache__\guard.cpython-311.pyc') 'b'; Put (Join-Path $p.c1 '.claude\stray.pyc') 'b'
  Put (Join-Path $p.c1 '.claude\notes.md') 'notes'
  $r = Sync $p.c1 @('status', '-Brief')
  Expect 'status: .pyc and __pycache__ are not counted, the real edit is' ($r.out -match 'uncommitted=1 ahead')
  $r = Sync $p.c1 @('commit', '-Message', 'docs: add agent notes')
  $tracked = @(& git "--git-dir=$($p.c1)\.git\agentic" "--work-tree=$($p.c1)" ls-files) -join ' '
  Expect 'commit: __pycache__ and .pyc files are not added to the overlay' (($r.code -eq 0) -and ($tracked -notmatch '__pycache__|\.pyc'))
  $r = Sync $p.c1 @('status', '-Brief')
  Expect 'status after commit: clean even with bytecode on disk' ($r.out -match 'uncommitted=0 ahead')
  # sh is found in the Git for Windows folders when it is not on PATH
  $gitSh = @("$env:ProgramFiles\Git\bin\sh.exe", "$env:ProgramFiles\Git\usr\bin\sh.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  $gitCmd = "$env:ProgramFiles\Git\cmd"
  if ($gitSh -and (Test-Path $gitCmd)) {
    $savedPath = $env:Path
    $env:Path = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0;$gitCmd"
    $noSh = -not (Get-Command sh -ErrorAction SilentlyContinue)
    $r = Sync $p.c1 @('commit', '-Message', 'Update stuff')
    $env:Path = $savedPath
    Expect 'commit: sh is found in Program Files\Git when it is not on PATH (bad message still rejected)' ($noSh -and ($r.code -eq 1) -and ($r.out -notmatch 'sh not found'))
  } else { Write-Output 'SKIP sh lookup test (Git for Windows not in Program Files)' }
  $wc = (Resolve-Path (Join-Path $Sc 'wrap-check.ps1')).Path
  function Wrap([string]$d) { return ((& powershell -NoProfile -File $wc -Root $d -Agent claude-code -Today 2026-01-01) -join "`n") }
  Expect 'wrap-check: unpushed overlay commits -> FAIL' ((Wrap $p.c1) -match 'FAIL\s+OVERLAY: \d+ overlay commit')
  $r = Sync $p.c1 @('commit')
  Expect 'commit: nothing changed (default message) -> nothing to commit' (($r.code -eq 0) -and ($r.out -match 'Nothing to commit'))
  $r = Sync $p.c1 @('push')
  Expect 'push: overlay branch pushed' (($r.code -eq 0) -and ($r.out -match 'Pushed'))
  Expect 'wrap-check: committed and pushed overlay -> OK' ((Wrap $p.c1) -match 'OK\s+OVERLAY: clean and pushed')
  $heads = (& git -C $p.bare for-each-ref --format='%(refname)' refs/heads)
  Expect 'push: remote has agentic-ops and main' (($heads -contains 'refs/heads/agentic-ops') -and ($heads -contains 'refs/heads/main'))
  $mainFiles = (& git -C $p.bare ls-tree -r main --name-only) -join ' '
  Expect 'project branch main on the remote holds no agentic file' ($mainFiles -notmatch 'AGENTS|CLAUDE|CURRENT_OPS|\.claude|\.githooks|agentic')
  $ovFiles = (& git -C $p.bare ls-tree -r agentic-ops --name-only) -join ' '
  Expect 'overlay branch holds AGENTS.md and not the project code' (($ovFiles -match 'AGENTS\.md') -and ($ovFiles -notmatch 'src/a\.txt'))

  $c2 = Join-Path $base 'p1-device2'
  G $base @('clone', '-q', $p.bare, $c2); G $c2 @('config', 'user.name', 't'); G $c2 @('config', 'user.email', 't@example.test')
  Expect 'device 2: a plain clone has no agentic files' (-not (Test-Path (Join-Path $c2 'AGENTS.md')))
  $r = Sync $c2 @('init')
  Expect 'device 2: init restores the files' (($r.code -eq 0) -and ($r.out -match 'Restored') -and ((Get-Content (Join-Path $c2 'AGENTS.md') -Raw).Trim() -eq 'rules v2'))
  Expect 'device 2: project status clean after restore' (Clean $c2)
  Put (Join-Path $p.c1 'AGENTS.md') 'rules v3'
  Expect 'wrap-check: uncommitted agentic file -> FAIL' ((Wrap $p.c1) -match 'FAIL\s+OVERLAY: \d+ agentic file')
  $null = Sync $p.c1 @('commit', '-Message', 'docs: rules v3'); $null = Sync $p.c1 @('push')
  $r = Sync $c2 @('pull')
  Expect 'device 2: pull fast-forwards and updates the file' (($r.code -eq 0) -and ((Get-Content (Join-Path $c2 'AGENTS.md') -Raw).Trim() -eq 'rules v3'))

  Put (Join-Path $p.c1 'docs\CURRENT_OPS.md') 'from c1'; $null = Sync $p.c1 @('commit', '-Message', 'chore(ops): c1 row'); $null = Sync $p.c1 @('push')
  Put (Join-Path $c2 'docs\CURRENT_OPS.md') 'from c2'; $null = Sync $c2 @('commit', '-Message', 'chore(ops): c2 row')
  $r = Sync $c2 @('push')
  Expect 'push: remote has newer commits -> exit 5, not forced' ($r.code -eq 5)
  $r = Sync $c2 @('pull')
  Expect 'pull: diverged -> exit 5, local file untouched' (($r.code -eq 5) -and ((Get-Content (Join-Path $c2 'docs\CURRENT_OPS.md') -Raw).Trim() -eq 'from c2'))

  $c3 = Join-Path $base 'p1-device3'
  G $base @('clone', '-q', $p.bare, $c3); G $c3 @('config', 'user.name', 't'); G $c3 @('config', 'user.email', 't@example.test')
  Put (Join-Path $c3 'AGENTS.md') 'my own rules'
  $r = Sync $c3 @('init')
  Expect 'init: differing local file -> exit 4, file untouched' (($r.code -eq 4) -and ((Get-Content (Join-Path $c3 'AGENTS.md') -Raw).Trim() -eq 'my own rules'))
  $r = Sync $c3 @('init', '-Overwrite')
  $bk = @(Get-ChildItem (Join-Path $c3 '.git\agentic') -Directory -Filter 'backup-*')
  Expect 'init -Overwrite: replaced and backed up' (($r.code -eq 0) -and ((Get-Content (Join-Path $c3 'AGENTS.md') -Raw).Trim() -eq 'rules v3') -and ($bk.Count -eq 1) -and ((Get-Content (Join-Path $bk[0].FullName 'AGENTS.md') -Raw).Trim() -eq 'my own rules'))

  $p2 = New-Project 'p2'
  G $p2.c1 @('add', 'AGENTS.md'); G $p2.c1 @('commit', '-q', '-m', 'docs: add rules')
  $r = Sync $p2.c1 @('init')
  Expect 'init: tracked in the project history -> exit 3, nothing created' (($r.code -eq 3) -and ($r.out -match 'AGENTS\.md') -and (-not (Test-Path (Join-Path $p2.c1 '.git\agentic'))))

  $p3 = New-Project 'p3'
  $ov = Join-Path $base 'p3-overlay.git'; G $base @('init', '--bare', '-q', $ov)
  $r = Sync $p3.c1 @('init', '-Remote', $ov)
  Expect 'separate remote: init ok' ($r.code -eq 0)
  $null = Sync $p3.c1 @('commit', '-Message', 'chore: add agentic files'); $null = Sync $p3.c1 @('push')
  $ovHeads = (& git -C $ov for-each-ref --format='%(refname)' refs/heads); $pHeads = (& git -C $p3.bare for-each-ref --format='%(refname)' refs/heads)
  Expect 'separate remote: overlay branch only in the overlay repo' (($ovHeads -contains 'refs/heads/agentic-ops') -and ($pHeads -notcontains 'refs/heads/agentic-ops'))

  $p4 = New-Project 'p4'
  $r = Sync $p4.c1 @('init', '-Remote', (Join-Path $base 'does-not-exist.git'))
  Expect 'unreachable overlay remote -> exit 6' ($r.code -eq 6)
  $r = Sync $p4.c1 @('init', '-Remote', (Join-Path $base 'does-not-exist.git'), '-LocalOnly')
  Expect 'init -LocalOnly works without the remote' ($r.code -eq 0)

  $p6 = New-Project 'p6'
  $r = Sync $p6.c1 @('pull')
  Expect 'pull before init -> exit 2' ($r.code -eq 2)
  $r = Sync $p6.c1 @('status', '-Brief')
  Expect 'status -Brief before init -> not initialised' ($r.out -match 'not initialised')
  $r = Sync $p.c1 @('status', '-Brief')
  Expect 'status -Brief after init -> branch and counts' ($r.out -match 'OVERLAY: agentic-ops uncommitted=\d+ ahead=\d+ behind=\d+')
  $sb = (Resolve-Path (Join-Path $Sc 'start-brief.ps1')).Path
  $o = (& powershell -NoProfile -File $sb -Root $p.c1) -join "`n"
  Expect 'start-brief: [OVERLAY] section shown once the overlay exists' (($o -match '\[OVERLAY\]') -and ($o -match 'OVERLAY: agentic-ops'))
  $o = (& powershell -NoProfile -File $sb -Root $p6.c1) -join "`n"
  Expect 'start-brief: no [OVERLAY] section before init' ($o -notmatch '\[OVERLAY\]')
  $r = Sync $p6.c1 @('bogus')
  Expect 'unknown command -> usage, exit 2' ($r.code -eq 2)
} finally {
  Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
}
if ($fail -eq 0) { Write-Output 'ALL TESTS PASSED' } else { Write-Output "$fail FAILED" }
exit $(if ($fail -eq 0) { 0 } else { 1 })
