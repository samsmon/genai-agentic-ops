# Dot-sourced by the PowerShell test suites. The same suites run in two layouts:
#   kit layout       <kit>\tests, <kit>\scripts, <kit>\githooks, <kit>\handoff
#   installed layout <project>\scripts\agentic-ops\tests, scripts and handoff checks flat in scripts\agentic-ops,
#                    git hooks in <project>\.githooks                         (what kit/install.* produces)
# Sets: $Kit (parent of tests), $Sc (folder with the scripts), $Ho (folder with handoff-check), $Gh (folder with the git hooks),
#       $Hk (folder with the Claude Code hooks: <kit>\claude\hooks, or <project>\.claude\hooks), $Layout.
$Kit = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ((Test-Path -LiteralPath (Join-Path $Kit 'scripts')) -and (Test-Path -LiteralPath (Join-Path $Kit 'githooks'))) {
  $Sc = Join-Path $Kit 'scripts'; $Ho = Join-Path $Kit 'handoff'; $Gh = Join-Path $Kit 'githooks'; $Hk = Join-Path $Kit 'claude\hooks'; $Layout = 'kit'
} else {
  $Sc = $Kit; $Ho = $Kit; $Gh = Join-Path (Resolve-Path (Join-Path $Kit '..\..')).Path '.githooks'; $Hk = Join-Path (Resolve-Path (Join-Path $Kit '..\..')).Path '.claude\hooks'; $Layout = 'installed'
}
