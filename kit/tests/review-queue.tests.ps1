$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
. (Join-Path $PSScriptRoot 'layout.ps1')
$script = (Resolve-Path (Join-Path $Sc 'review-queue.ps1')).Path
$root = Join-Path $env:TEMP ("rq-" + [guid]::NewGuid())
$fail = 0
function Expect([string]$name, $ok) { if ($ok) { Write-Output "ok   $name" } else { Write-Output "FAIL $name"; $script:fail++ } }
function W([string]$f, [string]$t) { $p = Join-Path $root $f; New-Item -ItemType Directory (Split-Path $p) -Force | Out-Null; Set-Content $p $t -Encoding UTF8 }
function RQ { return ((& powershell -NoProfile -File $script -Root $root) -join "`n") }
try {
  New-Item -ItemType Directory $root | Out-Null
  W 'projects/p1/discussion/2026-10-01-claude-a.md' "---`nstatus: done`nreviewed_by: []`n---`nx"
  W 'projects/p1/discussion/2026-10-05-gemini-b.md' "---`nstatus: wip`nreviewed_by: []`n---`nx"
  W 'projects/p2/discussion/2026-10-02-claude-c.md' "---`nstatus: done`nreviewed_by: [gemini]`n---`nx"
  W 'research/2026-10-03-claude-d.md' "no front matter"
  W 'NOW.md' ("# NOW`n`n## Awaiting review`n" +
    "- projects/p1/discussion/2026-10-01-claude-a.md (by claude) - summary-a`n" +
    "- projects/p1/discussion/2026-10-05-gemini-b.md (by gemini) - summary-b`n" +
    "- projects/p2/discussion/2026-10-02-claude-c.md (by claude) - summary-c`n" +
    "- research/2026-10-03-claude-d.md (by claude) - summary-d`n" +
    "- projects/p3/discussion/2026-10-04-claude-gone.md (by claude) - summary-e`n" +
    "- text without a path`n`n## Next step`n- not a queue item.md`n")
  $o = RQ
  Expect 'exit 0' ($LASTEXITCODE -eq 0)
  Expect 'counts 6 items' ($o -match '\[QUEUE\] 6 item\(s\)')
  Expect 'items outside the review section are not counted' ($o -notmatch 'not a queue item')
  Expect 'per project: p1 has two' ($o -match 'p1\s+2')
  Expect 'per agent: claude has 4' ($o -match 'claude\s+4')
  Expect 'status wip -> NOT-DONE' ($o -match 'NOT-DONE\s+projects/p1/discussion/2026-10-05')
  Expect 'reviewed_by filled -> ALREADY-REVIEWED' ($o -match 'ALREADY-REVIEWED\s+projects/p2')
  Expect 'no front matter -> NO-FRONTMATTER' ($o -match 'NO-FRONTMATTER\s+research/2026-10-03')
  Expect 'missing file -> MISSING' ($o -match 'MISSING\s+projects/p3')
  Expect 'line without a path -> UNPARSED' ($o -match 'UNPARSED')
  Expect 'a healthy item is not flagged' ($o -notmatch '(NOT-DONE|ALREADY-REVIEWED|NO-FRONTMATTER|MISSING)\s+projects/p1/discussion/2026-10-01')
  Expect 'oldest first: 2026-10-01 before 2026-10-05' ($o.IndexOf('2026-10-01-claude-a.md', $o.IndexOf('[OLDEST]')) -lt $o.IndexOf('2026-10-05-gemini-b.md', $o.IndexOf('[OLDEST]')))

  # the legacy heading and the "(oleh agent)" form are still accepted
  W 'NOW.md' "# NOW`n`n## Belum di-review`n- projects/p1/discussion/2026-10-01-claude-a.md (oleh claude) - ringkas`n"
  $o = RQ
  Expect 'legacy heading Belum di-review and (oleh x) are accepted' (($o -match '\[QUEUE\] 1 item\(s\)') -and ($o -match 'claude\s+1'))

  # configurable state file and heading
  W 'STATE.md' "# S`n`n## Needs a look`n- research/2026-10-03-claude-d.md (by x) - d`n"
  $env:STATE_FILE = 'STATE.md'; $env:REVIEW_HEADING = 'Needs a look'
  $o = RQ
  Remove-Item Env:STATE_FILE, Env:REVIEW_HEADING
  Expect 'STATE_FILE and REVIEW_HEADING from the environment' ($o -match '\[QUEUE\] 1 item\(s\)')

  W 'NOW.md' "# NOW`n`n## Awaiting review`n"
  $o = RQ
  Expect 'empty queue -> 0 items' ($o -match '\[QUEUE\] 0 item\(s\)')
  Remove-Item (Join-Path $root 'NOW.md')
  Expect 'no state file -> NOW.md MISSING, exit 0' ((RQ) -match 'NOW\.md MISSING')
} finally { Remove-Item $root -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item Env:STATE_FILE, Env:REVIEW_HEADING -ErrorAction SilentlyContinue }
if ($fail -gt 0) { exit 1 } else { exit 0 }
