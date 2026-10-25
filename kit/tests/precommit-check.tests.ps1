$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Sc 'precommit-check.ps1')).Path
$root = Join-Path $env:TEMP ("pctest-" + [guid]::NewGuid())
function Run($staged, [int]$max = 16384) { $o = & powershell -NoProfile -File $script -Staged $staged -Root $root -MaxRulesBytes $max; return @{ code = $LASTEXITCODE; out = ($o -join "`n") } }
$fail = 0
function Expect($name, $ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function New-GitRoot {
  Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory $root | Out-Null
  & git -C $root init -q 2>$null | Out-Null
}
function Stage-Run([string]$name, [string]$content) {
  New-GitRoot
  Set-Content (Join-Path $root $name) $content -Encoding UTF8 -NoNewline
  & git -C $root add -A 2>$null | Out-Null
  return (Run $name)
}

# rules file size warning (no git needed)
New-Item -ItemType Directory $root | Out-Null
Set-Content "$root\AGENTS.md" ('x' * 500) -Encoding ASCII -NoNewline
$r = Run 'AGENTS.md' 100
Expect 'big rules file -> 0 + WARNING' (($r.code -eq 0) -and ($r.out -match 'WARNING'))
$r = Run 'AGENTS.md' 1000
Expect 'small rules file -> silent' (($r.code -eq 0) -and ($r.out -eq ''))
Set-Content "$root\AGENTS.md" ('x' * 25000) -Encoding ASCII -NoNewline
$r = Run 'AGENTS.md' 100000
Expect 'rules file over 24000 B -> 0 + Antigravity WARNING even under the general limit' (($r.code -eq 0) -and ($r.out -match 'Antigravity'))
Set-Content "$root\AGENTS.md" ('x' * 500) -Encoding ASCII -NoNewline
$r = Run 'AGENTS.md' 100
Expect 'small rules file -> no Antigravity warning' ($r.out -notmatch 'Antigravity')
$r = Run 'README.md'
Expect 'unrelated file -> 0 and silent' (($r.code -eq 0) -and ($r.out -eq ''))

# fake values are assembled at runtime so this test file is not itself flagged
$fake = 'sk-ant-' + ('a1' * 15)
$r = Stage-Run 'a.md' "key $fake"
Expect 'Anthropic key staged -> 1 + REJECTED without the value' (($r.code -eq 1) -and ($r.out -match 'possible secret') -and ($r.out -notmatch [regex]::Escape($fake)))
$r = Stage-Run 'b.md' ('id AKIA' + ('B2' * 8))
Expect 'AWS access key id -> 1' ($r.code -eq 1)
$r = Stage-Run 'c.md' ('api_key = ' + ('Zx9' * 10))
Expect 'long literal api_key -> 1' ($r.code -eq 1)
$r = Stage-Run 'd.md' 'plain prose with no secrets in it'
Expect 'plain text -> 0 and silent' (($r.code -eq 0) -and ($r.out -eq ''))
$r = Stage-Run 'e.md' 'token: abc'
Expect 'short token -> 0' ($r.code -eq 0)
New-GitRoot; New-Item -ItemType Directory (Join-Path $root 'private') | Out-Null
Set-Content (Join-Path $root 'private\keys.env') ('SOME_API_KEY=' + ('q1' * 20)) -Encoding UTF8
& git -C $root add -A 2>$null | Out-Null
$env:SECRET_SCAN_SKIP = 'private/*'
$r = Run 'private/keys.env'
Remove-Item Env:\SECRET_SCAN_SKIP
Expect 'SECRET_SCAN_SKIP path -> 0' ($r.code -eq 0)
$r = Stage-Run 'video.mp4' 'x'
Expect 'media extension staged -> 1' (($r.code -eq 1) -and ($r.out -match 'large file'))
New-GitRoot; [IO.File]::WriteAllBytes((Join-Path $root 'big.dat'), (New-Object byte[] (6MB))); & git -C $root add -A 2>$null | Out-Null
$r = Run 'big.dat'
Expect 'file over 5 MB -> 1' ($r.code -eq 1)
$env:ALLOW_BIG_FILES = '1'; $r = Run 'big.dat'; Remove-Item Env:\ALLOW_BIG_FILES
Expect 'ALLOW_BIG_FILES=1 -> 0 (message still printed)' (($r.code -eq 0) -and ($r.out -match 'large file'))

Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
if ($fail) { exit 1 } else { Write-Output 'ALL TESTS PASSED'; exit 0 }
