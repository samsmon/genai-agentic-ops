// agentic-ops guard for OpenCode (experimental): thin adapter over the agent-neutral policy core.
// Install as .opencode/plugins/agentic-ops-guard.js (loaded automatically, no opencode.json entry needed).
//
// Runs `python -I core/policy.py` as a child process for every shell tool call and throws to block it.
// OpenCode plugins cannot ask the user, so an "ask" decision is turned into a block that tells the agent to
// get the user's confirmation first (ASK_AS = "allow" lets those commands through instead).
// Fails open: a missing python or core never blocks a session.
//
// Experimental: the docs show tool.execute.before(input, output), input.tool and output.args, and that
// throwing blocks the call; they do not name the shell tool's argument. This reads output.args.command and
// falls back to output.args.cmd. The tools page names the shell tool "shell" ("bash" is also accepted).
import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { join } from "node:path"

const ASK_AS = "deny"
const SHELL_TOOLS = new Set(["shell", "bash"])

export function findCore(directory) {
  const candidates = [
    process.env.AGENTIC_OPS_POLICY,
    join(directory, "scripts", "agentic-ops", "core", "policy.py"),
    join(directory, "kit", "core", "policy.py"),
  ]
  return candidates.find((c) => c && existsSync(c))
}

export function decide(command, core, python = process.env.AGENTIC_OPS_PYTHON || (process.platform === "win32" ? "python" : "python3")) {
  try {
    const r = spawnSync(python, ["-I", core], { input: JSON.stringify({ command }), encoding: "utf8" })
    return JSON.parse(r.stdout)
  } catch {
    return { decision: "allow", message: "" }
  }
}

export const AgenticOpsGuard = async ({ directory }) => {
  const core = findCore(directory)
  return {
    "tool.execute.before": async (input, output) => {
      if (!core || !SHELL_TOOLS.has(String(input.tool))) return
      const command = output?.args?.command ?? output?.args?.cmd
      if (!command) return
      const { decision, message } = decide(String(command), core)
      if (decision === "deny") throw new Error(message)
      if (decision === "ask" && ASK_AS === "deny") {
        throw new Error("CONFIRMATION REQUIRED (this plugin cannot ask in OpenCode): stop and ask the user before running this. " + message)
      }
    },
  }
}
