"""Tests for scripts/pr-check.py: title and body rules for pull requests."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "scripts", "pr-check.py")
ENV = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
ENV.pop("COMMIT_EXTRA_TYPES", None)
fail = 0
GOOD = "## Why\nThe check failed on Windows.\n\n## Changes\n- Use relative names.\n\n## Verification\n- Suite passes.\n"


def expect(name, ok, out=None):
    global fail
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fail += 1
        if out is not None:
            print((out.stdout + out.stderr)[-500:])


def run(*args, env=None):
    return subprocess.run([sys.executable, "-B", "-I", PY] + list(args), cwd=tmp, env=env or ENV, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def check(title, body, env=None):
    path = os.path.join(tmp, "body.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return run("--title", title, "--body-file", path, env=env)


tmp = tempfile.mkdtemp(prefix="prcheck-")
try:
    o = check("fix(handoff): take relative paths from the provider", GOOD)
    expect("good title and body -> PASS", o.returncode == 0 and "[PR] PASS" in o.stdout, o)

    o = check("fix(handoff): take relative paths from the provider and print the script output", GOOD)
    expect("title over 72 characters -> FAIL", o.returncode == 1 and "72 at most" in o.stdout, o)

    o = check("fix: make telemetry and benchmark claims evidence-based", GOOD)
    expect("title over 50 characters -> WARN, still PASS", o.returncode == 0 and "WARN" in o.stdout, o)

    for bad in ("Update stuff", "[agent] feat: add login", "feat:add login", "Feat: add login"):
        o = check(bad, GOOD)
        expect("title %r -> FAIL" % bad, o.returncode == 1 and "type(scope): subject" in o.stdout, o)

    o = check("feat: Add login.", GOOD)
    expect("uppercase description and final period -> FAIL twice", o.returncode == 1 and "uppercase" in o.stdout and "period" in o.stdout, o)

    o = check("ops: rotate the log", GOOD)
    expect("unknown type -> FAIL", o.returncode == 1 and "is not one of" in o.stdout, o)
    o = check("ops: rotate the log", GOOD, env=dict(ENV, COMMIT_EXTRA_TYPES="ops"))
    expect("extra type from COMMIT_EXTRA_TYPES -> PASS", o.returncode == 0, o)

    o = check("fix: correct the parser", "## Why\nx\n\n## Changes\n- y\n")
    expect("missing Verification section -> FAIL", o.returncode == 1 and "no '## Verification' section" in o.stdout, o)

    o = check("fix: correct the parser", GOOD.replace("- Suite passes.", "<!-- commands run -->"))
    expect("section holding only the template comment -> FAIL", o.returncode == 1 and "'## Verification' section is empty" in o.stdout, o)

    o = check("fix: correct the parser", "LGTM")
    expect("body without sections -> three FAIL lines", o.returncode == 1 and "[PR] FAIL (3)" in o.stdout, o)

    marks = (("trailer", "Co-Authored-By: Some Tool <tool@example.invalid>"), ("generated-with line", "Generated with SomeTool"),
             ("robot emoji", "\U0001F916 done"))
    for label, mark in marks:
        o = check("fix: correct the parser", GOOD + "\n" + mark + "\n")
        expect("attribution (%s) -> FAIL" % label, o.returncode == 1 and "attribution" in o.stdout, o)

    o = check("fix: correct the parser", GOOD.replace("\n", "\r\n") + "\r\n## Risks and follow-ups\r\n")
    expect("CRLF body with an empty optional section -> PASS", o.returncode == 0, o)

    o = run("--template")
    body = o.stdout
    expect("--template prints the three required headings", o.returncode == 0 and all("## " + h in body for h in ("Why", "Changes", "Verification")), o)
    o = check("fix: correct the parser", body)
    expect("unfilled template -> FAIL", o.returncode == 1 and "[PR] FAIL (3)" in o.stdout, o)

    o = run("--title", "fix: x")
    expect("title without a body file -> usage error 2", o.returncode == 2, o)
    o = run("--title", "fix: x", "--body-file", os.path.join(tmp, "missing.md"))
    expect("missing body file -> usage error 2", o.returncode == 2, o)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("[TESTS] %d failed" % fail)
sys.exit(1 if fail else 0)
