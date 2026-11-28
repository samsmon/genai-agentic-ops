"""Tests for receipt-based upgrade and --uninstall in kit/install.py.

Run: python -I kit/tests/test_uninstall.py     (needs git)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.abspath(os.path.join(HERE, ".."))
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
A = ["--tools", "claude", "--modules", "guard,githooks,scripts", "--shell", "sh", "--visibility", "visible", "--python", "python"]
RECEIPT = "scripts/agentic-ops/INSTALLED.json"
TARGET = "scripts/agentic-ops/core/policy.py"
PRE = "scripts/agentic-ops/commit-format.md"
fail = 0


def expect(name, ok, r=None):
    global fail
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fail += 1
        if r is not None:
            print(r.stdout + r.stderr)


def path(root, rel):
    return os.path.join(root, *rel.split("/"))


def read(root, rel):
    with open(path(root, rel), "rb") as f:
        return f.read()


def write(root, rel, data):
    os.makedirs(os.path.dirname(path(root, rel)), exist_ok=True)
    with open(path(root, rel), "wb") as f:
        f.write(data)


def exists(root, rel):
    return os.path.exists(path(root, rel))


def mkproject(name):
    p = os.path.join(BASE, name)
    os.makedirs(p)
    subprocess.run(["git", "-C", p, "init", "-q", "-b", "main"], env=ENV, check=True)
    return p


def mkkit(name):
    """A private copy of the kit and RULES.md that a test can change."""
    root = os.path.join(BASE, name)
    shutil.copytree(KIT, os.path.join(root, "kit"), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(os.path.join(KIT, "..", "RULES.md"), root)
    return os.path.join(root, "kit")


def inst(project, *args, kit=KIT):
    cmd = [sys.executable, "-B", os.path.join(KIT, "install.py"), "--project", project, "--kit-dir", kit] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV, encoding="utf-8", errors="replace")


BASE = tempfile.mkdtemp(prefix="agentic-uninstall-")
try:
    newer = mkkit("newer")
    write(newer, "core/policy.py", read(KIT, "core/policy.py") + b"\n# newer kit\n")

    # ---- upgrade: an untouched file follows the kit
    p = mkproject("up")
    inst(p, *A, "--apply")
    r = inst(p, *A, "--apply", kit=newer)
    expect("upgrade: untouched file is updated without --force", r.returncode == 0 and b"# newer kit" in read(p, TARGET), r)
    r = inst(p, *A, "--apply", kit=newer)
    expect("upgrade: second run changes nothing", "Nothing to do" in r.stdout, r)

    # ---- upgrade: an untouched file checked out with CRLF still counts as untouched
    p = mkproject("crlf")
    inst(p, *A, "--apply")
    write(p, TARGET, read(p, TARGET).replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    r = inst(p, *A, "--apply", kit=newer)
    expect("upgrade: CRLF checkout is still untouched", r.returncode == 0 and b"# newer kit" in read(p, TARGET), r)

    # ---- upgrade: a file the user changed stays a conflict
    p = mkproject("mine")
    inst(p, *A, "--apply")
    write(p, TARGET, b"# mine\n")
    r = inst(p, *A, "--apply", kit=newer)
    expect("upgrade: user change is a conflict, nothing written", r.returncode == 4 and read(p, TARGET) == b"# mine\n", r)

    # ---- upgrade: broken receipt falls back to conflict
    p = mkproject("broken")
    inst(p, *A, "--apply")
    write(p, RECEIPT, b"not json")
    r = inst(p, *A, "--apply", kit=newer)
    expect("upgrade: broken receipt means conflict", r.returncode == 4, r)

    # ---- upgrade: a deleted file is restored
    p = mkproject("deleted")
    inst(p, *A, "--apply")
    os.remove(path(p, TARGET))
    r = inst(p, *A, "--apply")
    expect("upgrade: deleted file is restored", r.returncode == 0 and exists(p, TARGET), r)

    # ---- uninstall: dry run, then a clean removal
    p = mkproject("clean")
    inst(p, *A, "--apply")
    r = inst(p, "--uninstall")
    expect("uninstall: dry run writes nothing", r.returncode == 0 and exists(p, TARGET) and "nothing was removed" in r.stdout, r)
    os.makedirs(path(p, "scripts/agentic-ops/core/__pycache__"))
    r = inst(p, "--uninstall", "--apply")
    expect("uninstall: kit files and empty folders are gone",
           r.returncode == 0 and not exists(p, "scripts") and not exists(p, ".githooks") and not exists(p, ".claude"), r)
    expect("uninstall: AGENTS.md that held only the block is removed", not exists(p, "AGENTS.md"), r)
    expect("uninstall: ops log is kept", exists(p, "docs/CURRENT_OPS.md"), r)
    hp = subprocess.run(["git", "-C", p, "config", "--get", "core.hooksPath"], capture_output=True, text=True, env=ENV)
    expect("uninstall: core.hooksPath is unset", hp.stdout.strip() == "", r)

    # ---- uninstall: user content survives
    p = mkproject("keep")
    write(p, "AGENTS.md", b"# My rules\n")
    mine = {"model": "x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "my/guard.py"}]}]}}
    write(p, ".claude/settings.json", json.dumps(mine).encode())
    inst(p, *A, "--apply")
    write(p, TARGET, b"# mine\n")
    r = inst(p, "--uninstall", "--apply")
    left = json.loads(read(p, ".claude/settings.json"))
    text = json.dumps(left)
    expect("uninstall: modified file is kept", r.returncode == 0 and read(p, TARGET) == b"# mine\n", r)
    expect("uninstall: own text in AGENTS.md survives", read(p, "AGENTS.md").strip() == b"# My rules", r)
    expect("uninstall: own settings and hook survive, kit hooks go",
           left.get("model") == "x" and "my/guard.py" in text and "session_start.py" not in text and ".claude/hooks/" not in text, r)
    expect("uninstall: receipt still lists what was kept", list(json.loads(read(p, RECEIPT))["files"]) == [TARGET], r)
    r = inst(p, "--uninstall", "--apply", "--force")
    expect("uninstall --force: modified file is removed", r.returncode == 0 and not exists(p, TARGET) and not exists(p, RECEIPT), r)

    # ---- uninstall: a file that was there before the install is never removed
    p = mkproject("pre")
    write(p, PRE, read(KIT, "commit-format.md"))
    inst(p, *A, "--apply")
    inst(p, *A, "--apply")
    r = inst(p, "--uninstall", "--apply", "--force")
    expect("uninstall: pre-existing file is kept", r.returncode == 0 and exists(p, PRE), r)

    # ---- uninstall: refusals
    p = mkproject("none")
    r = inst(p, "--uninstall", "--apply")
    expect("uninstall: no receipt is exit 2", r.returncode == 2 and "receipt" in r.stderr, r)
    write(BASE, "outside.txt", b"x")
    write(p, RECEIPT, json.dumps({"files": {"../outside.txt": "0"}}).encode())
    r = inst(p, "--uninstall", "--apply", "--force")
    expect("uninstall: a path outside the project is refused", r.returncode == 2 and exists(BASE, "outside.txt"), r)

    # ---- --pin: install.py downloaded on its own fetches its helper modules (RULES.md Part A step 4)
    scratch = os.path.join(BASE, "scratch")
    os.makedirs(scratch)
    shutil.copy(os.path.join(KIT, "install.py"), scratch)
    repo = Path(BASE, "raw")
    mkkit("raw/abc123")
    p = mkproject("pinned")
    env = dict(ENV, AGENTIC_OPS_RAW_BASE=repo.as_uri())

    def alone(*args):
        cmd = [sys.executable, "-B", os.path.join(scratch, "install.py"), "--project", p] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")

    r = alone("--pin", "abc123", *A, "--apply")
    expect("--pin: lone install.py installs", r.returncode == 0 and exists(p, TARGET), r)
    expect("--pin: nothing is written next to the lone script", os.listdir(scratch) == ["install.py"])
    r = alone("--pin=abc123", "--uninstall")
    expect("--pin=sha form works too", r.returncode == 0, r)
    r = alone("--pin", "nosuchsha", *A)
    expect("--pin: unreachable source is exit 6", r.returncode == 6, r)
finally:
    shutil.rmtree(BASE, ignore_errors=True)

print(f"{fail} failure(s)")
sys.exit(1 if fail else 0)
