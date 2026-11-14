# Triage the awaiting-review queue (read-only): inspects state file (NOW.md),
# groups by project/agent, flags anomalies, and lists oldest items.
# Anomalies checked: missing files, missing front matter, status != done, already reviewed but still listed.
# Exit code: always 0 (informational report).
param(
  [string]$Root = '',
  [string]$StateFile = 'NOW.md',
  [int]$Top = 10
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }

$now = Join-Path $Root $StateFile
if (-not (Test-Path -LiteralPath $now)) { Write-Output "$StateFile MISSING"; exit 0 }
$on = $false; $items = @()
foreach ($l in (Get-Content -LiteralPath $now -Encoding UTF8)) {
  if ($l -match '^## ') {
    $heading = $l.Trim()
    $on = ($heading -eq '## Awaiting review' -or $heading -eq '## Belum di-review')
    continue
  }
  if ($on -and $l -match '^- ') { $items += $l }
}
Write-Output "[QUEUE] $($items.Count) item(s)"
if ($items.Count -eq 0) { exit 0 }

$today = (Get-Date).Date
$rows = @()
foreach ($l in $items) {
  $m = [regex]::Match($l, '^-\s+`?([^\s`()]+\.md)`?(?:\s+\((?:by|oleh)\s+([^)]+)\))?\s*[-:]?\s*(.*)$')
  if (-not $m.Success) { $rows += [pscustomobject]@{ Path = '?'; Project = '?'; Agent = '?'; Age = -1; Flags = @('UNPARSED'); Desc = $l.Substring(2) }; continue }
  $rel = $m.Groups[1].Value -replace '\\', '/'
  $agent = if ($m.Groups[2].Success) { $m.Groups[2].Value.Trim() } else { '?' }
  $parts = $rel -split '/'
  $project = if ($parts[0] -eq 'projects' -and $parts.Count -gt 1) { $parts[1] } else { $parts[0] }
  $flags = @(); $age = -1
  $dm = [regex]::Match($rel, '(\d{4}-\d{2}-\d{2})')
  $full = Join-Path $Root $rel
  if (-not (Test-Path -LiteralPath $full)) { $flags += 'MISSING' }
  else {
    $head = @(Get-Content -LiteralPath $full -Encoding UTF8 -TotalCount 20)
    $st = $head | Where-Object { $_ -match '^status:\s*(\S+)' } | Select-Object -First 1
    $rb = $head | Where-Object { $_ -match '^reviewed_by:\s*\[(.*?)\]' } | Select-Object -First 1
    if (-not $st -and -not $rb) { $flags += 'NO-FRONTMATTER' }
    else {
      if ($st -and $st -notmatch '^status:\s*done\b') { $flags += 'NOT-DONE' }
      if ($rb -and ([regex]::Match($rb, '\[(.*?)\]').Groups[1].Value.Trim() -ne '')) { $flags += 'ALREADY-REVIEWED' }
    }
    $d = if ($dm.Success) { [datetime]::ParseExact($dm.Groups[1].Value, 'yyyy-MM-dd', $null) } else { (Get-Item -LiteralPath $full).LastWriteTime.Date }
    $age = [int]($today - $d).TotalDays
  }
  if ($age -lt 0 -and $dm.Success) { $age = [int]($today - [datetime]::ParseExact($dm.Groups[1].Value, 'yyyy-MM-dd', $null)).TotalDays }
  $desc = $m.Groups[3].Value.Trim(); if ($desc.Length -gt 90) { $desc = $desc.Substring(0, 90) + '...' }
  $rows += [pscustomobject]@{ Path = $rel; Project = $project; Agent = $agent; Age = $age; Flags = $flags; Desc = $desc }
}

Write-Output '[PROJECT]'
$rows | Group-Object Project | Sort-Object Count -Descending | ForEach-Object { Write-Output ("  {0,-22} {1}" -f $_.Name, $_.Count) }
Write-Output '[AGENT]'
$rows | Group-Object Agent | Sort-Object Count -Descending | ForEach-Object { Write-Output ("  {0,-22} {1}" -f $_.Name, $_.Count) }

Write-Output '[FLAGS] anomalies (clean up before review)'
$bad = @($rows | Where-Object { $_.Flags.Count -gt 0 })
if ($bad.Count -eq 0) { Write-Output '  (none)' }
else { $bad | ForEach-Object { Write-Output ("  {0}  {1}" -f ($_.Flags -join ','), $_.Path) } }

Write-Output "[OLDEST] $Top oldest item(s)"
$rows | Where-Object { $_.Age -ge 0 } | Sort-Object Age -Descending | Select-Object -First $Top | ForEach-Object {
  Write-Output ("  {0,3}d  {1}  [{2}]  {3}" -f $_.Age, $_.Path, $_.Agent, $_.Desc)
}
exit 0
