$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Sc 'status-brief.ps1')).Path
$root = Join-Path $env:TEMP ("sbr-" + [guid]::NewGuid())
$env:GIT_AUTHOR_NAME = 't'; $env:GIT_AUTHOR_EMAIL = 't@t'; $env:GIT_COMMITTER_NAME = 't'; $env:GIT_COMMITTER_EMAIL = 't@t'
$fail = 0
function Expect([string]$name, [bool]$ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function Brief([string]$mode) { $o = & powershell -NoProfile -File $script -Mode $mode -Root $root; return @{ code = $LASTEXITCODE; out = ($o -join "`n") } }
try {
  New-Item -ItemType Directory $root, (Join-Path $root 'docs'), (Join-Path $root 'projects\p\discussion'), (Join-Path $root 'projects\_template\discussion') | Out-Null
  & git -C $root init -q 2>$null | Out-Null
  $old = (Get-Date).AddHours(-5).ToString('yyyy-MM-dd HH:mm'); $new = (Get-Date).ToString('yyyy-MM-dd HH:mm')
  $hdr = "| T | A | ID | Target | Status | Task |`n|---|---|---|---|---|---|`n"
  Set-Content (Join-Path $root 'docs\CURRENT_OPS.md') ("# OPS`n" + $hdr + "| $new | claude | s1 | x | running | task-new |`n| $old | gemini | s2 | y | running | task-stale |`n| $new | codex | s3 | z | done | task-finished |`n## Archive`n| $old | a | m | x | running | archived-row |`n") -Encoding UTF8
  Set-Content (Join-Path $root 'NOW.md') "# NOW`n`n**Last update:** today`n`n## Last focus`n`n**focus-one:** body`n`n## Next step`n- next-one`n- next-two`n`n## Awaiting review`n- a.md`n- b.md`n" -Encoding UTF8
  Set-Content (Join-Path $root 'projects\p\discussion\wip.md') "---`nstatus: wip`n---`nx" -Encoding UTF8
  Set-Content (Join-Path $root 'projects\p\discussion\fin.md') "---`nstatus: done`n---`nx" -Encoding UTF8
  Set-Content (Join-Path $root 'projects\_template\discussion\t.md') "---`nstatus: wip`n---`nx" -Encoding UTF8
  & git -C $root add -A 2>$null | Out-Null; & git -C $root commit -q -m init 2>$null | Out-Null
  Set-Content (Join-Path $root 'stray.txt') 'x'

  $r = Brief 'status'
  Expect 'exit 0' ($r.code -eq 0)
  Expect 'status mode and four-part format' (($r.out -match '\[MODE\] status') -and ($r.out -match 'Done / In progress / Next / Blockers'))
  Expect 'running lock shown, done and archive rows not' (($r.out -match 'task-new') -and ($r.out -notmatch 'task-finished') -and ($r.out -notmatch 'archived-row'))
  Expect 'lock older than 2 hours is STALE' ($r.out -match 'task-stale[^\n]*<<STALE>>')
  Expect 'wip discussion shown, done and template not' (($r.out -match 'wip\.md \(wip\)') -and ($r.out -notmatch 'fin\.md') -and ($r.out -notmatch '_template'))
  Expect 'review count under Awaiting review' ($r.out -match '\[REVIEW\] 2 item\(s\)')
  Expect 'untracked reported' ($r.out -match 'untracked: 1 file\(s\)')
  Expect 'status mode has no RESUME block' ($r.out -notmatch '\[RESUME\]')

  $r = Brief 'resume'
  Expect 'resume shows focus and next step' (($r.out -match '\[RESUME\]') -and ($r.out -match 'focus-one') -and ($r.out -match 'next-one'))

  Add-Content (Join-Path $root 'NOW.md') 'edit'
  $r = Brief 'status'
  Expect 'tracked change reported' ($r.out -match 'tracked: 1 file\(s\) changed')

  # config: another state file name and review heading through the environment, and the legacy heading
  Set-Content (Join-Path $root 'STATE.md') "# S`n`n## Needs a look`n- c.md`n" -Encoding UTF8
  $env:STATE_FILE = 'STATE.md'; $env:REVIEW_HEADING = 'Needs a look'
  $r = Brief 'status'
  Remove-Item Env:STATE_FILE, Env:REVIEW_HEADING
  Expect 'STATE_FILE and REVIEW_HEADING from the environment' ($r.out -match '\[REVIEW\] 1 item\(s\) awaiting review in STATE\.md')
  Set-Content (Join-Path $root 'NOW.md') "# NOW`n`n## Belum di-review`n- a.md`n- b.md`n- c.md`n" -Encoding UTF8
  $r = Brief 'status'
  Expect 'the legacy heading Belum di-review is still accepted' ($r.out -match '\[REVIEW\] 3 item\(s\)')
  $env:OPS_FILE = 'docs/OTHER.md'
  $r = Brief 'status'
  Remove-Item Env:OPS_FILE
  Expect 'OPS_FILE from the environment (missing file: no rows, no crash)' (($r.code -eq 0) -and ($r.out -match 'no running/blocked rows') -and ($r.out -notmatch 'task-new'))
  Remove-Item (Join-Path $root 'NOW.md')
  $r = Brief 'resume'
  Expect 'missing state file -> NOW.md MISSING in resume' ($r.out -match 'NOW\.md MISSING')

  # hidden mode: agentic files excluded from the project history are still read, and not counted as untracked
  Set-Content (Join-Path $root 'NOW.md') "# NOW`n`n## Awaiting review`n- h.md`n" -Encoding UTF8
  Add-Content (Join-Path $root '.git\info\exclude') "`nNOW.md`ndocs/CURRENT_OPS.md`n"
  & git -C $root rm -q --cached NOW.md docs/CURRENT_OPS.md 2>$null | Out-Null
  & git -C $root commit -q -m untrack 2>$null | Out-Null
  $r = Brief 'status'
  Expect 'hidden mode: untracked count excludes the hidden files (stray.txt and STATE.md remain)' ($r.out -match 'untracked: 2 file\(s\)')
  Expect 'hidden mode: the hidden ops log and state file are still read' (($r.out -match 'task-new') -and ($r.out -match '\[REVIEW\] 1 item\(s\)'))

  # PowerShell pitfall: a pipe from Windows PowerShell 5.1 starts with a UTF-8 BOM; the hook must decode utf-8-sig
  $hook = Join-Path $Hk 'status_prompt.py'
  if (Test-Path -LiteralPath $hook) {
    $proj = Join-Path $env:TEMP ("sbh-" + [guid]::NewGuid())
    try {
      New-Item -ItemType Directory (Join-Path $proj 'scripts\agentic-ops') | Out-Null
      Copy-Item $script (Join-Path $proj 'scripts\agentic-ops\status-brief.ps1')
      & git -C $proj init -q 2>$null | Out-Null
      $env:CLAUDE_PROJECT_DIR = $proj
      $hookRun = { param([string]$prompt) ((@{ prompt = $prompt } | ConvertTo-Json -Compress) | & python -B -I $hook) -join "`n" }
      Expect 'hook: "Status" through a PowerShell pipe (BOM) triggers' ((& $hookRun 'Status') -match 'additionalContext')
      Expect 'hook: "progress." triggers' ((& $hookRun 'progress.') -match 'additionalContext')
      Expect 'hook: "resume" uses resume mode' ((& $hookRun 'resume') -match 'RESUME')
      Expect 'hook: a sentence containing status does not trigger' (-not [bool](& $hookRun 'check the status of the server'))
      $bad = ('not json' | & python -B -I $hook) -join ''
      Expect 'hook: broken input is silent, exit 0' ((-not $bad) -and ($LASTEXITCODE -eq 0))
    } finally { Remove-Item $proj -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item Env:CLAUDE_PROJECT_DIR -ErrorAction SilentlyContinue }
  } else { Write-Output 'SKIP hook cases (status_prompt.py not found in this layout)' }

  # PowerShell pitfalls in the source: no function named Git, no TrimStart('./')
  $src = (Get-Content -Raw -LiteralPath $script)
  Expect 'pitfall: status-brief does not define a function named Git' ($src -notmatch '(?im)^\s*function\s+Git\b')
} finally {
  Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item Env:CLAUDE_PROJECT_DIR, Env:STATE_FILE, Env:REVIEW_HEADING, Env:OPS_FILE -ErrorAction SilentlyContinue
}
if ($fail -gt 0) { exit 1 } else { exit 0 }
