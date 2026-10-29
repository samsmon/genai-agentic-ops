# Commit (and optionally push) only this session's files, with the checks of the rules (sections 8 and 9):
#   - -Paths must be explicit; "." and "*" are refused
#   - stops when files outside -Paths are staged (they belong to another session)
#   - commits with a pathspec, the message goes through a temporary file (the commit-msg hook still runs)
#   - -Push: git fetch, stops when the remote has new commits (no rebase or merge), checks identity and trailers, then pushes
#   - -DryRun: run the checks and show the stat, commit nothing
# Hidden mode: agentic files are excluded from the project history; use agentic-sync commit for them.
# Exit: 0 ok, 1 misuse or failure, 2 STOP (needs a decision from the user).
param(
  [Parameter(Mandatory)][string]$Message,
  [Parameter(Mandatory)][string[]]$Paths,
  [switch]$Push,
  [switch]$DryRun,
  [string]$Root
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# compute the root in the body: in Windows PowerShell 5.1 $PSScriptRoot is empty inside a param default when a parameter is Mandatory
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
$ErrorActionPreference = 'Continue'
function Invoke-Git { & git -C $Root @args }  # not named Git: a function named Git would shadow git.exe and recurse
function Stop-Here([string]$msg, [int]$code = 2) { Write-Output "STOP:$msg"; exit $code }

$Paths = @($Paths | ForEach-Object { $_ -split ',' } | Where-Object { $_.Trim() })  # powershell -File passes "a,b" as one string
$specs = @($Paths | ForEach-Object { ($_ -replace '\\', '/' -replace '^\./', '').TrimEnd('/') } | Where-Object { $_ })  # -replace, not a character-set trim, which would strip leading dots such as .github
foreach ($p in $Paths) {
  $n = ($p -replace '\\', '/').Trim()
  if ($n -in @('.', './', '*', '/', '') -or $n -match '^\.\.') { Stop-Here "path too broad or outside the repository: '$p' (name the files or folders of this session)" 1 }
}
if ($specs.Count -eq 0) { Stop-Here 'no -Paths' 1 }

# 1. any change under the paths?
$mine = @(Invoke-Git status --porcelain --untracked-files=all -- @specs)
if ($mine.Count -eq 0) {
  foreach ($s in $specs) {
    Invoke-Git check-ignore -q -- $s 2>$null
    if ($LASTEXITCODE -eq 0) { Stop-Here "'$s' is ignored by the project history (hidden-mode agentic file?); use agentic-sync commit for it" 1 }
  }
  Stop-Here 'no changes under the given paths' 1
}

# 2. staged files that belong to another session?
function Covered([string]$f) { foreach ($s in $specs) { if ($f -eq $s -or $f.StartsWith($s + '/')) { return $true } } return $false }
$foreign = @(Invoke-Git diff --cached --name-only | Where-Object { -not (Covered $_) })
if ($foreign.Count -gt 0) {
  Write-Output 'staged files outside -Paths (another session, not committed):'
  $foreign | Select-Object -First 10 | ForEach-Object { Write-Output "  $_" }
  Stop-Here 'another session has staged files; wait for its commit or report to the user'
}

# 3. stage only these paths and show the stat
Invoke-Git add -- @specs
Write-Output '[STAT]'
Invoke-Git diff --cached --stat | ForEach-Object { Write-Output $_ }
if ($DryRun) { Write-Output 'DRYRUN: nothing committed'; exit 0 }

# 4. commit with a pathspec
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("cm-" + [guid]::NewGuid() + '.txt')
[IO.File]::WriteAllText($tmp, $Message.TrimEnd() + "`n", (New-Object Text.UTF8Encoding $false))
try {
  $o = Invoke-Git commit -q -F $tmp -- @specs 2>&1
  if ($LASTEXITCODE -ne 0) { $o | ForEach-Object { Write-Output "$_" }; Stop-Here 'commit rejected (see the hook message above)' 1 }
  $o | Where-Object { $_ } | ForEach-Object { Write-Output "$_" }
} finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
Write-Output ("COMMIT: " + (Invoke-Git log -1 --format='%h %s'))
if (-not $Push) { Write-Output 'push skipped (no -Push)'; exit 0 }

# 5. safe push
$env:GIT_TERMINAL_PROMPT = '0'
Invoke-Git fetch --quiet 2>$null
if ($LASTEXITCODE -ne 0) { Stop-Here 'fetch failed; the commit exists locally, not pushed' }
Invoke-Git rev-parse --abbrev-ref '@{u}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Here 'no upstream; push by hand after the user decides' }
$behind = [int](Invoke-Git rev-list --count 'HEAD..@{u}')
if ($behind -gt 0) { Stop-Here "the remote has $behind new commit(s); the local commit exists, no automatic rebase or merge, report to the user" }

$email = (Invoke-Git config user.email); $name = (Invoke-Git config user.name)
$bad = @()
foreach ($sha in @(Invoke-Git rev-list '@{u}..HEAD')) {
  $id = Invoke-Git log -1 --format='%an|%ae|%cn|%ce' $sha
  $a = $id -split '\|'
  if ($a[0] -ne $name -or $a[1] -ne $email -or $a[2] -ne $name -or $a[3] -ne $email) { $bad += "$($sha.Substring(0,7)): identity $id" }
  $body = (Invoke-Git log -1 --format='%B' $sha) -join "`n"
  if ($body -match '(?im)^(co-authored-by|signed-off-by|generated-by)\s*:|generated with') { $bad += "$($sha.Substring(0,7)): agent trailer in the message" }
}
if ($bad.Count -gt 0) { $bad | ForEach-Object { Write-Output "  $_" }; Stop-Here 'identity or trailer does not match the policy; push cancelled' }

Invoke-Git push -q 2>&1 | ForEach-Object { Write-Output "$_" }
if ($LASTEXITCODE -ne 0) { Stop-Here 'push failed' 1 }
Write-Output 'PUSH: ok'
exit 0
