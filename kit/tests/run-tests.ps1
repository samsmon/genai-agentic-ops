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
# the Python suites need the kit folders (adapters, core, install.py); an installed project has the script suites only
$inKit = Test-Path -LiteralPath (Join-Path $PSScriptRoot '..\adapters')
foreach ($f in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter test_*.py | Sort-Object Name)) {
  if (-not $inKit) { Write-Output "SKIP   $($f.BaseName) (installed layout)"; continue }
  $o = & python -B -I $f.FullName 2>&1
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
foreach ($f in (Get-ChildItem -LiteralPath $PSScriptRoot -Filter *.tests.sh | Sort-Object Name)) {
  if ($bash) {
    $o = & $bash $f.FullName 2>&1
    if ($LASTEXITCODE -eq 0) { Write-Output "OK     $($f.Name)" } else { Write-Output "FAIL   $($f.Name)"; ($o | Where-Object { $_ -match '^FAIL' }) | ForEach-Object { Write-Output "         $_" }; $bad++ }
  } else { Write-Output "SKIP   $($f.Name) (bash not found)" }
}
Write-Output "[TESTS] $bad suite(s) failed"
if ($bad -gt 0) { exit 1 } else { exit 0 }
