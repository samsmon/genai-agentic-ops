// Runs the OpenCode adapter with the cases in fixtures/opencode.json. Run: node kit/tests/opencode-plugin.test.mjs
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath, pathToFileURL } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const kit = join(here, "..")
const { AgenticOpsGuard } = await import(pathToFileURL(join(kit, "adapters", "opencode", "agentic-ops-guard.js")).href)
const fixtures = JSON.parse(readFileSync(join(here, "fixtures", "opencode.json"), "utf8"))

// the kit layout has core at <repo>/kit/core, so point the plugin at the repo root's kit/ via AGENTIC_OPS_POLICY
process.env.AGENTIC_OPS_POLICY = join(kit, "core", "policy.py")
let fail = 0
const hooks = await AgenticOpsGuard({ directory: join(kit, "..") })
const before = hooks["tool.execute.before"]

for (const c of fixtures.cases) {
  let result = "allow"
  let message = ""
  try {
    await before({ ...c.input }, { args: { ...c.args } })
  } catch (e) {
    result = "block"
    message = String(e.message)
  }
  let ok = result === c.expect
  if (ok && c.message_contains) ok = message.includes(c.message_contains)
  console.log((ok ? "ok   " : `FAIL (got ${result}) `) + c.name)
  if (!ok) fail++
}

// without a core the plugin does nothing
delete process.env.AGENTIC_OPS_POLICY
const none = await AgenticOpsGuard({ directory: join(here, "no-such-dir") })
let blocked = false
try {
  await none["tool.execute.before"]({ tool: "shell" }, { args: { command: "git commit --no-verify" } })
} catch {
  blocked = true
}
console.log((blocked ? "FAIL " : "ok   ") + "missing core fails open")
if (blocked) fail++

console.log(fail ? `${fail} FAILED` : "ALL TESTS PASSED")
process.exit(fail ? 1 : 0)
