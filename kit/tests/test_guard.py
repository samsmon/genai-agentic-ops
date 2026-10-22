"""Tests for claude/hooks/guard.py. Run: python -I kit/tests/test_guard.py"""
import json
import os
import subprocess
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "claude", "hooks", "guard.py")
fail = 0


def run(tool, **inp):
    r = subprocess.run([sys.executable, "-I", GUARD], input=json.dumps({"tool_name": tool, "tool_input": inp}),
                       capture_output=True, text=True)
    if r.returncode == 2:
        return "deny"
    if '"permissionDecision": "ask"' in r.stdout:
        return "ask"
    return "allow"


def expect(name, got, want):
    global fail
    ok = got == want
    print(("ok   " if ok else f"FAIL (got {got}) ") + name)
    if not ok:
        fail += 1


bash = lambda c: run("Bash", command=c)
expect("plain commit", bash('git commit -m "feat: x"'), "allow")
expect("commit with Co-Authored-By", bash('git commit -m "x\n\nCo-Authored-By: Someone <a@b.c>"'), "deny")
expect("commit with Generated with", bash('git commit -m "x" -m "Generated with a tool"'), "deny")
expect("pr create with robot emoji", bash('gh pr create --body "body \U0001F916"'), "deny")
expect("clean pr create", bash('gh pr create --title a --body b'), "allow")
expect("commit --author", bash('git commit --author="Bot <c@x>" -m x'), "deny")
expect("git config user.name", bash('git config user.name "bot"'), "deny")
expect("env GIT_AUTHOR_NAME", bash('GIT_AUTHOR_NAME=bot git commit -m x'), "deny")
expect("commit --no-verify", bash('git commit --no-verify -m x'), "deny")
expect("sleep loop", bash('while true; do sleep 5; done'), "deny")
expect("force push", bash('git push --force origin main'), "ask")
expect("reset --hard", bash('git reset --hard HEAD~1'), "ask")
expect("rm -rf", bash('rm -rf build'), "ask")
expect("PowerShell Remove-Item", run("PowerShell", command='Remove-Item x -Recurse -Force'), "ask")
expect("git status", bash('git status -sb'), "allow")
expect("plain push", bash('git push'), "allow")
expect("config that is not identity", bash('git config core.hooksPath .githooks'), "allow")

with tempfile.TemporaryDirectory() as d:
    big = os.path.join(d, "big.md")
    open(big, "w").write("x" * 30000)
    small = os.path.join(d, "small.md")
    open(small, "w").write("x" * 100)
    code = os.path.join(d, "big.py")
    open(code, "w").write("x" * 30000)
    expect("Read big text file without limit", run("Read", file_path=big), "deny")
    expect("Read big text file with limit", run("Read", file_path=big, limit=50), "allow")
    expect("Read small file", run("Read", file_path=small), "allow")
    expect("Read big source file is not blocked", run("Read", file_path=code), "allow")
    expect("Read missing file does not crash", run("Read", file_path=os.path.join(d, "nope.md")), "allow")

r = subprocess.run([sys.executable, "-I", GUARD], input="not json", capture_output=True, text=True)
expect("broken input does not block", "deny" if r.returncode == 2 else "allow", "allow")

print("ALL TESTS PASSED" if not fail else f"{fail} FAILED")
sys.exit(1 if fail else 0)
