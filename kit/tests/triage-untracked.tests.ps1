$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Sc 'triage-untracked.ps1')).Path
$root = Join-Path $env:TEMP ("tu-" + [guid]::NewGuid())
$fail = 0
function Expect([string]$name, $ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function W([string]$f, [string]$t = 'x') { $p = Join-Path $root $f; New-Item -ItemType Directory (Split-Path $p) -Force | Out-Null; Set-Content $p $t -Encoding UTF8 }
function TU { return ((& powershell -NoProfile -File $script -Root $root) -join "`n") }
try {
  New-Item -ItemType Directory $root | Out-Null
  & git -C $root init -q 2>$null | Out-Null
  W 'docs/CURRENT_OPS.md' ("# OPS`n| T | A | ID | Target | Status | Task |`n|---|---|---|---|---|---|`n| 2026-10-29 10:00 | claude | sess-a | ``work/mine`` | running | x |`n| 2026-10-29 10:00 | gemini | sess-b | ``work/old`` | done | x |`n| 2026-10-29 10:00 | codex | sess-c | ``./.config/tool/`` | blocked | x |`n## Archive`n")
  W 'work/mine/a.py'; W 'work/mine/b.md'; W 'work/other/data.json'; W 'temp_notes.md'; W 'x.bak'
  W '.config/tool/one.txt'; W '.config/tool/two.txt'
  $p = Join-Path $root 'work/other/big.bin'; [IO.File]::WriteAllBytes($p, (New-Object byte[] (2MB)))
  & git -C $root add docs/CURRENT_OPS.md 2>$null | Out-Null
  $o = TU
  Expect 'exit 0' ($LASTEXITCODE -eq 0)
  Expect 'counts the untracked files' ($o -match '\[UNTRACKED\] 8 file\(s\)')
  Expect 'work/mine is marked with the running lock owner' ($o -match 'work/mine[^\n]*lock-owner: claude/sess-a')
  Expect 'a done lock is not an owner' ($o -notmatch 'sess-b')
  Expect 'temp files proposed (temp_ and .bak)' (($o -match 'temp \(2\)') -and ($o -match 'temp_notes\.md') -and ($o -match 'x\.bak'))
  Expect 'big file flagged' (($o -match 'big > 1024 KB \(1\)') -and ($o -match 'big\.bin'))
  Expect 'data without a lock owner proposed' ($o -match 'data without a lock owner \(1\)')
  # pitfall: a character-set trim of './' strips every leading '.' or '/', so the lock target ./.config/tool/ became config/tool and never matched
  Expect 'pitfall: a lock target with a leading dot (./.config/tool/) still matches its files' ($o -match '\.config/tool[^\n]*lock-owner: codex/sess-c')
  Expect 'pitfall: the source does not use TrimStart with ./' ((Get-Content -Raw -LiteralPath $script) -notmatch "TrimStart\(\s*'\./'")
  Expect 'deletes nothing' ((Test-Path (Join-Path $root 'temp_notes.md')) -and (Test-Path (Join-Path $root 'x.bak')))

  # OPS_FILE from the environment; hidden-mode files excluded from the project history are not counted
  W 'ops2.md' ("| T | A | ID | Target | Status | Task |`n|---|---|---|---|---|---|`n| 2026-10-29 10:00 | zed | sess-z | ``work/other`` | running | x |`n")
  $env:OPS_FILE = 'ops2.md'
  $o = TU
  Remove-Item Env:OPS_FILE
  Expect 'OPS_FILE from the environment' ($o -match 'work/other[^\n]*lock-owner: zed/sess-z')
  Add-Content (Join-Path $root '.git\info\exclude') "`nops2.md`ntemp_notes.md`n"
  $o = TU
  Expect 'hidden mode: excluded files are not counted' ($o -match '\[UNTRACKED\] 7 file\(s\)' -and $o -notmatch 'temp_notes\.md')

  Remove-Item (Join-Path $root 'x.bak'), (Join-Path $root 'work'), (Join-Path $root '.config'), (Join-Path $root 'ops2.md'), (Join-Path $root 'temp_notes.md') -Recurse -Force
  Expect 'no untracked files -> 0' ((TU) -match '\[UNTRACKED\] 0 file\(s\)')
} finally { Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item Env:OPS_FILE -ErrorAction SilentlyContinue }
if ($fail -gt 0) { exit 1 } else { exit 0 }
