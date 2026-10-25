"""Tests for the Codex, Cursor, Antigravity and OpenCode adapters with payloads that follow each tool's docs.

Fixtures: kit/tests/fixtures/*.json (source URLs and access dates are inside each file).
This checks payload handling and answer format only; it does not prove the hook fires inside the real tool.
Run: python -I kit/tests/test_adapters.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.abspath(os.path.join(HERE, ".."))
FIX = os.path.join(HERE, "fixtures")
fail = 0


def expect(name, ok):
    global fail
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fail += 1


def cases(tool):
    with open(os.path.join(FIX, tool + ".json"), encoding="utf-8") as f:
        return json.load(f)["cases"]


def run(script, payload, env=None):
    e = dict(os.environ)
    e.pop("AGENTIC_OPS_POLICY", None)
    e.update(env or {})
    return subprocess.run([sys.executable, "-I", script], input=payload if isinstance(payload, str) else json.dumps(payload),
                          capture_output=True, text=True, env=e)


# --- Codex: exit 2 + stderr = deny; exit 0 and silent = allow
codex = os.path.join(KIT, "adapters", "codex", "guard.py")
for c in cases("codex"):
    r = run(codex, c["payload"])
    got = "deny" if r.returncode == 2 else "allow"
    ok = got == c["expect"] and r.returncode in (0, 2)
    if ok and c.get("message_contains"):
        ok = c["message_contains"] in r.stderr
    if ok and got == "allow":
        ok = r.stdout == "" and r.stderr == ""
    expect("codex: " + c["name"], ok)
expect("codex: broken input allows", run(codex, "not json").returncode == 0)

# --- Cursor: stdout {"permission": ...}, exit 0
cursor = os.path.join(KIT, "adapters", "cursor", "guard.py")
for c in cases("cursor"):
    r = run(cursor, c["payload"])
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = {}
    ok = r.returncode == 0 and out.get("permission") == c["expect"]
    if ok and c["expect"] != "allow":
        ok = bool(out.get("user_message")) and bool(out.get("agent_message"))
    expect("cursor: " + c["name"], ok)
expect("cursor: broken input answers allow", json.loads(run(cursor, "not json").stdout).get("permission") == "allow")

# --- Antigravity: stdout {"decision": ...}, exit 0
anti = os.path.join(KIT, "adapters", "antigravity", "guard.py")
for c in cases("antigravity"):
    r = run(anti, c["payload"])
    try:
        out = json.loads(r.stdout)
    except ValueError:
        out = {}
    ok = r.returncode == 0 and out.get("decision") == c["expect"]
    if ok and c["expect"] != "allow":
        ok = bool(out.get("reason"))
    if ok and c.get("message_contains"):
        ok = c["message_contains"] in out.get("reason", "")
    expect("antigravity: " + c["name"], ok)
expect("antigravity: broken input answers allow", json.loads(run(anti, "not json").stdout).get("decision") == "allow")
ask_case = [c for c in cases("antigravity") if c["expect"] == "deny" and "recursive" in c["name"]][0]
r = run(anti, ask_case["payload"], env={"AGENTIC_OPS_ASK_AS": "ask"})
expect("antigravity: AGENTIC_OPS_ASK_AS=ask restores the ask answer", json.loads(r.stdout).get("decision") == "ask")

# --- hooks.json files are valid and point at the installed guard path
for tool, key_path in (("codex", ".codex/hooks/guard.py"), ("cursor", ".cursor/hooks/guard.py"), ("antigravity", "hooks/guard.py")):
    p = os.path.join(KIT, "adapters", tool, "hooks.json")
    try:
        text = open(p, encoding="utf-8").read()
        json.loads(text)
        expect(f"{tool}: hooks.json is valid JSON and names {key_path}", key_path in text.replace("\\\\", "/"))
    except ValueError:
        expect(f"{tool}: hooks.json is valid JSON", False)

# --- every hook command uses python -B (no __pycache__ in tracked or overlay folders)
for rel in ("claude/settings.json", "adapters/codex/hooks.json", "adapters/cursor/hooks.json", "adapters/antigravity/hooks.json"):
    text = open(os.path.join(KIT, *rel.split("/")), encoding="utf-8").read()
    cmds = [m for m in __import__("re").findall(r'"(?:command|commandWindows)":\s*"((?:[^"\\]|\\.)*)"', text)]
    expect(f"{rel}: every python command has -B", bool(cmds) and all(" -B " in c for c in cmds if c.startswith("python")))
js = open(os.path.join(KIT, "adapters", "opencode", "agentic-ops-guard.js"), encoding="utf-8").read()
expect("opencode plugin spawns python with -B", '["-B", "-I", core]' in js)

# --- the Antigravity hook command: the IDE splits it on spaces and runs it with no shell, from the folder of hooks.json (.agents/)
with tempfile.TemporaryDirectory() as proj:
    shutil.copytree(os.path.join(KIT, "core"), os.path.join(proj, "scripts", "agentic-ops", "core"), ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(proj, ".agents", "hooks"))
    shutil.copy(os.path.join(KIT, "adapters", "antigravity", "guard.py"), os.path.join(proj, ".agents", "hooks", "guard.py"))
    shutil.copy(os.path.join(KIT, "adapters", "antigravity", "hooks.json"), os.path.join(proj, ".agents", "hooks.json"))
    hook = json.load(open(os.path.join(proj, ".agents", "hooks.json"), encoding="utf-8"))["agentic-ops-guard"]["PreToolUse"][0]["hooks"][0]["command"]
    expect("antigravity hooks.json command has no quotes or shell characters", not any(ch in hook for ch in "\"'|&;<>$`()"))
    expect("antigravity hooks.json command uses python -B", hook.startswith("python -B "))
    env = {k: v for k, v in os.environ.items() if k != "AGENTIC_OPS_POLICY"}

    def payload(c):
        return json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": c}}})

    for label, c, want in (("force push", "git push --force origin main", "deny"), ("git status", "git status", "allow"), ("amend", "git commit --amend --allow-empty -m x", "allow")):
        r = subprocess.run(hook.split(" "), cwd=os.path.join(proj, ".agents"), input=payload(c), capture_output=True, text=True, env=env)
        try:
            got = json.loads(r.stdout).get("decision")
        except ValueError:
            got = None
        expect(f"antigravity hook (split on spaces, no shell, cwd = .agents): {label} is {want}", r.returncode == 0 and got == want)
    left = [d for d, _, fs in os.walk(proj) if "__pycache__" in d]
    expect("antigravity hook run leaves no __pycache__", not left)
    # the quoted one-liner of v2.3.0 and v2.3.1 breaks under a runner that splits on spaces (kept as a regression check)
    bad_cmd = 'python -B -I -c "import os,runpy;p=next((q for q in (\'hooks/guard.py\',) if os.path.isfile(q)),None);p and runpy.run_path(p)"'
    r = subprocess.run(bad_cmd.split(" "), cwd=os.path.join(proj, ".agents"), input=payload("git status"), capture_output=True, text=True, env=env)
    expect("regression: a command with nested quotes fails when split on spaces (why the shipped command has none)", r.returncode != 0)

# --- installed layout: core in scripts/agentic-ops/core, adapter in the tool's own folder
with tempfile.TemporaryDirectory() as proj:
    shutil.copytree(os.path.join(KIT, "core"), os.path.join(proj, "scripts", "agentic-ops", "core"), ignore=shutil.ignore_patterns("__pycache__"))
    for tool, folder in (("codex", ".codex"), ("cursor", ".cursor"), ("antigravity", ".agents")):
        os.makedirs(os.path.join(proj, folder, "hooks"))
        shutil.copy(os.path.join(KIT, "adapters", tool, "guard.py"), os.path.join(proj, folder, "hooks", "guard.py"))
    os.makedirs(os.path.join(proj, ".claude", "hooks"))
    shutil.copy(os.path.join(KIT, "claude", "hooks", "guard.py"), os.path.join(proj, ".claude", "hooks", "guard.py"))
    bad = {"command": "git commit --no-verify -m x"}
    r = run(os.path.join(proj, ".codex", "hooks", "guard.py"), {"tool_name": "Bash", "tool_input": bad})
    expect("installed layout: codex finds core", r.returncode == 2)
    r = run(os.path.join(proj, ".cursor", "hooks", "guard.py"), bad)
    expect("installed layout: cursor finds core", json.loads(r.stdout).get("permission") == "deny")
    r = run(os.path.join(proj, ".agents", "hooks", "guard.py"), {"toolCall": {"name": "run_command", "args": {"CommandLine": bad["command"]}}})
    expect("installed layout: antigravity finds core", json.loads(r.stdout).get("decision") == "deny")
    r = run(os.path.join(proj, ".claude", "hooks", "guard.py"), {"tool_name": "Bash", "tool_input": bad})
    expect("installed layout: claude finds core", r.returncode == 2)
    shutil.rmtree(os.path.join(proj, "scripts"))
    r = run(os.path.join(proj, ".codex", "hooks", "guard.py"), {"tool_name": "Bash", "tool_input": bad})
    expect("missing core fails open with a warning (codex)", r.returncode == 0 and "core/policy.py not found" in r.stderr)
    r = run(os.path.join(proj, ".cursor", "hooks", "guard.py"), bad)
    expect("missing core fails open (cursor)", json.loads(r.stdout).get("permission") == "allow")
    r = run(os.path.join(proj, ".claude", "hooks", "guard.py"), {"tool_name": "Bash", "tool_input": bad})
    expect("missing core fails open (claude)", r.returncode == 0)

# --- OpenCode plugin: needs node (the plugin is plain ESM; OpenCode itself runs it on Bun)
node = shutil.which("node")
if node:
    r = subprocess.run([node, os.path.join(HERE, "opencode-plugin.test.mjs")], capture_output=True, text=True, encoding="utf-8")
    for line in r.stdout.splitlines():
        if line.startswith(("ok   ", "FAIL ")):
            print("opencode: " + line)
    expect("opencode: plugin test run succeeded", r.returncode == 0)
else:
    print("SKIP opencode: node not found")

print("ALL TESTS PASSED" if not fail else f"{fail} FAILED")
sys.exit(1 if fail else 0)
