"""UserPromptSubmit: a one-word message "status" / "progress" or "resume" runs scripts/agentic-ops/status-brief.*.

It matches only when the WHOLE message is that word (case and trailing punctuation are ignored), so a normal sentence
that contains "status" is not touched. The script output is injected as additional context.
Fails silently: a hook must never break the session.
"""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
MODES = {"status": "status", "progress": "status", "resume": "resume"}


def find_sh():
    p = shutil.which("sh")
    if p:
        return p
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        for rel in ("Git/bin/sh.exe", "Git/usr/bin/sh.exe"):
            c = os.path.join(base or "", *rel.split("/"))
            if base and os.path.isfile(c):
                return c
    return None


def command(mode):
    """The installed status-brief for this machine: PowerShell first on Windows, sh first elsewhere."""
    folder = os.path.join(ROOT, "scripts", "agentic-ops")
    ps1, sh = os.path.join(folder, "status-brief.ps1"), os.path.join(folder, "status-brief.sh")
    ps = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Mode", mode, "-Root", ROOT]
    for kind in (("ps", "sh") if os.name == "nt" else ("sh", "ps")):
        if kind == "ps" and os.name == "nt" and os.path.isfile(ps1):
            return ps
        if kind == "sh" and os.path.isfile(sh) and find_sh():
            return [find_sh(), sh, mode, ROOT]
    return None


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))  # a PowerShell pipe adds a UTF-8 BOM
        word = re.sub(r"[\s.!?]+$", "", str(data.get("prompt", "")).strip()).lower()
    except Exception:
        return
    mode = MODES.get(word)
    cmd = command(mode) if mode else None
    if not cmd:
        return
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
    except Exception:
        return
    if r.returncode != 0 or not r.stdout.strip():
        return
    ctx = f"The user message '{word}' triggered an automatic {mode} brief (scripts/agentic-ops/status-brief):\n{r.stdout.strip()}"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}}))


if __name__ == "__main__":
    main()
