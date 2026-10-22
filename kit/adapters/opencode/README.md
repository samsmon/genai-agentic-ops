# OpenCode adapter (experimental)

Guard for shell commands through an OpenCode plugin. Status: experimental, not tested live (see the matrix in `../../README.md`).

## Install

1. Copy `core/policy.py` to `scripts/agentic-ops/core/policy.py` in the project (shared by all adapters).
2. Copy `agentic-ops-guard.js` to `.opencode/plugins/agentic-ops-guard.js`. Files in that folder load automatically; no `opencode.json` entry is needed.
3. Python must be on the path (`python` on Windows, `python3` elsewhere; override with `AGENTIC_OPS_PYTHON`).

## Behavior and limits

- On every call of the `shell` (or `bash`) tool the plugin runs `python -I core/policy.py` and throws an Error to block the call. The agent sees the message.
- OpenCode plugins cannot ask the user, so a risky command is blocked with a "get the user's confirmation" message. Set `ASK_AS = "allow"` in the file to let those through.
- Experimental because the docs name the hook and the throw-to-block behavior but not the shell tool's argument name. The plugin reads `args.command`, then `args.cmd`. If your OpenCode version uses another name, nothing is blocked (fails open); check `output.args` in a test run and adjust.
- No read guard (the read tool's arguments are not documented).
- The kit test runs the plugin on Node with fixture inputs. It has not run on OpenCode's own Bun runtime.
