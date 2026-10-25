# genai-agentic-ops installer (PowerShell entry). The behaviour lives in install.py so the PowerShell and sh entries cannot drift.
# Dry run by default; add -Apply to write.
#   .\install.ps1 -Tools antigravity,claude -Modules guard,githooks,scripts -Shell ps -Visibility hidden -Policy agent-commits -Apply
param(
  [string[]]$Tools = @(),
  [string[]]$Modules = @('guard', 'githooks', 'scripts'),
  [ValidateSet('ps', 'sh')][string]$Shell = 'ps',
  [ValidateSet('hidden', 'visible')][string]$Visibility = 'hidden',
  [ValidateSet('agent-commits', 'user-only-git')][string]$Policy = 'agent-commits',
  [string]$Remote = '',
  [string]$KitDir = '',
  [string]$Pin = '',
  [string]$Project = (Get-Location).Path,
  [switch]$Apply,
  [switch]$Force,
  [switch]$LocalOnly,
  [switch]$SkipSync
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py = $null
foreach ($c in @('python', 'python3')) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($cmd) {
    $null = & $cmd.Source -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $cmd.Source; break }
  }
}
if (-not $py) { [Console]::Error.WriteLine('install: python 3 not found (the guard hooks need it too)'); exit 2 }
$args2 = @('-B', (Join-Path $PSScriptRoot 'install.py'),
  '--tools', ($Tools -join ','), '--modules', ($Modules -join ','), '--shell', $Shell,
  '--visibility', $Visibility, '--policy', $Policy, '--project', $Project)
if ($Remote) { $args2 += @('--remote', $Remote) }
if ($KitDir) { $args2 += @('--kit-dir', $KitDir) }
if ($Pin) { $args2 += @('--pin', $Pin) }
if ($Apply) { $args2 += '--apply' }
if ($Force) { $args2 += '--force' }
if ($LocalOnly) { $args2 += '--local-only' }
if ($SkipSync) { $args2 += '--skip-sync' }
& $py @args2
exit $LASTEXITCODE
