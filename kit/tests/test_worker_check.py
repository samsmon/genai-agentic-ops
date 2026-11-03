"""worker-check: scope and verify checks on temporary git repositories. Run: python -I kit/tests/test_worker_check.py"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
PY = os.path.join(SCRIPTS, "worker-check.py")
fail = 0

ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull)
ENV.pop("ALLOW_SENSITIVE", None)
OK_CMD = '"%s" -c "import sys; sys.exit(0)"' % sys.executable
BAD_CMD = '"%s" -c "import sys; print(\'boom\'); sys.exit(3)"' % sys.executable


def expect(name, ok):
    global fail
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fail += 1


def run(*cmd, cwd=None, env=None):
    return subprocess.run(list(cmd), cwd=cwd, env=env or ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")


def wc(root, *args, env=None):
    return run(sys.executable, "-B", "-I", PY, *args, "--root", root, env=env)


def write(root, rel, text="x\n"):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def make_repo():
    root = tempfile.mkdtemp(prefix="wc-test-")
    run("git", "init", "-q", cwd=root)
    for rel in ("src/a.js", "src/b.js", "tests/a.test.js", "README.md", "AGENTS.md", "keep/old.txt"):
        write(root, rel, "base\n")
    run("git", "add", "-A", cwd=root)
    run("git", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init", cwd=root)
    return root


roots = []


def fresh():
    r = make_repo()
    roots.append(r)
    return r


def check(root, allow, verify=OK_CMD, *extra, env=None):
    return wc(root, "check", "--allow", allow, "--verify", verify, *extra, env=env)


try:
    # in scope, verify passes
    r = fresh()
    write(r, "src/a.js", "changed\n")
    o = check(r, "src/a.js")
    expect("allowed edit and passing verify: exit 0 and PASS", o.returncode == 0 and "RESULT    PASS" in o.stdout and "OK        src/a.js" in o.stdout)

    # outside the allowed list
    r = fresh()
    write(r, "src/a.js", "changed\n")
    write(r, "README.md", "changed\n")
    o = check(r, "src/a.js")
    expect("file outside the list: exit 1 and OUTSIDE", o.returncode == 1 and "OUTSIDE   README.md" in o.stdout and "SCOPE     FAIL" in o.stdout)

    # verify still runs and reports when scope fails
    expect("verify result is shown even when scope fails", "VERIFY    exit 0" in o.stdout)

    # protected file, even when listed
    r = fresh()
    write(r, "AGENTS.md", "changed\n")
    o = check(r, "AGENTS.md")
    expect("protected file in the allowed list: exit 1 and SENSITIVE", o.returncode == 1 and "SENSITIVE AGENTS.md" in o.stdout)
    o = check(r, "AGENTS.md", env=dict(ENV, ALLOW_SENSITIVE="1"))
    expect("ALLOW_SENSITIVE=1 lifts the protected-file rule", o.returncode == 0 and "RESULT    PASS" in o.stdout)

    r = fresh()
    write(r, "config/.env", "KEY=value\n")
    o = check(r, "config/")
    expect(".env is protected by base name inside an allowed folder", o.returncode == 1 and "SENSITIVE config/.env" in o.stdout)

    # failing verify
    r = fresh()
    write(r, "src/a.js", "changed\n")
    o = check(r, "src/a.js", BAD_CMD)
    expect("failing verify: exit 1, exit code and output shown", o.returncode == 1 and "VERIFY    exit 3" in o.stdout and "boom" in o.stdout and "RESULT    FAIL" in o.stdout)

    # timeout
    r = fresh()
    slow = '"%s" -c "import time; time.sleep(5)"' % sys.executable
    o = check(r, "src/", slow, "--timeout", "1")
    expect("verify timeout: exit 1 and exit 124", o.returncode == 1 and "VERIFY    exit 124" in o.stdout)

    # folder prefix, glob, untracked, deleted
    r = fresh()
    write(r, "src/new.js", "new\n")
    write(r, "tests/b.test.js", "new\n")
    o = check(r, "src/,tests/*.js")
    expect("folder prefix and glob match; untracked files are counted", o.returncode == 0 and "OK        src/new.js" in o.stdout and "OK        tests/b.test.js" in o.stdout)

    r = fresh()
    write(r, "stray.txt", "new\n")
    o = check(r, "src/")
    expect("an untracked file outside the list fails", o.returncode == 1 and "OUTSIDE   stray.txt" in o.stdout)

    r = fresh()
    os.remove(os.path.join(r, "keep", "old.txt"))
    o = check(r, "src/")
    expect("a deleted tracked file outside the list fails", o.returncode == 1 and "OUTSIDE   keep/old.txt" in o.stdout)

    # snapshot: a dirty tree before the worker starts
    r = fresh()
    write(r, "README.md", "my own edit\n")
    snap = os.path.join(r, "..", os.path.basename(r) + ".snap")
    o = wc(r, "snapshot", "--out", snap)
    expect("snapshot: exit 0 and counts the pre-existing change", o.returncode == 0 and "snapshot of 1 changed file(s)" in o.stdout)
    write(r, "src/a.js", "worker edit\n")
    o = check(r, "src/a.js", OK_CMD, "--since", snap)
    expect("since: a pre-existing change is ignored, the worker's edit is checked", o.returncode == 0 and "1 file(s) counted, 1 ignored" in o.stdout)
    write(r, "README.md", "worker touched my file\n")
    o = check(r, "src/a.js", OK_CMD, "--since", snap)
    expect("since: editing a pre-existing dirty file again is counted", o.returncode == 1 and "OUTSIDE   README.md" in o.stdout)
    os.remove(snap)

    # usage errors
    r = fresh()
    expect("empty allowed list: exit 2", wc(r, "check", "--allow", " , ", "--verify", OK_CMD).returncode == 2)
    expect("empty verify command: exit 2", wc(r, "check", "--allow", "src/", "--verify", " ").returncode == 2)
    nogit = tempfile.mkdtemp(prefix="wc-nogit-")
    roots.append(nogit)
    expect("not a git work tree: exit 2", check(nogit, "src/").returncode == 2)
    expect("missing snapshot file: exit 2", check(r, "src/", OK_CMD, "--since", os.path.join(r, "nope.snap")).returncode == 2)

    # shell entries
    r = fresh()
    write(r, "src/a.js", "changed\n")
    sh = shutil.which("sh")
    if sh:
        o = run(sh, os.path.join(SCRIPTS, "worker-check.sh"), "check", "--allow", "src/a.js", "--verify", OK_CMD, "--root", r)
        expect("worker-check.sh: PASS", o.returncode == 0 and "RESULT    PASS" in o.stdout)
    else:
        print("skip worker-check.sh (no sh)")
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps and os.name == "nt":
        o = run(ps, "-NoProfile", "-File", os.path.join(SCRIPTS, "worker-check.ps1"), "check", "-Allow", "src/a.js", "-Verify", OK_CMD, "-Root", r)
        expect("worker-check.ps1: PASS", o.returncode == 0 and "RESULT    PASS" in o.stdout)
        if o.returncode != 0:
            print((o.stdout + o.stderr)[-600:])
    else:
        print("skip worker-check.ps1 (not Windows PowerShell)")
finally:
    for d in roots:
        shutil.rmtree(d, ignore_errors=True)

print("[TESTS] %d failed" % fail)
sys.exit(1 if fail else 0)
