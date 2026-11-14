"""SessionStart hook for Claude Code: short sync summary, no model needed.

Prints the [GIT], [OPS] and [HOOK] sections of scripts/agentic-ops/start-brief.* and, when the optional
handoff module is used, how many items await review. Also activates core.hooksPath=.githooks when that
directory exists (local config, idempotent).
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
SCRIPTS = os.path.join(ROOT, "scripts", "agentic-ops")
STATE_FILE = os.environ.get("STATE_FILE", "NOW.md")                       # handoff module only
SHOW = ("GIT", "OPS", "RULES", "HOOK", "DEVICE")


def resolve_review_heading(text):
    cands = []
    if os.environ.get("REVIEW_HEADING"):
        cands.append(os.environ["REVIEW_HEADING"])
    settings_path = os.path.join(ROOT, ".claude", "settings.json")
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, encoding="utf-8") as f:
                cfg = json.load(f)
            h = (cfg.get("env") or {}).get("REVIEW_HEADING")
            if h and h not in cands:
                cands.append(h)
        except Exception:
            pass
    for h in ("## Awaiting review", "## Belum di-review"):
        if h not in cands:
            cands.append(h)
    for h in cands:
        if h in text:
            return h
    return cands[0]


def git(*args):
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True, text=True, timeout=30)


def run_brief():
    ps1 = os.path.join(SCRIPTS, "start-brief.ps1")
    sh = os.path.join(SCRIPTS, "start-brief.sh")
    if os.name == "nt" and os.path.exists(ps1):
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Root", ROOT]
    elif os.path.exists(sh):
        cmd = ["sh", sh, ROOT]
    elif os.path.exists(ps1):
        cmd = ["pwsh", "-NoProfile", "-File", ps1, "-Root", ROOT]
    else:
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=60).stdout
    except Exception as e:  # noqa: BLE001
        return f"[GIT]\nSTOP:start-brief could not run ({e})"


def main():
    notes = []
    try:
        if git("config", "core.hooksPath").stdout.strip() != ".githooks" and os.path.isdir(os.path.join(ROOT, ".githooks")):
            git("config", "core.hooksPath", ".githooks")
            notes.append("core.hooksPath set to .githooks")
    except Exception:
        pass

    keep, show = [], True
    for line in run_brief().splitlines():
        m = re.match(r"^\[(\w+)\]$", line)
        if m:
            show = m.group(1) in SHOW
        if show:
            keep.append(line.rstrip())

    unrev = 0
    heading = os.environ.get("REVIEW_HEADING", "## Awaiting review")
    try:
        text = open(os.path.join(ROOT, STATE_FILE), encoding="utf-8").read()
        heading = resolve_review_heading(text)
        sec = text[text.index(heading):]
        nxt = sec.find("\n## ", 5)
        sec = sec if nxt < 0 else sec[:nxt]
        unrev = sum(1 for l in sec.splitlines() if l.startswith("- "))
    except Exception:
        pass

    print("Session start summary (automatic; read the state file only if the topic needs it):")
    print("\n".join(keep))
    if notes:
        print("[AUTO] " + "; ".join(notes))
    if unrev:
        print(f"[REVIEW] {unrev} item(s) under '{heading}' in {STATE_FILE} (offer a review if relevant)")


if __name__ == "__main__":
    main()
