# Categorize untracked files (read-only): by directory, size, age, inferred kind,
# and match against active running/blocked locks in CURRENT_OPS.md.
# Does not delete, does not touch .gitignore; reports suggestions for the user.
param(
  [string]$Root = '',
  [string]$OpsFile = 'docs\CURRENT_OPS.md',
  [int]$BigKB = 1024,
  [int]$Top = 12
)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $Root) { $Root = (& git rev-parse --show-toplevel 2>$null); if (-not $Root) { $Root = (Get-Location).Path } }

$files = @(& git -C $Root ls-files --others --exclude-standard)
Write-Output "[UNTRACKED] $($files.Count) file(s)"
if ($files.Count -eq 0) { exit 0 }

# Collect active targets from running/blocked locks
$owners = @()
$inArchive = $false
$opsPath = Join-Path $Root $OpsFile
if (Test-Path -LiteralPath $opsPath) {
  foreach ($line in (Get-Content -LiteralPath $opsPath -Encoding UTF8)) {
    if ($line -match '^## Archive') { $inArchive = $true; continue }
    if ($inArchive -or $line -notmatch '^\|') { continue }
    $c = $line.Split('|')
    if ($c.Count -lt 7) { continue }
    $st = $c[5].Trim().Trim('`').ToLower()
    if ($st -ne 'running' -and $st -ne 'blocked') { continue }
    foreach ($m in [regex]::Matches($c[4], '`([^`]+)`')) {
      $t = ($m.Groups[1].Value -replace '\\', '/' -replace '^\./', '').TrimEnd('/')
      if ($t -and $t -notmatch '^\.\.' -and $t -notmatch '^[A-Za-z]:' -and $t -notmatch '^//') {
        $owners += [pscustomobject]@{ Target = $t; Agent = $c[2].Trim(); Id = $c[3].Trim() }
      }
    }
  }
}

$today = Get-Date
$rows = foreach ($f in $files) {
  $full = Join-Path $Root $f
  $item = Get-Item -LiteralPath $full -ErrorAction SilentlyContinue
  if (-not $item) { continue }
  $parts = $f -split '/'
  $group = if ($parts.Count -ge 3) { $parts[0] + '/' + $parts[1] } else { $parts[0] }
  $name = $parts[-1]; $ext = $item.Extension.ToLower()
  $kind = 'other'
  if ($name -match '^(temp|tmp)[_-]|\.(tmp|bak|log|orig|swp)$|~$') { $kind = 'temporary' }
  elseif ($item.Length -gt ($BigKB * 1KB)) { $kind = 'large' }
  elseif ($ext -in '.json', '.csv', '.tsv', '.db', '.sqlite', '.xlsx', '.docx', '.zip') { $kind = 'data' }
  elseif ($ext -in '.py', '.ps1', '.sh', '.cmd') { $kind = 'script' }
  elseif ($ext -in '.md', '.txt') { $kind = 'docs' }
  $owner = $owners | Where-Object { $f -eq $_.Target -or $f.StartsWith($_.Target + '/') } | Select-Object -First 1
  [pscustomobject]@{
    Path  = $f
    Group = $group
    Kind  = $kind
    KB    = [math]::Round($item.Length / 1KB, 1)
    Days  = [int]($today - $item.LastWriteTime).TotalDays
    Owner = $(if ($owner) { "$($owner.Agent)/$($owner.Id)" } else { '' })
  }
}

Write-Output '[GROUP] folder: count, total KB, kinds'
$rows | Group-Object Group | Sort-Object Count -Descending | Select-Object -First $Top | ForEach-Object {
  $kinds = ($_.Group | Group-Object Kind | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ' '
  $own = ($_.Group | Where-Object Owner | Select-Object -ExpandProperty Owner -Unique) -join ','
  Write-Output ("  {0,-42} {1,3} files {2,9} KB  {3}{4}" -f $_.Name, $_.Count, [math]::Round(($_.Group | Measure-Object KB -Sum).Sum, 1), $kinds, $(if ($own) { "  lock-owner: $own" } else { '' }))
}

Write-Output '[SUGGESTIONS] informational only'
$tmp = @($rows | Where-Object Kind -eq 'temporary')
$big = @($rows | Where-Object Kind -eq 'large')
$data = @($rows | Where-Object { $_.Kind -eq 'data' -and -not $_.Owner })
$noOwner = @($rows | Where-Object { -not $_.Owner })
if ($tmp.Count) {
  Write-Output "  temporary ($($tmp.Count)): inspect and remove or add to .gitignore"
  $tmp | Select-Object -First 5 | ForEach-Object { Write-Output "    $($_.Path)  ($($_.Days) days old)" }
}
if ($big.Count) {
  Write-Output "  large > $BigKB KB ($($big.Count)): do not stage; .gitignore or move outside repo"
  $big | Select-Object -First 5 | ForEach-Object { Write-Output "    $($_.Path)  $($_.KB) KB" }
}
if ($data.Count) {
  Write-Output "  data files without lock owner ($($data.Count)): add to .gitignore if build/run artifact"
  $data | Select-Object -First 5 | ForEach-Object { Write-Output "    $($_.Path)" }
}
Write-Output "  unlocked: $($noOwner.Count) of $($rows.Count) files (locked files must NOT be touched by other sessions)"
exit 0
