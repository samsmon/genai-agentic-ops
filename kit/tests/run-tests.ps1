# Run every kit test suite. Exit 1 if any fails.
# -Skip wrap-check skips a slow suite (it creates several temporary git repositories).
param([string[]]$Skip = @())
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$bad = 0
foreach ($f in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter *.tests.ps1 | Sort-Object Name)) {
  $name = $f.Name -replace '\.tests\.ps1$', ''
  if ($Skip -contains $name) { Write-Output "SKIP   $name"; continue }
  $o = & powershell -NoProfile -File $f.FullName 2>&1
  if ($LASTEXITCODE -eq 0) { Write-Output "OK     $name" } else { Write-Output "FAIL   $name"; ($o | Where-Object { $_ -match '^FAIL' }) | ForEach-Object { Write-Output "         $_" }; $bad++ }
}
foreach ($f in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter test_*.py | Sort-Object Name)) {
  $o = & python -I $f.FullName 2>&1
  if ($LASTEXITCODE -eq 0) { Write-Output "OK     $($f.BaseName)" } else { Write-Output "FAIL   $($f.BaseName)"; ($o | Where-Object { $_ -match '^FAIL' }) | ForEach-Object { Write-Output "         $_" }; $bad++ }
}
# bash.exe in System32 is often the WSL stub with no distribution, so probe each candidate
$bash = $null
$cands = @(Get-Command bash -All -ErrorAction SilentlyContinue | ForEach-Object Source) + @("$env:ProgramFiles\Git\bin\bash.exe")
foreach ($c in $cands) {
  if ($c -and (Test-Path -LiteralPath $c)) {
    $probe = & $c -c 'echo ok' 2>$null
    if ("$probe".Trim() -eq 'ok') { $bash = $c; break }
  }
}
if ($bash) {
  $o = & $bash (Join-Path $PSScriptRoot 'scripts.tests.sh') 2>&1
  if ($LASTEXITCODE -eq 0) { Write-Output 'OK     scripts.tests.sh' } else { Write-Output 'FAIL   scripts.tests.sh'; ($o | Where-Object { $_ -match '^FAIL' }) | ForEach-Object { Write-Output "         $_" }; $bad++ }
} else { Write-Output 'SKIP   scripts.tests.sh (bash not found)' }
Write-Output "[TESTS] $bad suite(s) failed"
if ($bad -gt 0) { exit 1 } else { exit 0 }
