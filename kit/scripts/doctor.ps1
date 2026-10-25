# agentic-ops doctor (PowerShell entry): read-only report, one PASS/WARN/FAIL/UNKNOWN line per check. The behaviour lives in doctor.py.
# Usage: doctor.ps1 [-Project DIR] [-Pin SHA]
param([string]$Project = '', [string]$Pin = '')
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$py = $null
foreach ($c in @('python', 'python3')) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($cmd) {
    $null = & $cmd.Source -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $cmd.Source; break }
  }
}
if (-not $py) { [Console]::Error.WriteLine('doctor: python 3 not found'); exit 2 }
$a = @('-B', (Join-Path $PSScriptRoot 'doctor.py'))
if ($Project) { $a += @('--project', $Project) }
if ($Pin) { $a += @('--pin', $Pin) }
& $py @a
exit $LASTEXITCODE
