# Check (read-only) that .claude/commands/ and .agent/workflows/ pairs stay synchronized.
# Lines containing $ARGUMENTS, "argumen dari user", or similar argument markers may differ across tools.
param(
  [string]$Source = '',
  [string]$Dest   = '',
  [switch]$Check,
  [string]$Root   = ''
)
$ErrorActionPreference = 'Stop'
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
if (-not $Source) { $Source = Join-Path $Root '.claude\commands' }
if (-not $Dest)   { $Dest   = Join-Path $Root '.agent\workflows' }

if (-not (Test-Path -LiteralPath $Source) -or -not (Test-Path -LiteralPath $Dest)) {
  Write-Output 'INFO: one or both command/workflow directories do not exist; check skipped'
  exit 0
}

function Get-Core([string]$path) {
  @(Get-Content -LiteralPath $path -Encoding UTF8 | Where-Object { $_ -notmatch '\$ARGUMENTS|argumen dari user|argumen perintah|Kalau ada argumen' })
}
$src = @(Get-ChildItem -LiteralPath $Source -Filter *.md | ForEach-Object Name)
$dst = @(Get-ChildItem -LiteralPath $Dest -Filter *.md | ForEach-Object Name)
$bad = 0
foreach ($n in (@($src) + @($dst) | Sort-Object -Unique)) {
  if (($src -notcontains $n) -or ($dst -notcontains $n)) { Write-Output "MISSING: $n"; $bad++; continue }
  $a = Get-Core (Join-Path $Source $n)
  $b = Get-Core (Join-Path $Dest $n)
  if (($a -join "`n") -cne ($b -join "`n")) {
    Write-Output "DIFF: $n"
    if ($a.Count -and $b.Count) { Compare-Object $a $b | ForEach-Object { Write-Output "  $($_.SideIndicator) $($_.InputObject)" } }
    $bad++
  }
}
if ($bad) { exit 1 }
Write-Output 'OK: paired commands and workflows are synchronized'
exit 0
