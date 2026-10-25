$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Ho 'handoff-check.ps1')).Path
$base = Join-Path $env:TEMP ("hctest-" + [guid]::NewGuid())
$today = '2026-10-11'
function New-Env([string]$nowDate = $today, [bool]$logLine = $true) {
  Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory (Join-Path $base 'log') | Out-Null
  Set-Content (Join-Path $base 'NOW.md') "# NOW`n`n**Last update:** $nowDate by claude-code`n`n## Next step`n- x`n" -Encoding UTF8
  $log = "# Log`n"; if ($logLine) { $log += "- $today [claude-code] x: summary`n" }
  Set-Content (Join-Path $base 'log\2026-10.md') $log -Encoding UTF8
}
function Check([string]$agent = 'claude-code') { $o = & powershell -NoProfile -File $script -Root $base -Agent $agent -Today $today; return @{ code = $LASTEXITCODE; out = ($o -join "`n") } }
function Add-Disc([string]$name, [string]$reviewed = '[]', [string]$status = 'done', [bool]$inState = $true) {
  $d = Join-Path $base 'projects\x\discussion'; New-Item -ItemType Directory $d -Force | Out-Null
  Set-Content (Join-Path $d $name) "---`ndate: 2026-10-11`nstatus: $status`nreviewed_by: $reviewed`n---`nbody`n" -Encoding UTF8
  if ($inState) { $np = Join-Path $base 'NOW.md'; $t = (Get-Content $np -Raw) + "`n## Awaiting review`n- projects/x/discussion/$name (by claude-code)`n"; Set-Content $np $t -Encoding UTF8 }
}
$fail = 0
function Expect([string]$name, [bool]$ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }

New-Env; $r = Check
Expect 'all good -> exit 0' (($r.code -eq 0) -and ($r.out -match '\[HANDOFF\] 0 failed'))
New-Env '2026-10-09'; $r = Check
Expect 'stale Last update -> FAIL STATE' (($r.code -eq 1) -and ($r.out -match 'FAIL.*STATE'))
New-Env; $r = Check 'gemini'
Expect 'Last update by another agent -> FAIL STATE and LOG' (($r.code -eq 1) -and ($r.out -match 'FAIL.*STATE') -and ($r.out -match 'FAIL.*LOG'))
New-Env $today $false; $r = Check
Expect 'no log line for today -> FAIL LOG' (($r.code -eq 1) -and ($r.out -match 'FAIL.*LOG'))
New-Env; Add-Disc 'a.md'; $r = Check
Expect 'unreviewed and listed -> pass' (($r.code -eq 0) -and ($r.out -match 'OK.*REVIEW'))
New-Env; Add-Disc 'a.md' '[]' 'done' $false; $r = Check
Expect 'unreviewed but not listed -> FAIL REVIEW' (($r.code -eq 1) -and ($r.out -match 'FAIL.*REVIEW'))
New-Env; Add-Disc 'a.md' '[gemini]'; $r = Check
Expect 'reviewed but still listed -> FAIL REVIEW' (($r.code -eq 1) -and ($r.out -match 'FAIL.*REVIEW'))
New-Env; Add-Disc 'a.md' '[gemini]' 'done' $false; $r = Check
Expect 'reviewed and not listed -> pass' ($r.code -eq 0)
New-Env; Add-Disc 'a.md' '[]' 'wip' $false; $r = Check
Expect 'wip file skipped -> pass' ($r.code -eq 0)

Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue
if ($fail) { exit 1 } else { Write-Output 'ALL TESTS PASSED'; exit 0 }
