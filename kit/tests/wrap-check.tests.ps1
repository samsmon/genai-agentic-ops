$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$kit = Join-Path $PSScriptRoot '..'
$base = Join-Path $env:TEMP ("wctest-" + [guid]::NewGuid())
$env:GIT_AUTHOR_NAME = 't'; $env:GIT_AUTHOR_EMAIL = 't@t'; $env:GIT_COMMITTER_NAME = 't'; $env:GIT_COMMITTER_EMAIL = 't@t'
$today = '2026-10-11'
# installed layout: wrap-check and handoff-check live in the same directory
$inst = Join-Path $base 'installed'
function Install([bool]$withHandoff) {
  New-Item -ItemType Directory $inst -Force | Out-Null
  Copy-Item (Join-Path $kit 'scripts\wrap-check.ps1') $inst -Force
  if ($withHandoff) { Copy-Item (Join-Path $kit 'handoff\handoff-check.ps1') $inst -Force }
}
function G([string]$d, [string[]]$a) { & git -C $d @a 2>$null | Out-Null }
function Row([string]$status, [string]$agent = 'claude-code') { return "| 2026-10-11 10:00 | $agent | main | x | $status | task |`n" }
function New-Env([string]$rows = '') {
  Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory $base | Out-Null
  $bare = Join-Path $base 'bare.git'; $c1 = Join-Path $base 'c1'
  G $base @('init', '--bare', '-q', $bare)
  G $bare @('symbolic-ref', 'HEAD', 'refs/heads/main')
  G $base @('clone', '-q', $bare, $c1)
  G $c1 @('symbolic-ref', 'HEAD', 'refs/heads/main')
  New-Item -ItemType Directory (Join-Path $c1 'docs') | Out-Null
  $hdr = "| Timestamp | Agent | ID | Target | Status | Task |`n|---|---|---|---|---|---|`n"
  Set-Content (Join-Path $c1 'docs\CURRENT_OPS.md') ("# OPS`n" + $hdr + $rows + "## Archive`n" + $hdr) -Encoding UTF8
  G $c1 @('add', '-A'); G $c1 @('commit', '-q', '-m', 'init'); G $c1 @('push', '-q', '-u', 'origin', 'main')
  Install $false
  return $c1
}
function Wrap([string]$d, [string[]]$extra = @()) { $o = & powershell -NoProfile -File (Join-Path $inst 'wrap-check.ps1') -Root $d -Agent 'claude-code' -Today $today @extra; return @{ code = $LASTEXITCODE; out = ($o -join "`n") } }
$fail = 0
function Expect([string]$name, [bool]$ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }

$c = New-Env; $r = Wrap $c
Expect 'all good -> exit 0, 0 failed' (($r.code -eq 0) -and ($r.out -cnotmatch 'FAIL') -and ($r.out -match '\[WRAP\] 0 failed'))
$c = New-Env (Row 'running'); $r = Wrap $c
Expect 'own running row -> FAIL, exit 1' (($r.code -eq 1) -and ($r.out -match 'FAIL.*OPS'))
$c = New-Env (Row 'Running'); $r = Wrap $c
Expect 'status Running (capitalised) still FAIL' (($r.code -eq 1) -and ($r.out -match 'FAIL.*OPS'))
$c = New-Env (Row 'running' 'gemini'); $r = Wrap $c
Expect "another agent's running row -> no FAIL" ($r.code -eq 0)
$c = New-Env ((Row 'done') * 6); $r = Wrap $c
Expect '6 finished rows in main table -> FAIL' (($r.code -eq 1) -and ($r.out -match 'FAIL.*OPS'))
$c = New-Env ((Row 'done') * 5); $r = Wrap $c
Expect '5 finished rows -> pass' ($r.code -eq 0)
$c = New-Env; Add-Content (Join-Path $c 'docs\CURRENT_OPS.md') (Row 'running'); $r = Wrap $c
Expect 'own running row under Archive -> still FAIL' (($r.code -eq 1) -and ($r.out -match 'FAIL.*OPS'))

$c = New-Env; Set-Content (Join-Path $c 'z.txt') 'z' -Encoding UTF8; G $c @('add', '-A'); G $c @('commit', '-q', '-m', 'z'); $r = Wrap $c
Expect 'unpushed commit -> FAIL git' (($r.code -eq 1) -and ($r.out -match 'FAIL.*GIT'))
$r = Wrap $c @('-GitPolicy', 'user-only-git')
Expect 'unpushed commit under user-only-git -> pass' (($r.code -eq 0) -and ($r.out -match 'user-only-git'))
$c = New-Env; Add-Content (Join-Path $c 'docs\CURRENT_OPS.md') 'edit'; $r = Wrap $c
Expect 'tracked change not committed -> FAIL git' (($r.code -eq 1) -and ($r.out -match 'FAIL.*GIT'))
$r = Wrap $c @('-GitPolicy', 'user-only-git')
Expect 'tracked change under user-only-git -> pass' ($r.code -eq 0)

$c = New-Env; New-Item -ItemType Directory (Join-Path $c 'other') | Out-Null; Set-Content (Join-Path $c 'other\doc.txt') 'a' -Encoding UTF8
G $c @('add', '-A'); G $c @('commit', '-q', '-m', 'other'); G $c @('push', '-q'); Add-Content (Join-Path $c 'other\doc.txt') 'edited by another session'
$r = Wrap $c
Expect "another session's change without -Ignore -> FAIL git naming the file" (($r.code -eq 1) -and ($r.out -match 'FAIL.*GIT.*other/doc\.txt'))
$r = Wrap $c @('-Ignore', 'other/*')
Expect '-Ignore pattern -> pass' ($r.code -eq 0)
$r = Wrap $c @('-Ignore', 'x/*,other/*')
Expect '-Ignore comma-separated patterns -> pass' ($r.code -eq 0)

# handoff module present next to wrap-check: its failures count
$c = New-Env; Install $true; $r = Wrap $c
Expect 'handoff installed, state file missing -> FAIL STATE and LOG, exit 1' (($r.code -eq 1) -and ($r.out -match 'FAIL.*STATE') -and ($r.out -match 'FAIL.*LOG'))

Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
if ($fail) { exit 1 } else { Write-Output 'ALL TESTS PASSED'; exit 0 }
