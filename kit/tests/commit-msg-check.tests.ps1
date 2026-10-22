$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# The checker is a POSIX sh script; PowerShell calls it through sh (Git for Windows ships one).
$chk = (Resolve-Path (Join-Path $PSScriptRoot '..\scripts\commit-msg-check.sh')).Path
$tmp = Join-Path $env:TEMP ("cmc-" + [guid]::NewGuid() + ".txt")
$utf8 = New-Object Text.UTF8Encoding $false
$fail = 0
function Expect([string]$name, [bool]$ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function Check([string]$text) {
  [IO.File]::WriteAllText($tmp, $text, $utf8)
  $o = & sh $chk $tmp 2>&1
  return @{ code = $LASTEXITCODE; out = (($o | ForEach-Object { "$_" }) -join "`n") }
}
try {
  if (-not (Get-Command sh -ErrorAction SilentlyContinue)) { Write-Output 'SKIP sh not found'; exit 0 }
  Expect 'valid message -> exit 0' ((Check "feat(auth): add login`n").code -eq 0)
  Expect 'valid message with body and footer' ((Check "fix: stop double submit`n`nThe form posted twice.`n`nRefs: #12`n").code -eq 0)
  $r = Check "[claude] feat: add login`n"
  Expect 'bracket prefix -> exit 1 with a reason' (($r.code -eq 1) -and ($r.out -match 'nothing may come before the type'))
  $r = Check "Update stuff`n"
  Expect 'free text -> exit 1' ($r.code -eq 1)
  $r = Check "feat: Add login.`n"
  Expect 'capital letter and period -> exit 1, both reported' (($r.code -eq 1) -and ($r.out -match 'lowercase') -and ($r.out -match 'period'))
  $r = Check "feat: added login`n"
  Expect 'past tense -> exit 0 with a warning' (($r.code -eq 0) -and ($r.out -match 'imperative'))
  Expect 'CRLF message accepted' ((Check "feat: add login`r`n`r`nbody`r`n").code -eq 0)
  Expect 'merge commit exempt' ((Check "Merge branch 'x' into main`n").code -eq 0)
  $env:COMMIT_EXTRA_TYPES = 'ops'
  Expect 'COMMIT_EXTRA_TYPES adds a type' ((Check "ops: rotate rows`n").code -eq 0)
  Remove-Item Env:COMMIT_EXTRA_TYPES
  $env:SKIP_COMMIT_FORMAT = '1'
  Expect 'SKIP_COMMIT_FORMAT=1 skips the check' ((Check "Update stuff`n").code -eq 0)
  Remove-Item Env:SKIP_COMMIT_FORMAT
} finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
if ($fail -eq 0) { Write-Output 'ALL TESTS PASSED' } else { Write-Output "$fail FAILED" }
exit $(if ($fail -eq 0) { 0 } else { 1 })
