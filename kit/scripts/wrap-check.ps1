# End-of-session check (read-only). Writes nothing.
# Checks: ops log (no running rows of this agent, at most 5 finished rows in the main table) and git state.
# When handoff-check.ps1 sits next to this script (handoff module), it runs too and its failures count.
param(
  [string]$Root = '',
  [string]$Agent = 'claude-code',   # must match the Agent column spelling in the ops log
  [string]$Today = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$OpsFile = 'docs\CURRENT_OPS.md',
  [ValidateSet('user-only-git', 'agent-commits')][string]$GitPolicy = 'agent-commits',
  [string[]]$Ignore = @()   # path patterns (-like) of tracked changes owned by another session, confirmed by the user
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
$Ignore = @($Ignore | ForEach-Object { $_ -split ',' } | Where-Object { $_ })   # -File does not pass arrays: split on comma
$script:bad = 0
function Ok([string]$m) { Write-Output "OK     $m" }
function No([string]$m) { Write-Output "FAIL   $m"; $script:bad++ }

# 1-2. ops log
$opsPath = Join-Path $Root $OpsFile
if (-not (Test-Path -LiteralPath $opsPath)) { No "OPS: $($OpsFile -replace '\\','/') not found" }
else {
  $mine = @(); $done = 0; $inArchive = $false
  foreach ($line in (Get-Content -LiteralPath $opsPath -Encoding UTF8)) {
    if ($line -match '^## Archive') { $inArchive = $true; continue }
    if ($line -notmatch '^\|') { continue }
    $c = $line.Split('|')
    if ($c.Count -lt 7) { continue }
    $status = $c[5].Trim().Trim('`').ToLower()
    if ($status -eq 'running' -and $c[2].Trim().ToLower() -eq $Agent.ToLower()) { $mine += $line }
    if (-not $inArchive -and $status -ne 'running' -and $status -ne 'blocked' -and $c[1].Trim() -match '^\d') { $done++ }
  }
  if ($mine.Count -gt 0) { No "OPS: $($mine.Count) running row(s) of $Agent not closed: $($mine[0])" } else { Ok "OPS: no running rows of $Agent" }
  if ($done -gt 5) { No "OPS: $done finished rows in the main table (max 5); move older ones to the archive file" } else { Ok "OPS: $done finished rows in the main table (max 5)" }
}

# 3. git
& git -C $Root rev-parse --abbrev-ref '@{u}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Ok 'GIT: no upstream (skipped)' }
else {
  $ahead = [int](& git -C $Root rev-list --count '@{u}..HEAD')
  $dirtyFiles = @()
  foreach ($p in (& git -C $Root -c core.quotepath=off status --porcelain --untracked-files=no)) {
    $path = $p.Substring(3)
    $skip = $false
    foreach ($pat in $Ignore) { if ($path -like $pat) { $skip = $true } }
    if (-not $skip) { $dirtyFiles += $path }
  }
  if ($GitPolicy -eq 'user-only-git') {
    Ok "GIT: user-only-git, $($dirtyFiles.Count) changed file(s) and $ahead unpushed commit(s) are for the user to commit"
  }
  elseif ($ahead -gt 0) { No "GIT: $ahead commit(s) not pushed" }
  elseif ($dirtyFiles.Count -gt 0) { No ("GIT: tracked changes not committed: " + (($dirtyFiles | Select-Object -First 5) -join ', ') + ". If they belong to another session, do not commit them: report to the user, then rerun with -Ignore '<path>'.") }
  else { Ok 'GIT: clean and pushed' }
}

# 4. optional handoff module
$handoff = Join-Path $PSScriptRoot 'handoff-check.ps1'
if (Test-Path -LiteralPath $handoff) {
  $o = & powershell -NoProfile -File $handoff -Root $Root -Agent $Agent -Today $Today
  foreach ($l in $o) { if ($l -notmatch '^\[HANDOFF\]') { Write-Output $l } ; if ($l -match '^FAIL') { $script:bad++ } }
}

Write-Output "[WRAP] $($script:bad) failed"
if ($script:bad -gt 0) { exit 1 } else { exit 0 }
