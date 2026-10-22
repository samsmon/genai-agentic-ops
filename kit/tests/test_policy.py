"""Tests for core/policy.py. Run: python -I kit/tests/test_policy.py"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
POLICY = os.path.join(HERE, "..", "core", "policy.py")
sys.path.insert(0, os.path.dirname(POLICY))
import policy  # noqa: E402

fail = 0


def expect(name, got, want):
    global fail
    ok = got == want
    print(("ok   " if ok else f"FAIL (got {got}) ") + name)
    if not ok:
        fail += 1


def dec(**kw):
    return policy.evaluate(**kw)[0]


expect("no input", dec(), "allow")
expect("plain commit", dec(command='git commit -m "feat: x"'), "allow")
expect("Co-Authored-By", dec(command='git commit -m "x\n\nCo-Authored-By: A <a@b.c>"'), "deny")
expect("Signed-off-by", dec(command='git commit -m "x" -m "Signed-off-by: A <a@b.c>"'), "deny")
expect("Generated with", dec(command='git commit -m "x" -m "Generated with a tool"'), "deny")
expect("gh pr create with robot emoji", dec(command='gh pr create --body "body \U0001F916"'), "deny")
expect("clean gh pr create", dec(command="gh pr create --title a --body b"), "allow")
expect("trailer text outside a commit is fine", dec(command='echo "Co-Authored-By: x"'), "allow")
expect("commit --author", dec(command='git commit --author="Bot <c@x>" -m x'), "deny")
expect("git config user.name", dec(command='git config user.name "bot"'), "deny")
expect("git -c user.email", dec(command='git -c user.email=a@b.c commit -m x'), "deny")
expect("env GIT_COMMITTER_EMAIL", dec(command="GIT_COMMITTER_EMAIL=a@b.c git commit -m x"), "deny")
expect("config that is not identity", dec(command="git config core.hooksPath .githooks"), "allow")
expect("--no-verify", dec(command="git commit --no-verify -m x"), "deny")
expect("while sleep", dec(command="while true; do sleep 5; done"), "deny")
expect("until sleep", dec(command="until test -f x; do sleep 1; done"), "deny")
expect("sleep then command", dec(command="sleep 30 && cat log"), "deny")
expect("force push", dec(command="git push --force origin main"), "ask")
expect("force-with-lease", dec(command="git push --force-with-lease"), "ask")
expect("push -f", dec(command="git push origin main -f"), "ask")
expect("reset --hard", dec(command="git reset --hard HEAD~1"), "ask")
expect("clean -fd", dec(command="git clean -fd"), "ask")
expect("branch -D", dec(command="git branch -D old"), "ask")
expect("rm -rf", dec(command="rm -rf build"), "ask")
expect("Remove-Item", dec(command="Remove-Item x -Recurse -Force"), "ask")
expect("plain push", dec(command="git push"), "allow")
expect("git status", dec(command="git status -sb"), "allow")
expect("deny wins over ask", dec(command="git commit --no-verify -m x && git reset --hard"), "deny")

big = 30000
expect("big md read in full", dec(read_path="docs/x.md", read_size=big), "deny")
expect("big md read with limit", dec(read_path="docs/x.md", read_size=big, read_limited=True), "allow")
expect("small md", dec(read_path="docs/x.md", read_size=100), "allow")
expect("big source file", dec(read_path="src/x.py", read_size=big), "allow")
expect("unknown size", dec(read_path="docs/x.md", read_size=None), "allow")
expect("read message names file", "x.md" in policy.evaluate(read_path="C:\\w\\x.md", read_size=big)[1], True)

# switches
policy.BLOCK_AGENT_TRAILERS = False
expect("trailer switch off", dec(command='git commit -m "x" -m "Co-Authored-By: A <a@b.c>"'), "allow")
policy.BLOCK_AGENT_TRAILERS = True
policy.ASK_DESTRUCTIVE = False
expect("destructive switch off", dec(command="git reset --hard"), "allow")
policy.ASK_DESTRUCTIVE = True


def cli(stdin):
    r = subprocess.run([sys.executable, "-I", POLICY], input=stdin, capture_output=True, text=True)
    return r.returncode, r.stdout


code, out = cli(json.dumps({"command": "git reset --hard"}))
expect("cli ask exit 0", code, 0)
expect("cli ask decision", json.loads(out)["decision"], "ask")
expect("cli deny decision", json.loads(cli(json.dumps({"command": "git commit --no-verify"}))[1])["decision"], "deny")
expect("cli broken input allows", json.loads(cli("not json")[1])["decision"], "allow")
with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "big.md")
    open(p, "w").write("x" * big)
    expect("cli read", json.loads(cli(json.dumps({"read_path": p, "read_size": big}))[1])["decision"], "deny")

print("ALL TESTS PASSED" if not fail else f"{fail} FAILED")
sys.exit(1 if fail else 0)
