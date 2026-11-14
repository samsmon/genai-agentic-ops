# Handoff module check (read-only). Normally run by wrap-check.ps1; can run alone.
# Checks: state file says "Last update: <today> by <agent>", the monthly log has a line for today,
# and the reviewed_by front matter of discussion files matches the "Awaiting review" list.
param(
  [string]$Root = '',
  [string]$Agent = 'claude-code',
  [string]$Today = (Get-Date -Format 'yyyy-MM-dd'),
  [string]$StateFile = 'NOW.md',
  [string]$LogDir = 'log',                          # monthly files: log/YYYY-MM.md, lines "- YYYY-MM-DD [agent] ..."
  [string]$ReviewHeading = '## Awaiting review',
  [string]$DiscussionDirName = 'discussion'        # directories with this name hold discussion files
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$explicitHeading = $PSBoundParameters.ContainsKey('ReviewHeading')
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }
$script:bad = 0
function Ok([string]$m) { Write-Output "OK     $m" }
function No([string]$m) { Write-Output "FAIL   $m"; $script:bad++ }

function Resolve-ReviewSection([string]$stateText) {
  $cands = New-Object System.Collections.Generic.List[string]
  if ($explicitHeading -and $ReviewHeading) {
    $cands.Add($ReviewHeading)
  } else {
    if ($env:REVIEW_HEADING) { $cands.Add($env:REVIEW_HEADING) }
    $settingsPath = Join-Path $Root '.claude\settings.json'
    if (Test-Path -LiteralPath $settingsPath) {
      try {
        $cfg = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.env -and $cfg.env.REVIEW_HEADING) {
          $h = [string]$cfg.env.REVIEW_HEADING
          if (-not $cands.Contains($h)) { $cands.Add($h) }
        }
      } catch { }
    }
    foreach ($h in @('## Awaiting review', '## Belum di-review')) {
      if (-not $cands.Contains($h)) { $cands.Add($h) }
    }
  }
  foreach ($h in $cands) {
    $idx = $stateText.IndexOf($h)
    if ($idx -ge 0) {
      $sec = $stateText.Substring($idx)
      $next = $sec.IndexOf("`n## ", 5)
      if ($next -gt 0) { $sec = $sec.Substring(0, $next) }
      return $sec
    }
  }
  return ''
}

$statePath = Join-Path $Root $StateFile
if (-not (Test-Path -LiteralPath $statePath)) { No "STATE: $StateFile not found" }
else {
  $state = (Get-Content -LiteralPath $statePath -Encoding UTF8) -join "`n"
  $dateRe = [regex]::Escape($Today)
  $agentRe = [regex]::Escape($Agent)
  if ($state -match "(?:Last update|Update terakhir):\*{0,2}\s*$dateRe\s+(?:by|oleh)\s+$agentRe(?=\s|$)") { Ok "STATE: Last update = $Today by $Agent" }
  else { No "STATE: 'Last update' line is not '$Today by $Agent'" }
}

$logPath = Join-Path $Root ($LogDir + '\' + $Today.Substring(0, 7) + '.md')
if ((Test-Path -LiteralPath $logPath) -and ((Get-Content -LiteralPath $logPath -Encoding UTF8) -match ('^- ' + [regex]::Escape($Today) + ' \[' + [regex]::Escape($Agent) + '\]'))) { Ok "LOG: line for $Today [$Agent] present" }
else { No "LOG: no '- $Today [$Agent]' line in the monthly log" }

$rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\', '/')
$discFiles = @(Get-ChildItem -Path $rootFull -Filter *.md -Recurse -ErrorAction SilentlyContinue |
  Where-Object { $_.Directory.Name -eq $DiscussionDirName -and $_.Name -notlike '_*' -and $_.FullName -notmatch '[\\/]\.git[\\/]' -and $_.FullName -notmatch '[\\/]_template[\\/]' })
if ($discFiles.Count -eq 0 -or -not (Test-Path -LiteralPath $statePath)) { Ok 'REVIEW: no discussion files to check' }
else {
  $stateText = ((Get-Content -LiteralPath $statePath -Encoding UTF8) -join "`n") -replace "`r`n", "`n"
  $secNorm = (Resolve-ReviewSection $stateText) -replace '\\', '/'
  $probs = @()
  foreach ($f in $discFiles) {
    $rel = $f.FullName.Substring($rootFull.Length).TrimStart('\', '/') -replace '\\', '/'
    $txt = (Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8) -replace "`r`n", "`n"
    $fm = [regex]::Match($txt, '(?s)^---\n(.*?)\n---')
    if (-not $fm.Success) { $probs += "${rel}: no front matter"; continue }
    $rb = [regex]::Match($fm.Groups[1].Value, '(?m)^reviewed_by:\s*\[(.*?)\]')
    if (-not $rb.Success) { $probs += "${rel}: no reviewed_by"; continue }
    $st = [regex]::Match($fm.Groups[1].Value, '(?m)^status:\s*(\S+)')
    if ($st.Success -and $st.Groups[1].Value -ne 'done') { continue }
    $listed = $secNorm -match ('(?m)(?:^|[\s`(])' + [regex]::Escape($rel) + '(?:$|[\s`),:])')
    $reviewed = $rb.Groups[1].Value.Trim() -ne ''
    if (-not $reviewed -and -not $listed) { $probs += "${rel}: not reviewed but missing from $StateFile" }
    if ($reviewed -and $listed) { $probs += "${rel}: reviewed but still listed in $StateFile" }
  }
  if ($probs.Count -gt 0) { No ("REVIEW: $($probs.Count) discussion file(s) disagree with ${StateFile}: " + (($probs | Select-Object -First 3) -join '; ')) }
  else { Ok "REVIEW: $($discFiles.Count) discussion file(s) match $StateFile" }
}

Write-Output "[HANDOFF] $($script:bad) failed"
if ($script:bad -gt 0) { exit 1 } else { exit 0 }
