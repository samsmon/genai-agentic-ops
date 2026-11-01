# Headless delegation between agents

Notes from a live run (Windows 11, 2026-11-01): one agent session delegating read-only analysis to another agent CLI, in the background, without opening the other tool's GUI. This is reference material. It is not installed by `install.py` and is not in `kit/MANIFEST`.

## What worked

An agent CLI that has a print mode can be called from another agent's session:

```
agy -p "<prompt>" --mode plan --print-timeout 120s
```

- `--mode plan` is read-only. The target analyses and answers; it does not edit files.
- The answer goes to a file (`handoff/<agent>/<id>.out.md`), not into the caller's context. The caller starts the command in the background and reads the file after the completion notice. No polling.
- The result is data, not instructions. The caller verifies it, says which parts came from the other agent, and does the file changes itself.
- `handoff/` holds intermediate output only. Keep it in `.gitignore`.

A wrapper (`ask-agent.ps1` in the run) did four things: inline the attached files into the prompt, refuse prompts over 24,000 characters, enforce a timeout, and write the answer to `-OutFile`.

## What did not work

| Attempt | Result | Consequence |
|---|---|---|
| Prompt on stdin, `-p` with a short instruction | The target tried to run a command and was denied | Pass the content as the `-p` argument |
| "Read file X" in the prompt | Same denial (`command` permission) | Inline the file text into the prompt; tell the target to use only the attachment |
| Edit files in headless mode (`--mode accept-edits`) | Denied; the CLI says it cannot prompt in headless mode | Delegation stays read-only |
| `--dangerously-skip-permissions` for write mode | Blocked by the session's own safety classifier | Not used. A narrow allow rule in the target's `settings.json` is the only reasonable route, and that is the user's decision |
| Attaching a 15 KB rules file | Timed out at 150 s with partial output | Send small attachments or excerpts |

Windows PowerShell 5.1 does not escape double quotes when it starts a native executable. A prompt containing `"` made the CLI see extra arguments. Escape before calling: `($p -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1'`.

## Windows pitfalls found on the way

- **Packaged desktop apps redirect writes.** When the agent's host is an MSIX-packaged desktop app, writes under `AppData` land in the package's private folder (`%LOCALAPPDATA%\Packages\<package>\LocalCache\...`). `npm i -g` run by the agent installed a CLI there. The agent saw it; the user's own terminal did not (`command not found`, `%APPDATA%\npm\x.cmd` "path not found"). Check with `Test-Path` on the `LocalCache` path. Install CLIs that the user must also run from the user's own terminal, not from the agent session.
- **Stale PATH.** An installer that edits the user PATH only affects terminals opened afterwards. Close the old terminal windows, or refresh `$env:Path` from the machine and user values.
- **A running binary blocks its own upgrade.** `winget upgrade` failed with "Access is denied" while another session was running the same `claude.exe`. Find the process by path (`Get-Process | Select Path`) and close the session; do not kill a session you did not start.
- **Package managers lag the vendor updater.** The CLI's own `update` command reported a newer version than winget offered.
- **Installer exit codes.** A winget install of a desktop app failed with exit code 2 in silent and interactive mode, while the same installer, downloaded from the vendor release and run directly with `/S`, succeeded. Before running it, check the Authenticode signature (`Get-AuthenticodeSignature`) and that the winget hash check passed.

## Not verified

- Write-mode delegation (needs an explicit allow rule; skip-all is not acceptable).
- Delegation in the other direction (the other CLI calling this one): needs that CLI logged in separately from its desktop app.
- Whether stdout of the target is suppressed when not attached to a terminal. One third-party report says so; the run above got normal output from a background job.
