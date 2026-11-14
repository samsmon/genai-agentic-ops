<#
.SYNOPSIS
  Headless read-only query to another AI agent CLI (agy / claude) using plan mode.
.EXAMPLE
  scripts/agentic-ops/ask-agent.ps1 -Agent agy -Prompt 'Review this diff' -Files a.md,b.md
  scripts/agentic-ops/ask-agent.ps1 -Agent agy -Prompt 'Analyze architecture' -OutFile handoff/agy/x.out.md
.NOTES
  Enforces read-only plan mode. Uses user's existing CLI subscription; requires no external API key.
#>
param(
  [Parameter(Mandatory)][ValidateSet('agy', 'claude')][string]$Agent,
  [Parameter(Mandatory)][string]$Prompt,
  [string[]]$Files = @(),
  [string]$Model = '',
  [string]$OutFile = '',
  [int]$TimeoutSec = 300
)
$ErrorActionPreference = 'Stop'

function Resolve-Cli([string]$name) {
  $c = Get-Command $name -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  if ($name -eq 'agy') {
    $p = Join-Path $env:LOCALAPPDATA 'agy\bin\agy.exe'
    if (Test-Path -LiteralPath $p) { return $p }
  }
  throw "CLI '$name' not found in PATH or standard installation directory."
}

$parts = @($Prompt)
foreach ($f in $Files) {
  if (-not (Test-Path -LiteralPath $f)) { throw "File not found: $f" }
  $parts += "`n--- $f ---`n" + (Get-Content -LiteralPath $f -Raw -Encoding utf8)
}
if ($MyInvocation.ExpectingInput) { $parts += "`n--- stdin ---`n" + (@($input) -join "`n") }
$full = $parts -join "`n"

$cli = Resolve-Cli $Agent
# Windows PowerShell 5.1 does not escape quotes when calling native executables; escape manually.
$argText = ($full -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1'
if ($full.Length -gt 24000) { throw "Prompt too long ($($full.Length) characters, limit is 24,000). Reduce attachments in -Files." }
$argv = switch ($Agent) {
  'agy' {
    @('-p', $argText, '--mode', 'plan', '--print-timeout', "${TimeoutSec}s") +
      $(if ($Model) { @('--model', $Model) })
  }
  'claude' {
    @('-p', '--permission-mode', 'plan') +
      $(if ($Model) { @('--model', $Model) })
  }
}

$tmp = New-TemporaryFile
try {
  Set-Content -LiteralPath $tmp -Value $full -Encoding utf8
  $job = Start-Job {
    param($c, $v, $p, $agent)
    if ($agent -eq 'agy') { & $c @v 2>&1 } else { Get-Content -LiteralPath $p -Raw -Encoding utf8 | & $c @v 2>&1 }
  } -ArgumentList $cli, $argv, $tmp.FullName, $Agent
  if (-not (Wait-Job $job -Timeout ($TimeoutSec + 15))) {
    Stop-Job $job; Remove-Job $job -Force; throw "Timeout after $TimeoutSec seconds ($Agent)"
  }
  $out = Receive-Job $job
  Remove-Job $job -Force
  if ($OutFile) {
    New-Item -ItemType Directory -Force (Split-Path -Parent $OutFile) | Out-Null
    Set-Content -LiteralPath $OutFile -Value $out -Encoding utf8
    "Saved: $OutFile"
  } else { $out }
} finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
