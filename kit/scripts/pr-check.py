#!/usr/bin/env python3
"""agentic-ops pr-check: check a pull request title and body before it is opened or merged.

  python pr-check.py --title "feat(auth): add OAuth callback" --body-file body.md
  python pr-check.py --pr 12            read title and body of an existing pull request with gh
  python pr-check.py --template         print the body skeleton

Title: a Conventional Commits subject, same types as the commit check, 72 characters at most.
Body:  sections "## Why", "## Changes" and "## Verification", each with content. No agent attribution.
Exit codes: 0 PASS (warnings may print), 1 FAIL, 2 usage error. Rules and reasons: pr-format.md
"""
import argparse
import json
import os
import re
import subprocess
import sys

BASE_TYPES = "feat fix docs style refactor perf test build ci chore revert"
REQUIRED = ("Why", "Changes", "Verification")
TEMPLATE = """## Why
<!-- The problem or the goal, in one or two sentences. -->

## Changes
<!-- What changed, one bullet per area. -->

## Verification
<!-- Commands run and their results. Say what was not verified. -->

## Risks and follow-ups
<!-- Optional. What could break, and what is left for later. -->
"""
ATTRIBUTION = re.compile(r"co-authored-by:|signed-off-by:|generated[- ](?:with|by)\b|\U0001F916", re.I)


def allowed_types():
    words = BASE_TYPES.split()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "commit-types")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                words += line.split("#", 1)[0].split()
    words += os.environ.get("COMMIT_EXTRA_TYPES", "").split()
    try:
        cfg = subprocess.run(["git", "config", "--get", "agentic.commitTypes"], capture_output=True, text=True)
        words += cfg.stdout.split()
    except OSError:
        pass
    return sorted({w for w in words if re.fullmatch(r"[a-z][a-z0-9-]*", w)})


def check_title(title, types):
    fails, warns = [], []
    m = re.fullmatch(r"(?P<type>[a-z][a-z0-9-]*)(\([^()\s]+\))?!?: (?P<desc>\S.*)", title)
    if not m:
        return ["title is not 'type(scope): subject'"], warns
    if m.group("type") not in types:
        fails.append("title type '%s' is not one of: %s" % (m.group("type"), " ".join(types)))
    if m.group("desc")[0].isupper():
        fails.append("title description starts with an uppercase letter")
    if title.endswith("."):
        fails.append("title ends with a period")
    if len(title) > 72:
        fails.append("title has %d characters (72 at most)" % len(title))
    elif len(title) > 50:
        warns.append("title has %d characters; aim for 50 or fewer" % len(title))
    return fails, warns


def sections(body):
    """Map each level-2 heading (lower case) to its text with HTML comments removed."""
    text = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.S)
    out, name = {}, None
    for line in text.split("\n"):
        m = re.match(r"##\s+(.+?)\s*$", line)
        if m:
            name = m.group(1).lower()
            out.setdefault(name, "")
        elif name is not None:
            out[name] += line + "\n"
    return out


def check_body(body):
    fails = []
    secs = sections(body)
    for want in REQUIRED:
        if want.lower() not in secs:
            fails.append("body has no '## %s' section" % want)
        elif not secs[want.lower()].strip():
            fails.append("'## %s' section is empty" % want)
    hit = ATTRIBUTION.search(body)
    if hit:
        fails.append("body carries agent attribution or a trailer: '%s'" % hit.group(0).strip())
    return fails


def read_pr(number):
    try:
        o = subprocess.run(["gh", "pr", "view", str(number), "--json", "title,body"], capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        print("pr-check: cannot run gh: %s" % exc, file=sys.stderr)
        sys.exit(2)
    if o.returncode != 0:
        print("pr-check: gh pr view failed: " + (o.stderr or "").strip(), file=sys.stderr)
        sys.exit(2)
    data = json.loads(o.stdout)
    return data.get("title") or "", data.get("body") or ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a pull request title and body.")
    ap.add_argument("--title")
    ap.add_argument("--body-file")
    ap.add_argument("--pr")
    ap.add_argument("--template", action="store_true")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.template:
        sys.stdout.write(TEMPLATE)
        return 0
    if a.pr:
        title, body = read_pr(a.pr)
    elif a.title is not None and a.body_file:
        if not os.path.isfile(a.body_file):
            print("pr-check: body file not found: " + a.body_file, file=sys.stderr)
            return 2
        with open(a.body_file, encoding="utf-8-sig") as f:
            title, body = a.title, f.read()
    else:
        ap.print_usage(sys.stderr)
        return 2
    fails, warns = check_title(title.strip(), allowed_types())
    fails += check_body(body)
    for w in warns:
        print("WARN   " + w)
    for f in fails:
        print("FAIL   " + f)
    print("[PR] " + ("FAIL (%d)" % len(fails) if fails else "PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
