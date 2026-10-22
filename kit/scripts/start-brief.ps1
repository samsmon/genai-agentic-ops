# Session start summary (read-only). Does not write, pull or summarize.
# Output sections: [GIT] sync, [OPS] running/blocked rows, [STATE] optional state file, [HOOK].
# Exit 2 (or a STOP: line) means stop and report to the user.
param(
  [string]$Root = '',
  [string]$OpsFile = 'docs\CURRENT_OPS.md',
  [string]$StateFile = 'NOW.md'    # optional; shown when present (handoff module), never required
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
$script:rc = 0

Write-Output '[GIT]'
$env:GIT_TERMINAL_PROMPT = '0'
& git -C $Root -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 fetch --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Output 'STOP:fetch failed (remote unreachable or missing)'
  $script:rc = 2
} else {
  & git -C $Root rev-parse --abbrev-ref '@{u}' 2>$null | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Write-Output 'NO_UPSTREAM (no remote tracking branch, sync check skipped)'
  } else {
    $ahead = [int](& git -C $Root rev-list --count '@{u}..HEAD')
    $behind = [int](& git -C $Root rev-list --count 'HEAD..@{u}')
    $dirty = @(& git -C $Root status --porcelain --untracked-files=no).Count -gt 0
    if ($ahead -gt 0 -and $behind -gt 0) { Write-Output "STOP:diverged (ahead $ahead, behind $behind)"; $script:rc = 2 }
    elseif ($ahead -gt 0) { Write-Output "STOP:ahead ($ahead commit(s) not pushed)"; $script:rc = 2 }
    elseif ($dirty) { Write-Output 'STOP:dirty (tracked changes not committed)'; $script:rc = 2 }
    elseif ($behind -gt 0) { Write-Output "BEHIND_CLEAN (behind $behind; safe: git pull --ff-only)" }
    else { Write-Output 'SYNC_OK' }
  }
}
& git -C $Root status -sb --untracked-files=no
$untracked = @(& git -C $Root ls-files --others --exclude-standard)
if ($untracked.Count -gt 0) {
  $shown = (($untracked | ForEach-Object { ($_ -split '/' | Select-Object -First 2) -join '/' }) | Select-Object -Unique -First 5) -join ', '
  Write-Output "untracked: $($untracked.Count) file(s) (info, not STOP): $shown"
}

Write-Output '[OPS]'
$opsPath = Join-Path $Root $OpsFile
if (-not (Test-Path -LiteralPath $opsPath)) {
  Write-Output "$($OpsFile -replace '\\','/') MISSING"
  $script:rc = 2
} else {
  $found = 0; $inArchive = $false
  foreach ($line in (Get-Content -LiteralPath $opsPath -Encoding UTF8)) {
    if ($line -match '^## Archive') { $inArchive = $true; continue }
    if ($line -notmatch '^\|') { continue }
    $c = $line.Split('|')
    if ($c.Count -lt 7) { continue }
    $status = $c[5].Trim().Trim('`').ToLower()
    if ($status -ne 'running' -and $status -ne 'blocked') { continue }
    $found++
    $mark = ''
    if ($status -eq 'running') {
      $ts = [datetime]::MinValue
      if ([datetime]::TryParseExact($c[1].Trim(), 'yyyy-MM-dd HH:mm', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$ts)) {
        if (((Get-Date) - $ts).TotalHours -gt 2) { $mark = '  <<STALE>>' }
      } else { $mark = '  <<TIMESTAMP?>>' }
    }
    if ($inArchive) { $mark += '  <<IN-ARCHIVE>>' }
    Write-Output ($line + $mark)
  }
  if ($found -eq 0) { Write-Output '(none)' }
}

$statePath = Join-Path $Root $StateFile
if (Test-Path -LiteralPath $statePath) {
  Write-Output '[STATE]'
  Get-Content -LiteralPath $statePath -Encoding UTF8 | ForEach-Object { Write-Output $_ }
}

Write-Output '[HOOK]'
$h = & git -C $Root config core.hooksPath 2>$null
if ($h -eq '.githooks') { Write-Output 'core.hooksPath=.githooks OK' }
else { Write-Output "core.hooksPath=$h NOT ACTIVE (run: git config core.hooksPath .githooks)" }
exit $script:rc
