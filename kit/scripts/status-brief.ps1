# Mid-session status and resume summary (read-only).
#   "status" / "progress" -> -Mode status  (git, active locks, WIP tasks, review queue)
#   "continue" / "resume" -> -Mode resume  (status + resume point from state file)
# Zero network calls: fast and works completely offline. Writes nothing.
param(
  [ValidateSet('status', 'resume')][string]$Mode = 'status',
  [string]$Root = '',
  [string]$OpsFile = 'docs\CURRENT_OPS.md',
  [string]$StateFile = 'NOW.md'
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }

function Cut([string]$s, [int]$n) { if ($s.Length -gt $n) { return $s.Substring(0, $n) + '...' } return $s }
function Read-Lines([string]$rel) {
  $p = Join-Path $Root $rel
  if (Test-Path -LiteralPath $p) { return @(Get-Content -LiteralPath $p -Encoding UTF8) }
  return @()
}
function Get-Section([string[]]$lines, [string]$heading) {
  $out = @(); $on = $false
  foreach ($l in $lines) {
    if ($l -match '^## ') { $on = ($l.Trim() -like "$heading*"); continue }
    if ($on) { $out += $l }
  }
  return $out
}

Write-Output "[MODE] $Mode"

Write-Output '[GIT] (local only, no fetch)'
$branch = (& git -C $Root rev-parse --abbrev-ref HEAD 2>$null)
& git -C $Root rev-parse --abbrev-ref '@{u}' 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
  $ahead = [int](& git -C $Root rev-list --count '@{u}..HEAD')
  $behind = [int](& git -C $Root rev-list --count 'HEAD..@{u}')
  Write-Output "branch $branch, ahead $ahead, behind $behind"
} else {
  Write-Output "branch $branch, no upstream"
}
$changed = @(& git -C $Root status --porcelain --untracked-files=no)
if ($changed.Count -eq 0) { Write-Output 'tracked: clean' }
else {
  Write-Output "tracked: $($changed.Count) changed file(s)"
  $changed | Select-Object -First 12 | ForEach-Object { Write-Output "  $_" }
  if ($changed.Count -gt 12) { Write-Output "  ... +$($changed.Count - 12) more" }
}
$untracked = @(& git -C $Root ls-files --others --exclude-standard)
if ($untracked.Count -gt 0) { Write-Output "untracked: $($untracked.Count) file(s) (informational)" }

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
      if (((Get-Date) - $ts).TotalHours -gt 2) { $mark = '  <<STALE LOCK (>2h)>>' }
    }
  }
  Write-Output ((Cut $line 200) + $mark)
}
if ($found -eq 0) { Write-Output '(no active running/blocked locks)' }

$nowLines = Read-Lines $StateFile
$unrev = @(Get-Section $nowLines '## Awaiting review' | Where-Object { $_ -match '^- ' }).Count
if ($unrev -eq 0) { $unrev = @(Get-Section $nowLines '## Belum di-review' | Where-Object { $_ -match '^- ' }).Count }
Write-Output "[REVIEW] $unrev item(s) awaiting review in $StateFile"

if ($Mode -eq 'resume') {
  Write-Output '[RESUME]'
  if ($nowLines.Count -eq 0) { Write-Output "$StateFile MISSING" }
  else {
    $upd = $nowLines | Where-Object { $_ -match '^(?:\*\*|\*|#)?\s*(?:Last update|Update terakhir)' } | Select-Object -First 1
    if ($upd) { Write-Output (Cut $upd 300) }
    $focus = Get-Section $nowLines '## Focus' | Where-Object { $_ -match '^\*\*' } | Select-Object -First 1
    if (-not $focus) { $focus = Get-Section $nowLines '## Fokus terakhir' | Where-Object { $_ -match '^\*\*' } | Select-Object -First 1 }
    if ($focus) { Write-Output "focus: $(Cut $focus 400)" }
    $nexts = Get-Section $nowLines '## Next' | Where-Object { $_ -match '^- ' } | Select-Object -First 3
    if ($nexts.Count -eq 0) { $nexts = Get-Section $nowLines '## Next step' | Where-Object { $_ -match '^- ' } | Select-Object -First 3 }
    $nexts | ForEach-Object { Write-Output "next: $(Cut $_ 220)" }
  }
}
exit 0
