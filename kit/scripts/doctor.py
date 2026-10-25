#!/usr/bin/env python3
"""agentic-ops doctor (read-only): what is installed, what is enforced by a machine, what is only text.

  python doctor.py [--project DIR] [--pin SHA]

One line per check: PASS, WARN, FAIL or UNKNOWN. UNKNOWN means it cannot be proven from here (for example that a hook
really fires inside an IDE). There is no overall score. Exit code 0 when there is no FAIL, 1 otherwise.
It reads the install receipt (scripts/agentic-ops/INSTALLED.json) written by kit/install.* and compares the files.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

RECEIPT = "scripts/agentic-ops/INSTALLED.json"
TOOL_DIRS = {"claude": ".claude", "codex": ".codex", "cursor": ".cursor", "antigravity": ".agents", "opencode": ".opencode"}
ALL_TOOLS = tuple(TOOL_DIRS)
rows = []


def add(status, label, detail=""):
    rows.append((status, label, detail))


def git(project, *args):
    r = subprocess.run(["git", "-C", project] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout.strip()


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def walk_files(root):
    for d, dirs, fs in os.walk(root):
        for f in fs:
            yield os.path.join(d, f)


def load_policy(project):
    p = os.path.join(project, "scripts", "agentic-ops", "core", "policy.py")
    if not os.path.isfile(p):
        return None
    try:
        spec = importlib.util.spec_from_file_location("agentic_ops_policy_doctor", p)
        mod = importlib.util.module_from_spec(spec)
        sys.dont_write_bytecode = True
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:  # noqa: BLE001
        add("FAIL", "policy.py imports", str(e)[:120])
        return False


def run_guard(args, payload, cwd):
    r = subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace")
    return r


def check_adapters(project, tools):
    force = "git push --force origin main"
    plain = "git status"
    for t in tools:
        d = os.path.join(project, TOOL_DIRS[t])
        if t == "opencode":
            f = os.path.join(d, "plugins", "agentic-ops-guard.js")
            add("PASS" if os.path.isfile(f) else "FAIL", "opencode: plugin file present", ".opencode/plugins/agentic-ops-guard.js")
            add("UNKNOWN", "opencode: plugin blocks a command", "the doctor does not run the plugin (it needs Bun or node); see kit/tests/opencode-plugin.test.mjs")
            continue
        guard = os.path.join(d, "hooks", "guard.py")
        if not os.path.isfile(guard):
            add("FAIL", f"{t}: guard script present", os.path.relpath(guard, project))
            continue
        py = [sys.executable, "-B", "-I", guard]
        try:
            if t == "claude":
                bad = run_guard(py, {"tool_name": "Bash", "tool_input": {"command": force}}, project)
                ok = bad.returncode == 2 or '"ask"' in bad.stdout
                good = run_guard(py, {"tool_name": "Bash", "tool_input": {"command": plain}}, project)
                add("PASS" if ok and good.returncode == 0 else "FAIL", "claude: guard asks before a force push, allows git status")
            elif t == "codex":
                bad = run_guard(py, {"tool_name": "Bash", "tool_input": {"command": force}}, project)
                good = run_guard(py, {"tool_name": "Bash", "tool_input": {"command": plain}}, project)
                add("PASS" if bad.returncode == 2 and good.returncode == 0 else "FAIL", "codex: guard blocks a force push (no ask in Codex), allows git status")
            elif t == "cursor":
                bad = run_guard(py, {"command": force}, project)
                good = run_guard(py, {"command": plain}, project)
                gb = json.loads(bad.stdout or "{}").get("permission")
                gg = json.loads(good.stdout or "{}").get("permission")
                add("PASS" if gb in ("ask", "deny") and gg == "allow" else "FAIL", "cursor: guard asks before a force push, allows git status")
            elif t == "antigravity":
                mk = lambda c: {"toolCall": {"name": "run_command", "args": {"CommandLine": c}}}
                bad = run_guard(py, mk(force), project)
                good = run_guard(py, mk(plain), project)
                gb = json.loads(bad.stdout or "{}").get("decision")
                gg = json.loads(good.stdout or "{}").get("decision")
                add("PASS" if gb == "deny" and gg == "allow" else "FAIL",
                    "antigravity: guard denies a force push (ask is answered as deny), allows git status", f"got {gb}/{gg}")
                cfg = os.path.join(d, "hooks.json")
                try:
                    cmd = json.load(open(cfg, encoding="utf-8"))["agentic-ops-guard"]["PreToolUse"][0]["hooks"][0]["command"]
                    ok = True
                    for cwd in (project, d):
                        r = subprocess.run(cmd, shell=True, cwd=cwd, input=json.dumps(mk(force)), capture_output=True, text=True)
                        ok = ok and r.returncode == 0 and json.loads(r.stdout or "{}").get("decision") == "deny"
                    add("PASS" if ok else "FAIL", "antigravity: hooks.json command works from the project root and from .agents/")
                except Exception as e:  # noqa: BLE001
                    add("FAIL", "antigravity: hooks.json command is valid", str(e)[:100])
        except Exception as e:  # noqa: BLE001
            add("FAIL", f"{t}: guard runs", str(e)[:100])
        cfg_name = {"claude": "settings.json", "codex": "hooks.json", "cursor": "hooks.json", "antigravity": "hooks.json"}[t]
        cfg = os.path.join(d, cfg_name)
        try:
            text = open(cfg, encoding="utf-8").read()
            json.loads(text)
            add("PASS" if "guard.py" in text else "FAIL", f"{t}: {TOOL_DIRS[t]}/{cfg_name} is valid JSON and calls the guard")
        except (OSError, ValueError):
            add("FAIL", f"{t}: {TOOL_DIRS[t]}/{cfg_name} is valid JSON")
        add("UNKNOWN", f"{t}: the hook fires inside the real tool", "cannot be proven from here; see the matrix in kit/README.md (tested live only for Antigravity deny, one model, one machine)")


def main():
    ap = argparse.ArgumentParser(description="agentic-ops doctor (read-only)")
    ap.add_argument("--project", default="")
    ap.add_argument("--pin", default="", help="expected pin sha to compare with the receipt")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    start = a.project or os.getcwd()
    rc, top = git(start, "rev-parse", "--show-toplevel")
    project = os.path.normpath(top) if rc == 0 and top else os.path.abspath(start)
    print(f"agentic-ops doctor: {project}")

    # AGENTS.md
    ag = os.path.join(project, "AGENTS.md")
    if not os.path.isfile(ag):
        add("FAIL", "AGENTS.md exists")
    else:
        t = open(ag, encoding="utf-8", errors="replace").read()
        b, e = len(re.findall(r"BEGIN genai-agentic-ops", t)), len(re.findall(r"END genai-agentic-ops", t))
        add("PASS" if (b == 1 and e == 1) else "FAIL", "AGENTS.md has one rules block with paired markers", f"BEGIN={b} END={e}")
        size = os.path.getsize(ag)
        add("PASS" if size <= 24000 else "WARN", "AGENTS.md under Antigravity's 24,000 byte limit", f"{size} bytes")

    # receipt
    rp = os.path.join(project, *RECEIPT.split("/"))
    receipt = None
    if os.path.isfile(rp):
        try:
            receipt = json.load(open(rp, encoding="utf-8"))
            add("PASS", "install receipt", f"source={receipt.get('source')} tools={','.join(receipt.get('tools', [])) or '-'} "
                f"modules={','.join(receipt.get('modules', []))} visibility={receipt.get('visibility')} policy={receipt.get('policy')}")
        except ValueError:
            add("FAIL", "install receipt is valid JSON", RECEIPT)
    else:
        add("WARN", "install receipt present", f"{RECEIPT} not found: installed by hand, or not installed (kit/install.* writes it)")
    tools = [t for t in (receipt or {}).get("tools", []) if t in ALL_TOOLS] if receipt else \
        [t for t in ALL_TOOLS if os.path.isdir(os.path.join(project, TOOL_DIRS[t]))]
    modules = (receipt or {}).get("modules", [])

    if a.pin and receipt:
        src = str(receipt.get("source", ""))
        add("PASS" if src.endswith(a.pin) else "WARN", "installed from the expected pin", f"receipt {src}, expected pin:{a.pin[:12]}")
    elif receipt:
        add("UNKNOWN", "installed pin is the latest", "pass --pin <sha> to compare; a local kit has no pin")

    # files against the receipt
    if receipt:
        missing, changed = [], []
        for rel, h in receipt.get("files", {}).items():
            p = os.path.join(project, *rel.split("/"))
            if not os.path.isfile(p):
                missing.append(rel)
            elif rel.endswith((".json",)):
                continue  # merged files legitimately differ from the kit copy
            elif sha(p) != h:
                changed.append(rel)
        add("PASS" if not missing else "FAIL", "every installed file is present", ", ".join(missing[:5]) or f"{len(receipt.get('files', {}))} files")
        add("PASS" if not changed else "WARN", "installed files match the kit copy", ("modified locally: " + ", ".join(changed[:5])) if changed else "no local edits")

    # extra copies, bytecode, adapters that were not chosen
    agentic_dirs = [os.path.join(project, p) for p in ("scripts/agentic-ops", ".claude", ".codex", ".cursor", ".agents", ".opencode", ".githooks")]
    pyc, by_hash = [], {}
    for root in agentic_dirs:
        if os.path.isdir(root):
            for f in walk_files(root):
                rel = os.path.relpath(f, project).replace("\\", "/")
                if "__pycache__" in rel or rel.endswith(".pyc"):
                    pyc.append(rel)
                else:
                    by_hash.setdefault(sha(f), []).append(rel)
    add("PASS" if not pyc else "WARN", "no bytecode (__pycache__, .pyc) in agentic folders", ", ".join(pyc[:4]))
    dups = [v for v in by_hash.values() if len(v) > 1]
    add("PASS" if not dups else "WARN", "no duplicate copies of the same file in agentic folders", "; ".join(" = ".join(v) for v in dups[:3]))
    if receipt:
        extra = [t for t in ALL_TOOLS if t not in tools and os.path.isdir(os.path.join(project, TOOL_DIRS[t]))
                 and os.path.isfile(os.path.join(project, TOOL_DIRS[t], "hooks", "guard.py"))]
        add("PASS" if not extra else "WARN", "only the chosen tools have adapters installed", ("not chosen but present: " + ", ".join(extra)) if extra else ",".join(tools) or "-")

    # git hooks and prerequisites
    if "githooks" in modules or os.path.isdir(os.path.join(project, ".githooks")):
        rc, hp = git(project, "config", "--get", "core.hooksPath")
        add("PASS" if hp == ".githooks" else "WARN", "core.hooksPath is .githooks (git hooks active)", hp or "(unset)")
        add("PASS" if os.path.isfile(os.path.join(project, ".githooks", "commit-msg")) else "FAIL", ".githooks/commit-msg present")
    if not shutil.which("python") and not shutil.which("python3"):
        add("WARN", "python is on PATH", "the guard hooks call python; without it they fail open")
    if os.name == "nt" and ("scripts" in modules or "githooks" in modules):
        sh = shutil.which("sh") or any(os.path.isfile(os.path.join(r, *p.split("/"))) for r in
                                       (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")) for p in ("Git/bin/sh.exe", "Git/usr/bin/sh.exe"))
        add("PASS" if sh else "WARN", "sh is available for commit-msg-check", "Git for Windows ships it" if not sh else "")

    # policy core and per-tool adapters
    pol = load_policy(project)
    if pol is None:
        if tools:
            add("FAIL", "scripts/agentic-ops/core/policy.py present")
    elif pol is not False:
        got = [pol.evaluate(command=c)[0] for c in ("git status", "git commit --no-verify -m x", "git push --force origin main")]
        add("PASS" if got == ["allow", "deny", "ask"] else "FAIL", "policy core answers allow / deny / ask for 3 sample commands", "/".join(got))
        check_adapters(project, tools)
    if not tools:
        add("WARN", "a guard adapter is installed for at least one tool", "no tool chosen: the rules are text only here, git hooks still apply")
    else:
        texty = [t for t in ALL_TOOLS if t not in tools]
        if texty:
            add("UNKNOWN", "tools without an installed hook follow the rules as text only", ", ".join(texty) + " (git hooks still cover anything that commits)")

    # hidden mode overlay
    ov = os.path.join(project, ".git", "agentic")
    vis = (receipt or {}).get("visibility")
    if vis == "hidden" or os.path.isdir(ov):
        exc = os.path.join(project, ".git", "info", "exclude")
        et = open(exc, encoding="utf-8", errors="replace").read() if os.path.isfile(exc) else ""
        add("PASS" if "BEGIN agentic-ops" in et else "FAIL", "hidden mode: .git/info/exclude has the agentic block")
        add("PASS" if os.path.isdir(ov) else "FAIL", "hidden mode: overlay git dir (.git/agentic) exists")
        rc, tracked = git(project, "ls-files", "--", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".claude/", ".cursor/", ".codex/", ".agents/", ".opencode/",
                          ".githooks/", "scripts/agentic-ops/", "docs/CURRENT_OPS.md")
        add("PASS" if not tracked else "FAIL", "hidden mode: no agentic file is tracked in the project history", tracked.replace("\n", ", ")[:160])
        if os.path.isdir(ov):
            og = ["git", f"--git-dir={ov}", f"--work-tree={project}"]
            r = subprocess.run(og + ["ls-files"], capture_output=True, text=True, encoding="utf-8", errors="replace")
            files = r.stdout.split()
            bad = [f for f in files if "__pycache__" in f or f.endswith(".pyc")]
            add("PASS" if not bad else "WARN", "overlay tracks no bytecode", ", ".join(bad[:4]))
            names = {}
            for f in files:
                p = os.path.join(project, *f.split("/"))
                if os.path.isfile(p):
                    names.setdefault(sha(p), []).append(f)
            d2 = [v for v in names.values() if len(v) > 1]
            add("PASS" if not d2 else "WARN", "overlay tracks no duplicate copies", "; ".join(" = ".join(v) for v in d2[:3]))
            lf = os.path.join(project, ".agentic-files")
            default = ["AGENTS.md", "CLAUDE.md", "GEMINI.md", ".cursorrules", "docs/CURRENT_OPS.md", "docs/CURRENT_OPS-archive.md",
                       "docs/HARNESS_DECLINED.md", ".claude/", ".cursor/", ".codex/", ".agents/", ".agent/", ".opencode/", ".githooks/",
                       "scripts/agentic-ops/", ".agentic-files"]
            pats = default
            if os.path.isfile(lf):
                pats = [l.strip() for l in open(lf, encoding="utf-8").read().splitlines() if l.strip() and not l.strip().startswith("#")]
            r = subprocess.run(og + ["status", "--short", "--untracked-files=all", "--"] + pats + [":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            pending = [l for l in r.stdout.splitlines() if l.strip()]
            add("PASS" if not pending else "WARN", "overlay has no uncommitted agentic files (otherwise: agentic-sync commit, then push)",
                f"{len(pending)} file(s)" if pending else "")
            r = subprocess.run(og + ["rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
            br = r.stdout.strip()
            r = subprocess.run(og + ["rev-list", "--left-right", "--count", f"{br}...refs/remotes/agentic/{br}"], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.split():
                ahead, behind = r.stdout.split()[:2]
                add("PASS" if (ahead, behind) == ("0", "0") else "WARN", "overlay is in sync with its remote (as of the last fetch)", f"ahead {ahead}, behind {behind}")
            else:
                add("UNKNOWN", "overlay is in sync with its remote", "no remote-tracking branch yet (never pushed or fetched)")

    w = max(len(r[1]) for r in rows)
    for s, l, d in rows:
        print(f"{s:<7} {l:<{w}}" + (f"  {d}" if d else ""))
    n = {k: sum(1 for r in rows if r[0] == k) for k in ("PASS", "WARN", "FAIL", "UNKNOWN")}
    print(f"[DOCTOR] {n['PASS']} pass, {n['WARN']} warn, {n['FAIL']} fail, {n['UNKNOWN']} unknown")
    return 1 if n["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
