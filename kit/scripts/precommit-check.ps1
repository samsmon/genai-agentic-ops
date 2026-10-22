# Called by .githooks/pre-commit. No model; silent when it passes.
# Blocks: large or media/binary files, and likely secrets in added lines (values are never printed).
# Warns: rules file larger than -MaxRulesBytes (keep it small; see the token discipline rule), and over 24,000 bytes (Antigravity limit).
# Overrides, on the user's say-so only: ALLOW_BIG_FILES=1, ALLOW_SECRET_PATTERN=1.
# SECRET_SCAN_SKIP='path/pattern/*,other/*' skips the secret scan for those paths (-like patterns).
param(
  [string]$Staged = '',
  [string]$StagedFile = '',
  [string]$Root = '',
  [string]$RulesFile = 'AGENTS.md',
  [int]$MaxRulesBytes = 16384
)
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
if ($StagedFile -and (Test-Path -LiteralPath $StagedFile)) { $Staged = (Get-Content -LiteralPath $StagedFile -Raw -Encoding UTF8) }
$files = @($Staged -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$rc = 0

if ($files -contains $RulesFile) {
  $rp = Join-Path $Root $RulesFile
  $len = if (Test-Path -LiteralPath $rp) { (Get-Item -LiteralPath $rp).Length } else { 0 }
  if ($len -gt $MaxRulesBytes) {
    Write-Output "WARNING: $RulesFile is $len B, over $MaxRulesBytes B. Move rarely used blocks into a doc and link to it."
  }
  if ($len -gt 24000) {
    Write-Output "WARNING: $RulesFile is $len B. Antigravity truncates any single rule file over 24,000 bytes (docs, accessed 2026-10-22); trim it or move detail into linked docs."
  }
}

if ($files.Count -gt 0 -and (Test-Path -LiteralPath (Join-Path $Root '.git'))) {
  $maxBytes = 5MB
  $bigExt = '\.(mp4|mkv|avi|mov|wmv|zip|rar|7z|iso|exe|dll|dmp|flac|mp3|sqlite|sqlite3|db)$'
  foreach ($f in $files) {
    $fp = Join-Path $Root $f
    if (-not (Test-Path -LiteralPath $fp -PathType Leaf)) { continue }
    $len = (Get-Item -LiteralPath $fp).Length
    if ($len -gt $maxBytes -or $f -match $bigExt) {
      Write-Output "COMMIT REJECTED: large file or media/binary dump staged: $f ($([int]($len / 1KB)) KB). Keep it outside the repo or in .gitignore. Exception is the user's call: rerun with ALLOW_BIG_FILES=1."
      if ($env:ALLOW_BIG_FILES -ne '1') { $rc = 1 }
    }
  }
  $pats = [ordered]@{
    'Anthropic key'        = 'sk-ant-[A-Za-z0-9_-]{20,}'
    'AWS access key id'    = 'AKIA[0-9A-Z]{16}'
    'private key'          = '-----BEGIN [A-Z ]*PRIVATE KEY-----'
    'GitHub token'         = 'gh[pousr]_[A-Za-z0-9]{30,}'
    'Slack token'          = 'xox[baprs]-[A-Za-z0-9-]{10,}'
    'Google API key'       = 'AIza[0-9A-Za-z_-]{35}'
    'literal secret value' = '(?i)(api[_-]?key|secret|passwd|password|token)\s*[:=]\s*["'']?(?=[A-Za-z0-9/+_.-]{24,})(?=[A-Za-z0-9/+_.-]*[A-Za-z])(?=[A-Za-z0-9/+_.-]*\d)[A-Za-z0-9/+_.-]{24,}'
  }
  $skip = @(([string]$env:SECRET_SCAN_SKIP) -split ',' | Where-Object { $_ })
  $diff = & git -C $Root -c core.quotepath=off diff --cached -U0 --no-color 2>$null
  $cur = ''; $hits = @{}
  foreach ($l in $diff) {
    if ($l -match '^\+\+\+ b/(.+)$') { $cur = $Matches[1]; continue }
    if ($l -notmatch '^\+' -or $l -match '^\+\+\+') { continue }
    $skipped = $false
    foreach ($s in $skip) { if ($cur -like $s) { $skipped = $true } }
    if ($skipped) { continue }
    foreach ($k in $pats.Keys) {
      if ($l -match $pats[$k]) { $hits["$cur | $k"] = 1 }
    }
  }
  if ($hits.Count -gt 0) {
    foreach ($h in ($hits.Keys | Sort-Object)) { Write-Output "COMMIT REJECTED: possible secret in an added line: $h (value not shown)" }
    Write-Output 'Remove the value and keep it outside the repo. False positive is the user''s call: rerun with ALLOW_SECRET_PATTERN=1.'
    if ($env:ALLOW_SECRET_PATTERN -ne '1') { $rc = 1 }
  }
}
exit $rc
