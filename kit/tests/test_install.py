"""Tests for kit/install.py (and its install.sh / install.ps1 entries) and kit/scripts/doctor.py, on temporary git projects.

Run: python -I kit/tests/test_install.py     (needs git; the sh entry needs sh, the PowerShell entry needs powershell)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.abspath(os.path.join(HERE, ".."))
INSTALL = os.path.join(KIT, "install.py")
DOCTOR = os.path.join(KIT, "scripts", "doctor.py")
ENV = dict(os.environ, GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="t@example.test",
           GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="t@example.test", PYTHONDONTWRITEBYTECODE="1")
ENV.pop("AGENTIC_OPS_POLICY", None)
fail = 0


def expect(name, ok):
    global fail
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fail += 1


def git(cwd, *a):
    return subprocess.run(["git", "-C", cwd] + list(a), capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")


def mkproject(base, name, remote=True):
    proj = os.path.join(base, name)
    os.makedirs(proj)
    git(proj, "init", "-q", "-b", "main")
    with open(os.path.join(proj, "README.md"), "w") as f:
        f.write("# project\n")
    git(proj, "add", "README.md")
    git(proj, "commit", "-q", "-m", "chore: init")
    if remote:
        bare = os.path.join(base, name + ".git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], env=ENV)
        git(proj, "remote", "add", "origin", bare)
        git(proj, "push", "-q", "-u", "origin", "main")
    return proj


def inst(project, *args, entry=None):
    cmd = (entry or [sys.executable, "-B", INSTALL]) + ["--project", project, "--kit-dir", KIT] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")


def tree(project):
    out = {}
    for d, dirs, fs in os.walk(project):
        dirs[:] = [x for x in dirs if x != ".git"]
        for f in fs:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, project).replace("\\", "/")] = hashlib.sha256(fh.read()).hexdigest()
    return out


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def doctor(project, *args):
    r = subprocess.run([sys.executable, "-B", DOCTOR, "--project", project] + list(args), capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")
    return r


BASE = tempfile.mkdtemp(prefix="agentic-install-")
try:
    A = ["--tools", "antigravity", "--modules", "guard,githooks,scripts", "--shell", "sh"]

    # ---- dry run writes nothing
    p = mkproject(BASE, "dry")
    before = tree(p)
    r = inst(p, *A, "--visibility", "visible")
    expect("dry run: exit 0 and says nothing was written", r.returncode == 0 and "Dry run: nothing was written" in r.stdout)
    expect("dry run: the project tree is unchanged", tree(p) == before)

    # ---- visible install of one tool only
    r = inst(p, *A, "--visibility", "visible", "--apply")
    expect("visible install: exit 0", r.returncode == 0)
    t = tree(p)
    expect("visible install: antigravity adapter and hooks.json present", ".agents/hooks/guard.py" in t and ".agents/hooks.json" in t)
    expect("visible install: no other tool's folder", not any(x.startswith((".codex/", ".cursor/", ".opencode/", ".claude/")) for x in t))
    expect("visible install: no bytecode", not any("__pycache__" in x or x.endswith(".pyc") for x in t))
    kit_files = [x for x in t if x.startswith("scripts/agentic-ops/") and not x.endswith("INSTALLED.json")]
    seen = {}
    for x in kit_files:
        seen.setdefault((os.path.basename(x), t[x]), []).append(x)
    expect("visible install: no file is installed twice", all(len(v) == 1 for v in seen.values()))
    expect("visible install: only the sh scripts, no ps1", any(x.endswith(".sh") for x in kit_files) and not any(x.endswith(".ps1") for x in kit_files))
    ag = read(os.path.join(p, "AGENTS.md"))
    expect("visible install: AGENTS.md has one block and the git policy line is replaced",
           ag.count("BEGIN genai-agentic-ops") == 1 and ag.count("END genai-agentic-ops") == 1 and "<!-- GIT-POLICY -->" not in ag and "agent-commits" in ag)
    expect("visible install: no hidden-mode section (visible)", ".git/agentic" not in ag)
    expect("visible install: ops log and archive created", "docs/CURRENT_OPS.md" in t and "docs/CURRENT_OPS-archive.md" in t)
    expect("visible install: core.hooksPath set to .githooks", git(p, "config", "--get", "core.hooksPath").stdout.strip() == ".githooks")
    expect("visible install: nothing committed", git(p, "log", "--oneline").stdout.count("\n") == 1)
    receipt = json.loads(read(os.path.join(p, "scripts", "agentic-ops", "INSTALLED.json")))
    expect("receipt lists the chosen tool and every installed file hash", receipt["tools"] == ["antigravity"] and len(receipt["files"]) > 10)

    # ---- idempotent
    r = inst(p, *A, "--visibility", "visible", "--apply")
    expect("second run: nothing to do", r.returncode == 0 and "Nothing to do" in r.stdout and tree(p) == t)

    # ---- doctor on a healthy install, then on broken ones
    r = doctor(p)
    expect("doctor: healthy visible install has no FAIL (exit 0)", r.returncode == 0 and "0 fail" in r.stdout)
    expect("doctor: antigravity guard denies a force push (ask answered as deny)", "PASS    antigravity: guard denies a force push" in r.stdout)
    expect("doctor: lists the hook-fires check as UNKNOWN", "UNKNOWN antigravity: the hook fires inside the real tool" in r.stdout)
    expect("doctor: lists tools without a hook as text only", "UNKNOWN tools without an installed hook" in r.stdout)
    expect("doctor: read-only (tree unchanged)", tree(p) == t)
    os.makedirs(os.path.join(p, ".agents", "hooks", "__pycache__"))
    open(os.path.join(p, ".agents", "hooks", "__pycache__", "guard.cpython-311.pyc"), "w").close()
    r = doctor(p)
    expect("doctor: warns about bytecode", "WARN    no bytecode" in r.stdout and r.returncode == 0)
    shutil.rmtree(os.path.join(p, ".agents", "hooks", "__pycache__"))
    os.makedirs(os.path.join(p, ".codex", "hooks"))
    shutil.copy(os.path.join(KIT, "adapters", "codex", "guard.py"), os.path.join(p, ".codex", "hooks", "guard.py"))
    r = doctor(p)
    expect("doctor: warns about an adapter that was not chosen", "WARN    only the chosen tools" in r.stdout)
    shutil.rmtree(os.path.join(p, ".codex"))
    os.remove(os.path.join(p, "scripts", "agentic-ops", "core", "policy.py"))
    r = doctor(p)
    expect("doctor: a missing file is a FAIL and exit 1", r.returncode == 1 and "FAIL" in r.stdout)

    # ---- conflict handling: existing differing file, nothing written without --force
    p2 = mkproject(BASE, "conflict")
    os.makedirs(os.path.join(p2, ".githooks"))
    with open(os.path.join(p2, ".githooks", "commit-msg"), "w") as f:
        f.write("#!/bin/sh\necho own hook\n")
    before = tree(p2)
    r = inst(p2, *A, "--visibility", "visible", "--apply")
    expect("conflict: exit 4, nothing written", r.returncode == 4 and tree(p2) == before and "Nothing was written" in r.stdout)
    expect("conflict: the plan shows a diff", "differing line" in r.stdout)
    r = inst(p2, *A, "--visibility", "visible", "--apply", "--force")
    expect("conflict: --force overwrites", r.returncode == 0 and "own hook" not in read(os.path.join(p2, ".githooks", "commit-msg")))

    # ---- AGENTS.md marker cases
    p3 = mkproject(BASE, "markers")
    user_text = "# Project rules\n\nKeep my own text.\n\n"
    tail = "\n## Other section\nkeep me\n"
    with open(os.path.join(p3, "AGENTS.md"), "w", newline="") as f:
        f.write(user_text + "## Agent Rules (genai-agentic-ops v1)\n\n### 0. Old\n- old rule\n<!-- END genai-agentic-ops v1 -->" + tail)
    r = inst(p3, *A, "--visibility", "visible", "--apply")
    ag = read(os.path.join(p3, "AGENTS.md"))
    expect("END without BEGIN: replaced from the heading, one block, own text kept",
           r.returncode == 0 and ag.count("BEGIN genai-agentic-ops") == 1 and "old rule" not in ag and ag.startswith(user_text) and ag.endswith(tail))
    p4 = mkproject(BASE, "markers2")
    with open(os.path.join(p4, "AGENTS.md"), "w", newline="") as f:
        f.write(user_text + "<!-- BEGIN genai-agentic-ops v1 -->\n## Agent Rules (genai-agentic-ops v1)\n- old rule\n" + tail)
    before = tree(p4)
    r = inst(p4, *A, "--visibility", "visible", "--apply")
    expect("BEGIN without END: exit 4, nothing written", r.returncode == 4 and tree(p4) == before and "STOP AGENTS.md" in r.stdout)
    p5 = mkproject(BASE, "markers3")
    with open(os.path.join(p5, "AGENTS.md"), "w", newline="") as f:
        f.write(user_text.rstrip("\n") + "\n")
    r = inst(p5, *A, "--visibility", "visible", "--apply")
    ag = read(os.path.join(p5, "AGENTS.md"))
    expect("no block yet: appended once after the user's text", r.returncode == 0 and ag.startswith(user_text) and ag.count("BEGIN genai-agentic-ops") == 1)
    r = inst(p5, *A, "--visibility", "visible", "--apply")
    expect("block already current: unchanged", r.returncode == 0 and read(os.path.join(p5, "AGENTS.md")) == ag)

    # ---- pointers and tool choice
    p6 = mkproject(BASE, "pointers")
    for n, txt in (("GEMINI.md", "# gemini notes\n"),):
        with open(os.path.join(p6, n), "w", newline="") as f:
            f.write(txt)
    r = inst(p6, "--tools", "claude,antigravity", "--modules", "guard,githooks,scripts", "--shell", "sh", "--visibility", "visible", "--apply")
    expect("pointers: CLAUDE.md created with @AGENTS.md", read(os.path.join(p6, "CLAUDE.md")).strip() == "@AGENTS.md")
    expect("pointers: existing GEMINI.md gets one pointer line", "AGENTS.md" in read(os.path.join(p6, "GEMINI.md")) and read(os.path.join(p6, "GEMINI.md")).startswith("# gemini notes"))
    expect("pointers: .cursorrules and .codex are not created", not os.path.exists(os.path.join(p6, ".cursorrules")) and not os.path.exists(os.path.join(p6, ".codex")))

    # ---- merging into an existing hook file, including the v2.2 entry (python -I) being upgraded in place
    p7 = mkproject(BASE, "merge")
    os.makedirs(os.path.join(p7, ".claude"))
    old = {"hooks": {"PreToolUse": [{"matcher": "Read|Bash|PowerShell", "hooks": [{"type": "command", "command": "python -I \"$CLAUDE_PROJECT_DIR/.claude/hooks/guard.py\""}]},
                                    {"matcher": "Edit", "hooks": [{"type": "command", "command": "echo mine"}]}]},
           "permissions": {"allow": ["Bash(ls:*)"]}, "model": "keep-me"}
    with open(os.path.join(p7, ".claude", "settings.json"), "w") as f:
        json.dump(old, f)
    r = inst(p7, "--tools", "claude", "--modules", "guard", "--shell", "sh", "--visibility", "visible", "--apply")
    s = json.load(open(os.path.join(p7, ".claude", "settings.json"), encoding="utf-8"))
    pre = s["hooks"]["PreToolUse"]
    expect("merge: the user's own settings and hook survive", s["model"] == "keep-me" and any(h["matcher"] == "Edit" for h in pre) and "Bash(ls:*)" in s["permissions"]["allow"])
    ours = [h for h in pre if "guard.py" in json.dumps(h)]
    expect("merge: the old guard entry is upgraded in place, not duplicated", len(ours) == 1 and " -B " in ours[0]["hooks"][0]["command"])
    r = inst(p7, "--tools", "claude", "--modules", "guard", "--shell", "sh", "--visibility", "visible", "--apply")
    expect("merge: second run changes nothing", "Nothing to do" in r.stdout)

    # ---- an installed v2.3.0 / v2.3.1 Antigravity entry (quoted one-liner) is replaced in place by the plain command
    p7b = mkproject(BASE, "merge-ag")
    os.makedirs(os.path.join(p7b, ".agents"))
    quoted = 'python -B -I -c "import os,runpy;p=next((q for q in (\'hooks/guard.py\',\'.agents/hooks/guard.py\') if os.path.isfile(q)),None);p and runpy.run_path(p,run_name=\'__main__\')"'
    prev = {"agentic-ops-guard": {"PreToolUse": [{"matcher": "run_command", "hooks": [{"command": quoted, "timeout": 10}]}]},
            "my-own-hook": {"PreToolUse": [{"matcher": "run_command", "hooks": [{"command": "echo mine", "timeout": 5}]}]}}
    with open(os.path.join(p7b, ".agents", "hooks.json"), "w") as f:
        json.dump(prev, f)
    inst(p7b, "--tools", "antigravity", "--modules", "guard", "--shell", "sh", "--visibility", "visible", "--apply")
    hj = json.load(open(os.path.join(p7b, ".agents", "hooks.json"), encoding="utf-8"))
    cmd_new = hj["agentic-ops-guard"]["PreToolUse"][0]["hooks"][0]["command"]
    expect("merge-ag: the quoted v2.3 entry becomes the plain command, in place", cmd_new == "python -B -I hooks/guard.py" and len(hj["agentic-ops-guard"]["PreToolUse"]) == 1)
    expect("merge-ag: the user's own hook survives", hj.get("my-own-hook", {}).get("PreToolUse", [{}])[0].get("hooks", [{}])[0].get("command") == "echo mine")

    # ---- hidden mode with the real sync: main stays clean, overlay pushed, no bytecode
    p8 = mkproject(BASE, "hidden")
    r = inst(p8, *A, "--visibility", "hidden", "--apply")
    expect("hidden install: exit 0", r.returncode == 0)
    expect("hidden install: the project's git status is clean", git(p8, "status", "--porcelain").stdout.strip() == "")
    expect("hidden install: ignore lives in .git/info/exclude, no .gitignore", "BEGIN agentic-ops" in read(os.path.join(p8, ".git", "info", "exclude")) and not os.path.exists(os.path.join(p8, ".gitignore")))
    expect("hidden install: overlay git dir exists", os.path.isdir(os.path.join(p8, ".git", "agentic")))
    expect("hidden install: AGENTS.md has the hidden-mode section", ".git/agentic" in read(os.path.join(p8, "AGENTS.md")))
    expect("hidden install: nothing committed in the project", git(p8, "log", "--oneline").stdout.count("\n") == 1)
    r = doctor(p8)
    expect("doctor: healthy hidden install has no FAIL", r.returncode == 0 and "PASS    hidden mode: no agentic file is tracked" in r.stdout)
    r = inst(p8, *A, "--visibility", "hidden", "--apply")
    expect("hidden install: second run is idempotent", r.returncode == 0 and "Nothing to do" in r.stdout)

    # ---- hidden mode with an agentic file already tracked: exit 3, nothing written
    p9 = mkproject(BASE, "tracked")
    with open(os.path.join(p9, "AGENTS.md"), "w") as f:
        f.write("# my rules\n")
    git(p9, "add", "AGENTS.md")
    git(p9, "commit", "-q", "-m", "docs: add rules")
    before = tree(p9)
    r = inst(p9, *A, "--visibility", "hidden", "--apply")
    expect("tracked agentic file: exit 3 and nothing written", r.returncode == 3 and tree(p9) == before and "already tracked" in r.stderr)

    # ---- argument errors
    p10 = mkproject(BASE, "args")
    expect("unknown tool: exit 2", inst(p10, "--tools", "emacs").returncode == 2)
    expect("hidden without the scripts module: exit 2", inst(p10, "--modules", "guard", "--tools", "antigravity", "--visibility", "hidden").returncode == 2)
    notgit = os.path.join(BASE, "plain")
    os.makedirs(notgit)
    expect("not a git work tree: exit 2", inst(notgit, "--visibility", "visible").returncode == 2)

    # ---- --pin: download from a raw base (a file:// copy of the repo stands in for GitHub)
    raw = os.path.join(BASE, "raw")
    pin = "0123456789abcdef0123456789abcdef01234567"
    shutil.copytree(KIT, os.path.join(raw, pin, "kit"), ignore=shutil.ignore_patterns("__pycache__", "tests"))
    shutil.copy(os.path.join(KIT, "..", "RULES.md"), os.path.join(raw, pin, "RULES.md"))
    p11 = mkproject(BASE, "pin")
    e = dict(ENV, AGENTIC_OPS_RAW_BASE="file:///" + raw.replace("\\", "/").lstrip("/"))
    r = subprocess.run([sys.executable, "-B", INSTALL, "--project", p11, "--pin", pin, "--tools", "antigravity", "--modules", "guard,githooks,scripts",
                        "--shell", "sh", "--visibility", "visible", "--apply"], capture_output=True, text=True, env=e, encoding="utf-8", errors="replace")
    expect("--pin: installs from the raw base and records the pin in the receipt",
           r.returncode == 0 and pin in read(os.path.join(p11, "scripts", "agentic-ops", "INSTALLED.json")))
    r = doctor(p11, "--pin", pin)
    expect("doctor --pin: matching pin passes", "PASS    installed from the expected pin" in r.stdout)
    r = subprocess.run([sys.executable, "-B", INSTALL, "--project", p11, "--pin", "ffffffffffffffffffffffffffffffffffffffff", "--tools", "antigravity"],
                       capture_output=True, text=True, env=e, encoding="utf-8", errors="replace")
    expect("--pin: an unreachable pin is exit 6", r.returncode == 6)

    # ---- the sh and PowerShell entries behave like install.py
    sh = shutil.which("sh")
    if not sh:
        for root in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
            for rel in ("Git/bin/sh.exe", "Git/usr/bin/sh.exe"):
                c = os.path.join(root, *rel.split("/"))
                if root and os.path.isfile(c):
                    sh = sh or c
    ps = shutil.which("powershell") or shutil.which("pwsh")
    p12 = mkproject(BASE, "entries")
    plan_py = inst(p12, *A, "--visibility", "visible").stdout.splitlines()[2:]
    if sh:
        r = subprocess.run([sh, os.path.join(KIT, "install.sh"), "--project", p12, "--kit-dir", KIT] + A + ["--visibility", "visible"], capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")
        expect("install.sh: same plan as install.py", r.returncode == 0 and r.stdout.splitlines()[2:] == plan_py)
    else:
        print("SKIP install.sh (sh not found)")
    if ps and os.name == "nt":
        r = subprocess.run([ps, "-NoProfile", "-File", os.path.join(KIT, "install.ps1"), "-Project", p12, "-KitDir", KIT, "-Tools", "antigravity",
                            "-Modules", "guard,githooks,scripts", "-Shell", "sh", "-Visibility", "visible"], capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")
        expect("install.ps1: same plan as install.py", r.returncode == 0 and r.stdout.splitlines()[2:] == plan_py)
        r = subprocess.run([ps, "-NoProfile", "-File", os.path.join(KIT, "scripts", "doctor.ps1"), "-Project", p12], capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")
        expect("doctor.ps1 runs (not installed project: receipt warning, exit 0 or 1 but no crash)", "[DOCTOR]" in r.stdout)
    else:
        print("SKIP install.ps1 and doctor.ps1 (PowerShell on Windows not found)")
    if sh:
        r = subprocess.run([sh, os.path.join(KIT, "scripts", "doctor.sh"), "--project", p]
                           , capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")
        expect("doctor.sh runs", "[DOCTOR]" in r.stdout)
    # ---- hidden mode through each shell entry must run agentic-sync init (the sync step is not skipped)
    for shell_name in ("ps", "sh"):
        if shell_name == "ps" and not (ps and os.name == "nt"):
            print("SKIP hidden mode with --shell ps (PowerShell on Windows not found)")
            continue
        if shell_name == "sh" and not sh:
            print("SKIP hidden mode with --shell sh (sh not found)")
            continue
        ph = mkproject(BASE, "hidden-" + shell_name)
        r = inst(ph, "--tools", "antigravity", "--modules", "guard,githooks,scripts", "--shell", shell_name, "--visibility", "hidden", "--apply")
        expect(f"hidden --shell {shell_name}: exit 0, agentic-sync init ran", r.returncode == 0)
        expect(f"hidden --shell {shell_name}: no 'was not installed' error", "was not installed" not in r.stdout + r.stderr)
        expect(f"hidden --shell {shell_name}: overlay git dir exists", os.path.isdir(os.path.join(ph, ".git", "agentic")))
        expect(f"hidden --shell {shell_name}: project git status stays clean", git(ph, "status", "--porcelain").stdout.strip() == "")
        expect(f"hidden --shell {shell_name}: prints the Antigravity workspace-root reminder", "Open the repository root itself" in r.stdout)
        r2 = inst(ph, "--tools", "antigravity", "--modules", "guard,githooks,scripts", "--shell", shell_name, "--visibility", "hidden", "--apply")
        expect(f"hidden --shell {shell_name}: running again changes nothing", r2.returncode == 0 and "Nothing to do" in r2.stdout)
finally:
    shutil.rmtree(BASE, ignore_errors=True)

print("ALL TESTS PASSED" if not fail else f"{fail} FAILED")
sys.exit(1 if fail else 0)
