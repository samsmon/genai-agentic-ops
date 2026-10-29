# Mid-session status / resume brief (read-only). Answers the one-word messages "status" and "resume".
#   -Mode status  git state, OPS locks, unfinished discussion files, review queue
#   -Mode resume  status plus the resume point from the state file
# No fetch: fast and works offline. Writes nothing.
# Config (env or parameter): STATE_FILE (default NOW.md), OPS_FILE (default docs/CURRENT_OPS.md),
#   REVIEW_HEADING (default "Awaiting review"; "Belum di-review" is always accepted too),
#   STATUS_WIP_GLOBS (comma list of folder globs with front matter "status:", default below).
# Works in hidden mode: it reads working-tree files and never needs them tracked in the project history.
param(
  [ValidateSet('status', 'resume')][string]$Mode = 'status',
  [string]$Root = '',
  [string]$OpsFile = '',
  [string]$StateFile = '',
  [string]$ReviewHeading = ''
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
if (-not $OpsFile) { $OpsFile = if ($env:OPS_FILE) { $env:OPS_FILE } else { 'docs/CURRENT_OPS.md' } }
if (-not $StateFile) { $StateFile = if ($env:STATE_FILE) { $env:STATE_FILE } else { 'NOW.md' } }
if (-not $ReviewHeading) { $ReviewHeading = if ($env:REVIEW_HEADING) { $env:REVIEW_HEADING } else { 'Awaiting review' } }
$wipGlobs = if ($env:STATUS_WIP_GLOBS) { @($env:STATUS_WIP_GLOBS -split ',' | Where-Object { $_.Trim() }) } else { @('projects/*/discussion/*.md', 'research/*.md', 'docs/discussion/*.md', 'docs/research/*.md') }

function Invoke-Git { & git -C $Root @args }
function Cut([string]$s, [int]$n) { if ($s.Length -gt $n) { return $s.Substring(0, $n) + '...' } return $s }
function Read-Lines([string]$rel) {
  $p = Join-Path $Root $rel
  if (Test-Path -LiteralPath $p) { return @(Get-Content -LiteralPath $p -Encoding UTF8) }
  return @()
}
function Get-Section([string[]]$lines, [string[]]$headings) {
  $out = @(); $on = $false
  foreach ($l in $lines) {
    if ($l -match '^## ') { $on = ($headings -contains $l.Trim()); continue }
    if ($on) { $out += $l }
  }
  return $out
}

Write-Output "[MODE] $Mode"

Write-Output '[GIT] (no fetch)'
$branch = (Invoke-Git rev-parse --abbrev-ref HEAD 2>$null)
Invoke-Git rev-parse --abbrev-ref '@{u}' 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
  $ahead = [int](Invoke-Git rev-list --count '@{u}..HEAD')
  $behind = [int](Invoke-Git rev-list --count 'HEAD..@{u}')
  Write-Output "branch $branch, ahead $ahead, behind $behind"
} else {
  Write-Output "branch $branch, no upstream"
}
$changed = @(Invoke-Git status --porcelain --untracked-files=no)
if ($changed.Count -eq 0) { Write-Output 'tracked: clean' }
else {
  Write-Output "tracked: $($changed.Count) file(s) changed"
  $changed | Select-Object -First 12 | ForEach-Object { Write-Output "  $_" }
  if ($changed.Count -gt 12) { Write-Output "  ... +$($changed.Count - 12) more" }
}
$untracked = @(Invoke-Git ls-files --others --exclude-standard)
if ($untracked.Count -gt 0) { Write-Output "untracked: $($untracked.Count) file(s) (info)" }

Write-Output '[OPS]'
$found = 0
$inArchive = $false
foreach ($line in (Read-Lines $OpsFile)) {
  if ($line -match '^## Archive') { $inArchive = $true; continue }
  if ($inArchive -or $line -notmatch '^\|') { continue }
  $c = $line.Split('|')
  if ($c.Count -lt 7) { continue }
  $st = $c[5].Trim().Trim('`').ToLower()
  if ($st -ne 'running' -and $st -ne 'blocked') { continue }
  $found++
  $mark = ''
  if ($st -eq 'running') {
    $ts = [datetime]::MinValue
    if ([datetime]::TryParseExact($c[1].Trim(), 'yyyy-MM-dd HH:mm', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$ts)) {
      if (((Get-Date) - $ts).TotalHours -gt 2) { $mark = '  <<STALE>>' }
    }
  }
  Write-Output ((Cut $line 200) + $mark)
}
if ($found -eq 0) { Write-Output '(no running/blocked rows)' }

Write-Output '[WIP] discussion/research files not yet status: done (5 newest)'
$cands = @()
foreach ($pat in $wipGlobs) {
  $cands += @(Get-ChildItem -Path (Join-Path $Root ($pat.Trim() -replace '/', '\')) -File -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch '[\\/]_template[\\/]' })
}
$wip = @()
foreach ($f in ($cands | Sort-Object LastWriteTime -Descending)) {
  $head = @(Get-Content -LiteralPath $f.FullName -Encoding UTF8 -TotalCount 15)
  $s = $head | Where-Object { $_ -match '^status:\s*(\S+)' } | Select-Object -First 1
  if ($s -and ($s -notmatch '^status:\s*done\b')) {
    $rel = $f.FullName.Substring((Resolve-Path -LiteralPath $Root).Path.Length).TrimStart('\', '/') -replace '\\', '/'
    $wip += "$rel ($(($s -replace '^status:\s*', '').Trim()))"
    if ($wip.Count -ge 5) { break }
  }
}
if ($wip.Count -eq 0) { Write-Output '(none)' } else { $wip | ForEach-Object { Write-Output "  $_" } }

$stateLines = Read-Lines $StateFile
$unrev = @(Get-Section $stateLines @("## $ReviewHeading", '## Awaiting review', '## Belum di-review') | Where-Object { $_ -match '^- ' }).Count
Write-Output "[REVIEW] $unrev item(s) awaiting review in $StateFile"

if ($Mode -eq 'resume') {
  Write-Output '[RESUME]'
  if ($stateLines.Count -eq 0) { Write-Output "$StateFile MISSING" }
  else {
    $upd = $stateLines | Where-Object { $_ -match '^\*\*(Last update|Update terakhir)' } | Select-Object -First 1
    if ($upd) { Write-Output (Cut $upd 300) }
    $focus = Get-Section $stateLines @('## Last focus', '## Fokus terakhir') | Where-Object { $_ -match '^\*\*' } | Select-Object -First 1
    if ($focus) { Write-Output "focus: $(Cut $focus 400)" }
    Get-Section $stateLines @('## Next step', '## Next steps') | Where-Object { $_ -match '^- ' } | Select-Object -First 3 | ForEach-Object { Write-Output "next: $(Cut $_ 220)" }
  }
  Write-Output '[FORMAT] State the resume point and the first next step, then ask the user which to continue. The data above is the source; do not guess.'
} else {
  Write-Output '[FORMAT] Answer briefly in four parts: Done / In progress / Next / Blockers. Fill them from this session''s task list and the data above. Write "unknown" for what is not known; do not guess.'
}
exit 0
