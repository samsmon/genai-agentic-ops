# Commit (and optionally push) ONLY files owned by this session, enforcing rules 2 and 9:
#   - -Paths is strictly required; "." and "*" are rejected
#   - stops immediately if foreign staged files exist outside -Paths (owned by another session/agent)
#   - stages only specified paths and prints git diff --cached --stat
#   - commits via a temporary file with pathspec (commit-msg hooks remain active)
#   - -Push: runs git fetch, stops if remote has new commits, verifies user identity and no AI trailers, then pushes
#   - -DryRun: runs checks and displays stat without committing
# Exit: 0 ok, 1 usage/failure, 2 STOP (requires user decision).
param(
  [Parameter(Mandatory)][string]$Message,
  [Parameter(Mandatory)][string[]]$Paths,
  [switch]$Push,
  [switch]$DryRun,
  [string]$Root = ''
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
$ErrorActionPreference = 'Continue'
function Invoke-Git { & git -C $Root @args }
function Stop-Here([string]$msg, [int]$code = 2) { Write-Output "STOP:$msg"; exit $code }

$Paths = @($Paths | ForEach-Object { $_ -split ',' } | Where-Object { $_.Trim() })
$specs = @($Paths | ForEach-Object { ($_ -replace '\\', '/' -replace '^\./', '').TrimEnd('/') } | Where-Object { $_ })
foreach ($p in $Paths) {
  $n = ($p -replace '\\', '/').Trim()
  if ($n -in @('.', './', '*', '/', '') -or $n -match '^\.\.') { Stop-Here "path too broad or outside repo: '$p' (specify explicit files or folders)" 1 }
}
if ($specs.Count -eq 0) { Stop-Here 'no -Paths specified' 1 }

# 1. Any changes in path?
$mine = @(Invoke-Git status --porcelain --untracked-files=all -- @specs)
if ($mine.Count -eq 0) { Stop-Here 'no changes in the specified paths' 1 }

# 2. Are foreign files staged?
function Covered([string]$f) { foreach ($s in $specs) { if ($f -eq $s -or $f.StartsWith($s + '/')) { return $true } } return $false }
$foreign = @(Invoke-Git diff --cached --name-only | Where-Object { -not (Covered $_) })
if ($foreign.Count -gt 0) {
  Write-Output 'staged files outside -Paths (owned by another session, not committing):'
  $foreign | Select-Object -First 10 | ForEach-Object { Write-Output "  $_" }
  Stop-Here 'foreign files are staged; wait for that session or ask user'
}

# 3. Stage only these paths and show stat
Invoke-Git add -- @specs
Write-Output '[STAT]'
Invoke-Git diff --cached --stat | ForEach-Object { Write-Output $_ }
if ($DryRun) { Write-Output 'DRYRUN: no commit made'; exit 0 }

# 4. Commit with pathspec
$tmp = Join-Path ([IO.Path]::GetTempPath()) ("cm-" + [guid]::NewGuid() + '.txt')
[IO.File]::WriteAllText($tmp, $Message.TrimEnd() + "`n", (New-Object Text.UTF8Encoding $false))
try {
  $o = Invoke-Git commit -q -F $tmp -- @specs 2>&1
  if ($LASTEXITCODE -ne 0) { $o | ForEach-Object { Write-Output "$_" }; Stop-Here 'commit rejected by hook' 1 }
  $o | Where-Object { $_ } | ForEach-Object { Write-Output "$_" }
} finally { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
Write-Output ("COMMIT: " + (Invoke-Git log -1 --format='%h %s'))
if (-not $Push) { Write-Output 'push skipped (run with -Push to push)'; exit 0 }

# 5. Safe push
$env:GIT_TERMINAL_PROMPT = '0'
Invoke-Git fetch --quiet 2>$null
if ($LASTEXITCODE -ne 0) { Stop-Here 'git fetch failed; commit made locally, push skipped' }
Invoke-Git rev-parse --abbrev-ref '@{u}' 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Here 'no upstream tracking branch; push manually after decision' }
$behind = [int](Invoke-Git rev-list --count 'HEAD..@{u}')
if ($behind -gt 0) { Stop-Here "remote has $behind new commit(s); commit is local, no auto-rebase, notify user" }

$email = (Invoke-Git config user.email); $name = (Invoke-Git config user.name)
$bad = @()
foreach ($sha in @(Invoke-Git rev-list '@{u}..HEAD')) {
  $id = Invoke-Git log -1 --format='%an|%ae|%cn|%ce' $sha
  $a = $id -split '\|'
  if ($a[0] -ne $name -or $a[1] -ne $email -or $a[2] -ne $name -or $a[3] -ne $email) { $bad += "$($sha.Substring(0,7)): identity mismatch $id" }
  $body = (Invoke-Git log -1 --format='%B' $sha) -join "`n"
  if ($body -match '(?im)^(co-authored-by|signed-off-by|generated-by)\s*:|generated with') { $bad += "$($sha.Substring(0,7)): agent trailer in commit message" }
}
if ($bad.Count -gt 0) { $bad | ForEach-Object { Write-Output "  $_" }; Stop-Here 'identity or trailer violates policy; push aborted' }

Invoke-Git push -q 2>&1 | ForEach-Object { Write-Output "$_" }
if ($LASTEXITCODE -ne 0) { Stop-Here 'push failed' 1 }
Write-Output 'PUSH: ok'
exit 0
