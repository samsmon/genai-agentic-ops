#!/usr/bin/env python3
"""agentic-ops worker-check: the chief's two checks after a worker reports DONE, as one command.

  python worker-check.py snapshot --out FILE [--root DIR]
  python worker-check.py check --allow PATTERNS --verify COMMAND [--since FILE] [--root DIR] [--timeout SEC] [--stat]

snapshot  records the files that are already changed (tracked edits and untracked files) with a hash of each, so a
          dirty working tree does not fail the scope check later. Run it before the worker starts.
check     (1) scope: every file changed since the snapshot must match --allow and must not be a protected file;
          (2) verify: runs COMMAND once and shows the tail of its output. Prints PASS or FAIL.

--allow is a comma list. Each item is an exact path, a folder prefix ending in "/", or a glob such as "src/*.js".
Protected files (secrets, keys, hook and agent folders, rules files, CI workflows, the ops log) fail the check even when
they are in --allow. ALLOW_SENSITIVE=1 lifts that, on the user's say-so only.
Exit codes: 0 PASS, 1 FAIL, 2 usage error or not a git work tree with a commit.
The chief still decides: this only replaces typing the same two checks by hand. It does not sandbox the worker.
"""
import argparse
import fnmatch
import hashlib
import os
import subprocess
import sys
import time

PROTECTED = (
    ".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", ".mcp.json",
    "AGENTS.md", "CLAUDE.md", "GEMINI.md",
    ".git/*", ".github/workflows/*", ".claude/*", ".codex/*", ".cursor/*", ".agents/*", ".opencode/*",
    "scripts/agentic-ops/*", "docs/CURRENT_OPS.md", "docs/CURRENT_OPS-archive.md",
)


def fail_usage(msg):
    sys.stderr.write("worker-check: " + msg + "\n")
    sys.exit(2)


def git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), capture_output=True)


def changed_paths(root):
    """Paths changed against HEAD (renames reported as delete + add) plus untracked files, as forward-slash paths."""
    if git(root, "rev-parse", "--verify", "-q", "HEAD").returncode != 0:
        fail_usage("%s is not a git work tree with at least one commit" % root)
    a = git(root, "diff", "--name-only", "--no-renames", "-z", "HEAD")
    b = git(root, "ls-files", "--others", "--exclude-standard", "-z")
    out = set()
    for blob in (a.stdout, b.stdout):
        for p in blob.decode("utf-8", "replace").split("\0"):
            if p:
                out.add(p.replace("\\", "/"))
    return sorted(out)


def digest(root, rel):
    full = os.path.join(root, rel)
    if os.path.islink(full):
        return "link:" + os.readlink(full)
    if not os.path.isfile(full):
        return "deleted"
    h = hashlib.sha256()
    with open(full, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_snapshot(path):
    snap = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if "\t" in line:
                    d, p = line.split("\t", 1)
                    snap[p] = d
    except OSError as e:
        fail_usage("cannot read snapshot %s: %s" % (path, e))
    return snap


def allowed(rel, patterns):
    for pat in patterns:
        if pat.endswith("/"):
            if rel.startswith(pat):
                return True
        elif rel == pat or fnmatch.fnmatchcase(rel, pat):
            return True
    return False


def protected(rel):
    base = rel.rsplit("/", 1)[-1]
    for pat in PROTECTED:
        if "/" in pat:
            if fnmatch.fnmatchcase(rel, pat):
                return True
        elif fnmatch.fnmatchcase(base, pat):
            return True
    return False


def cmd_snapshot(a):
    root = os.path.abspath(a.root)
    rows = ["%s\t%s" % (digest(root, p), p) for p in changed_paths(root)]
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(rows) + ("\n" if rows else ""))
    print("worker-check: snapshot of %d changed file(s) written to %s" % (len(rows), a.out))
    return 0


def cmd_check(a):
    root = os.path.abspath(a.root)
    patterns = [p.strip().replace("\\", "/") for p in a.allow.split(",") if p.strip()]
    if not patterns:
        fail_usage("--allow needs at least one path (the spec's Allowed Files)")
    if not a.verify.strip():
        fail_usage("--verify needs the spec's one verify command")
    snap = load_snapshot(a.since) if a.since else {}
    lift = os.environ.get("ALLOW_SENSITIVE") == "1"

    print("worker-check: root=%s" % root)
    if a.stat:
        st = git(root, "diff", "--stat", "HEAD")
        print(st.stdout.decode("utf-8", "replace").rstrip() or "(no tracked changes)")

    ignored, bad, rows = 0, 0, []
    files = changed_paths(root)
    for rel in files:
        if rel in snap and snap[rel] == digest(root, rel):
            ignored += 1
            continue
        if protected(rel) and not lift:
            rows.append(("SENSITIVE", rel, "protected file"))
            bad += 1
        elif not allowed(rel, patterns):
            rows.append(("OUTSIDE", rel, "not in the allowed list"))
            bad += 1
        else:
            rows.append(("OK", rel, "allowed"))
    print("CHANGED   %d file(s) counted, %d ignored from the snapshot" % (len(rows), ignored))
    for tag, rel, why in rows:
        print("%-9s %s  (%s)" % (tag, rel, why))
    print("SCOPE     " + ("FAIL" if bad else "ok"))

    t0 = time.time()
    try:
        r = subprocess.run(a.verify, shell=True, cwd=root, capture_output=True, timeout=a.timeout)
        rc, out = r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        rc, out = 124, ((e.stdout or b"") + (e.stderr or b"")).decode("utf-8", "replace") + "\n(timed out after %ss)" % a.timeout
    print("VERIFY    exit %d (%.1fs)" % (rc, time.time() - t0))
    tail = [ln for ln in out.replace("\r\n", "\n").split("\n") if ln.strip()][-a.tail:]
    for ln in tail:
        print("          " + ln)

    ok = bad == 0 and rc == 0
    print("RESULT    " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(prog="worker-check", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("snapshot")
    s.add_argument("--out", required=True)
    s.add_argument("--root", default=".")
    c = sub.add_parser("check")
    # WORKER_CHECK_ALLOW / WORKER_CHECK_VERIFY let the PowerShell entry pass text with quotes without argument escaping
    c.add_argument("--allow", default=os.environ.get("WORKER_CHECK_ALLOW", ""))
    c.add_argument("--verify", default=os.environ.get("WORKER_CHECK_VERIFY", ""))
    c.add_argument("--since", default="")
    c.add_argument("--root", default=".")
    c.add_argument("--timeout", type=int, default=600)
    c.add_argument("--tail", type=int, default=20)
    c.add_argument("--stat", action="store_true")
    a = ap.parse_args()
    if a.cmd == "snapshot":
        return cmd_snapshot(a)
    if a.cmd == "check":
        return cmd_check(a)
    ap.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
