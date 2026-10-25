$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Sc 'start-brief.ps1')).Path
$base = Join-Path $env:TEMP ("sbtest-" + [guid]::NewGuid())
$env:GIT_AUTHOR_NAME = 't'; $env:GIT_AUTHOR_EMAIL = 't@t'; $env:GIT_COMMITTER_NAME = 't'; $env:GIT_COMMITTER_EMAIL = 't@t'
$dash = [string][char]0x2014
function G([string]$d, [string[]]$a) { & git -C $d @a 2>$null | Out-Null }
function New-Env([string]$rows = '', [bool]$withState = $true) {
  Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory $base | Out-Null
  $bare = Join-Path $base 'bare.git'; $c1 = Join-Path $base 'c1'; $c2 = Join-Path $base 'c2'
  G $base @('init', '--bare', '-q', $bare)
  G $bare @('symbolic-ref', 'HEAD', 'refs/heads/main')
  G $base @('clone', '-q', $bare, $c1)
  G $c1 @('symbolic-ref', 'HEAD', 'refs/heads/main')
  New-Item -ItemType Directory (Join-Path $c1 'docs') | Out-Null
  if ($withState) { [IO.File]::WriteAllText((Join-Path $c1 'NOW.md'), "# NOW`nstate-body $dash ok`n", (New-Object Text.UTF8Encoding $false)) }
  $hdr = "| Timestamp | Agent | ID | Target | Status | Task |`n|---|---|---|---|---|---|`n"
  Set-Content (Join-Path $c1 'docs\CURRENT_OPS.md') ("# OPS`n" + $hdr + $rows + "## Archive`n" + $hdr + "| 2026-01-01 00:00 | a | m | x | done | archived-row |`n") -Encoding UTF8
  G $c1 @('add', '-A'); G $c1 @('commit', '-q', '-m', 'init'); G $c1 @('push', '-q', '-u', 'origin', 'main')
  G $base @('clone', '-q', $bare, $c2)
  return @{ c1 = $c1; c2 = $c2; bare = $bare }
}
function Commit-In([string]$d, [string]$file) {
  Set-Content (Join-Path $d $file) $file -Encoding UTF8
  G $d @('add', '-A'); G $d @('commit', '-q', '-m', $file)
}
function Brief([string]$d) { $o = & powershell -NoProfile -File $script -Root $d; return @{ code = $LASTEXITCODE; out = ($o -join "`n") } }
$fail = 0
function Expect([string]$name, [bool]$ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function Row([string]$ts, [string]$status, [string]$task) { return "| $ts | claude-code | main | x | $status | $task |`n" }
$fmt = 'yyyy-MM-dd HH:mm'

$e = New-Env; $r = Brief $e.c1
Expect 'in sync -> SYNC_OK, exit 0' (($r.code -eq 0) -and ($r.out -match 'SYNC_OK'))
Expect 'state file shown verbatim, non-ASCII intact' ($r.out -match ('state-body ' + $dash + ' ok'))
Expect 'hook not active is reported' ($r.out -match 'NOT ACTIVE')
G $e.c1 @('config', 'core.hooksPath', '.githooks'); $r = Brief $e.c1
Expect 'hook active -> OK' ($r.out -match 'core\.hooksPath=\.githooks OK')
Expect 'no rules file -> no [RULES] warning' ($r.out -notmatch '\[RULES\]')
Set-Content (Join-Path $e.c1 'AGENTS.md') ('x' * 25000) -Encoding ASCII -NoNewline; $r = Brief $e.c1
Expect 'AGENTS.md over 24000 B -> warning, still exit 0' (($r.code -eq 0) -and ($r.out -match '\[RULES\]') -and ($r.out -match 'Antigravity'))

$e = New-Env '' $false; $r = Brief $e.c1
Expect 'no state file -> still exit 0, no [STATE]' (($r.code -eq 0) -and ($r.out -notmatch '\[STATE\]'))

$e = New-Env; Commit-In $e.c2 'b.txt'; G $e.c2 @('push', '-q'); $r = Brief $e.c1
Expect 'behind and clean -> BEHIND_CLEAN, exit 0' (($r.code -eq 0) -and ($r.out -match 'BEHIND_CLEAN'))
$e = New-Env; Commit-In $e.c1 'a.txt'; $r = Brief $e.c1
Expect 'ahead -> STOP:ahead, exit 2' (($r.code -eq 2) -and ($r.out -match 'STOP:ahead'))
$e = New-Env; Commit-In $e.c2 'b.txt'; G $e.c2 @('push', '-q'); Commit-In $e.c1 'a.txt'; $r = Brief $e.c1
Expect 'diverged -> STOP:diverged, exit 2' (($r.code -eq 2) -and ($r.out -match 'STOP:diverged'))
$e = New-Env; Add-Content (Join-Path $e.c1 'NOW.md') 'changed'; $r = Brief $e.c1
Expect 'tracked change -> STOP:dirty, exit 2' (($r.code -eq 2) -and ($r.out -match 'STOP:dirty'))
$e = New-Env; Set-Content (Join-Path $e.c1 'new.txt') 'u'; $r = Brief $e.c1
Expect 'untracked only -> SYNC_OK, noted, exit 0' (($r.code -eq 0) -and ($r.out -match 'SYNC_OK') -and ($r.out -match 'new\.txt'))

$rows = (Row '2026-10-11 10:00' 'running' 'task-running') + (Row '2026-10-11 09:00' 'done' 'task-done') + (Row '2026-10-11 08:00' 'blocked' 'task-blocked')
$e = New-Env $rows; $r = Brief $e.c1
Expect 'OPS: running and blocked shown, done and archive not' (($r.out -match 'task-running') -and ($r.out -match 'task-blocked') -and ($r.out -notmatch 'task-done') -and ($r.out -notmatch 'archived-row'))
$e = New-Env (Row (Get-Date).AddHours(-3).ToString($fmt) 'running' 'old-one'); $r = Brief $e.c1
Expect 'OPS: running over 2 h -> STALE' ($r.out -match 'old-one.*<<STALE>>')
$e = New-Env (Row (Get-Date).AddMinutes(-10).ToString($fmt) 'running' 'fresh-one'); $r = Brief $e.c1
Expect 'OPS: fresh running row -> no STALE' (($r.out -match 'fresh-one') -and ($r.out -notmatch '<<STALE>>'))
$e = New-Env (Row 'sometime' 'running' 'odd-one'); $r = Brief $e.c1
Expect 'OPS: bad timestamp -> TIMESTAMP?, no crash' (($r.out -match 'odd-one.*<<TIMESTAMP\?>>') -and ($r.out -match '\[HOOK\]'))
$e = New-Env (Row '2026-10-11 10:00' 'Running' 'upper-case'); $r = Brief $e.c1
Expect 'OPS: status Running (capitalised) still shown' ($r.out -match 'upper-case')
$e = New-Env; $r = Brief $e.c1
Expect 'OPS: empty -> (none)' ($r.out -match '\(none\)')
$e = New-Env; Add-Content (Join-Path $e.c1 'docs\CURRENT_OPS.md') (Row '2026-10-11 10:00' 'running' 'hidden-in-archive'); $r = Brief $e.c1
Expect 'OPS: running row under Archive flagged IN-ARCHIVE' ($r.out -match 'hidden-in-archive.*<<IN-ARCHIVE>>')
$e = New-Env; Remove-Item (Join-Path $e.c1 'docs\CURRENT_OPS.md'); $r = Brief $e.c1
Expect 'OPS: log missing -> MISSING, exit 2' (($r.code -eq 2) -and ($r.out -match 'CURRENT_OPS\.md MISSING'))
$e = New-Env; Remove-Item $e.bare -Recurse -Force; $r = Brief $e.c1
Expect 'fetch failure -> STOP:fetch, exit 2, other sections still printed' (($r.code -eq 2) -and ($r.out -match 'STOP:fetch') -and ($r.out -match 'state-body'))

Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
if ($fail) { exit 1 } else { Write-Output 'ALL TESTS PASSED'; exit 0 }
