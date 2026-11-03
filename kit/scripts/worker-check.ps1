# agentic-ops worker-check (PowerShell entry): scope and verify checks after a worker reports DONE. The behaviour lives in worker-check.py.
# Usage: worker-check.ps1 snapshot -Out FILE [-Root DIR]
#        worker-check.ps1 check -Allow 'a,b,dir/' -Verify 'COMMAND' [-Since FILE] [-Root DIR] [-TimeoutSec N] [-Stat]
# -Allow and -Verify travel in environment variables, so a verify command with double quotes survives Windows PowerShell 5.1.
param(
  [Parameter(Position = 0, Mandatory = $true)][ValidateSet('snapshot', 'check')][string]$Mode,
  [string]$Allow = '', [string]$Verify = '', [string]$Since = '', [string]$Out = '',
  [string]$Root = '.', [int]$TimeoutSec = 600, [switch]$Stat
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
if (-not $py) { [Console]::Error.WriteLine('worker-check: python 3 not found'); exit 2 }
$a = @('-B', (Join-Path $PSScriptRoot 'worker-check.py'), $Mode, '--root', $Root)
if ($Mode -eq 'snapshot') {
  if (-not $Out) { [Console]::Error.WriteLine('worker-check: snapshot needs -Out FILE'); exit 2 }
  $a += @('--out', $Out)
} else {
  $env:WORKER_CHECK_ALLOW = $Allow
  $env:WORKER_CHECK_VERIFY = $Verify
  if ($Since) { $a += @('--since', $Since) }
  $a += @('--timeout', [string]$TimeoutSec)
  if ($Stat) { $a += '--stat' }
}
& $py @a
exit $LASTEXITCODE
