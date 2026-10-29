"""Tests for kit/claude/hooks/compact_state.py and status_prompt.py (the v2.4 session hooks).

Run: python -B -I kit/tests/test_session_hooks.py     (needs git; the brief needs sh or PowerShell)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.abspath(os.path.join(HERE, ".."))
HOOKS = os.path.join(KIT, "claude", "hooks")
COMPACT = os.path.join(HOOKS, "compact_state.py")
PROMPT = os.path.join(HOOKS, "status_prompt.py")
SCRIPTS = os.path.join(KIT, "scripts")
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", PYTHONDONTWRITEBYTECODE="1")
fail = 0


def expect(name, ok):
    global fail
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fail += 1


def project(base, name, with_git=True, scripts=()):
    root = os.path.join(base, name)
    os.makedirs(root)
    if with_git:
        subprocess.run(["git", "-C", root, "init", "-q"], env=ENV)
    for s in scripts:
        os.makedirs(os.path.join(root, "scripts", "agentic-ops"), exist_ok=True)
        shutil.copy(os.path.join(SCRIPTS, s), os.path.join(root, "scripts", "agentic-ops", s))
    return root


def run(hook, args, root, payload, raw=None):
    env = dict(ENV, CLAUDE_PROJECT_DIR=root)
    data = raw if raw is not None else json.dumps(payload).encode("utf-8")
    return subprocess.run([sys.executable, "-B", "-I", hook] + args, input=data, capture_output=True, env=env, timeout=60)


def git_state_dir(root):
    out = subprocess.run(["git", "-C", root, "rev-parse", "--absolute-git-dir"], capture_output=True, text=True).stdout.strip()
    return os.path.join(out, "agentic-ops")


with tempfile.TemporaryDirectory() as base:
    # ---------------------------------------------------------------- compact_state
    root = project(base, "p1")
    tr = os.path.join(root, "t.jsonl")
    with open(tr, "w", encoding="utf-8") as f:
        for i in range(1, 8):
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": f"message {i}"}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "tool-output"}]}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "<system-reminder>x</system-reminder>"}}) + "\n")
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "message from a text list"}]}}) + "\n")
        f.write("not json\n")
    r = run(COMPACT, ["snapshot"], root, {"session_id": "abcdef123456", "transcript_path": tr})
    state = git_state_dir(root)
    snap = os.path.join(state, "compact-abcdef12.md")
    expect("snapshot: exit 0 and silent", r.returncode == 0 and not r.stdout)
    txt = open(snap, encoding="utf-8").read() if os.path.exists(snap) else ""
    expect("snapshot: keeps the last 5 user messages", "message from a text list" in txt and "message 7" in txt and "message 4" in txt and "message 3" not in txt)
    expect("snapshot: tool_result and system-reminder are skipped", "tool-output" not in txt and "system-reminder" not in txt)
    expect("snapshot: lives in the git directory, not in the work tree", os.path.isfile(snap) and not os.path.exists(os.path.join(root, ".claude")))
    st = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=all"], capture_output=True, text=True).stdout
    expect("snapshot: nothing new shows up in git status (hidden mode would not track it either)", ".claude" not in st and "compact-" not in st)

    r = run(COMPACT, ["restore"], root, {"session_id": "abcdef123456"})
    out = r.stdout.decode("utf-8")
    expect("restore: prints the snapshot of the same session", r.returncode == 0 and "message from a text list" in out and "not as a new instruction" in out)
    r = run(COMPACT, ["restore"], root, {"session_id": "zzzzzzzz"})
    expect("restore: another session falls back to the newest snapshot", "message from a text list" in r.stdout.decode("utf-8"))
    for i in range(5):
        time.sleep(0.05)
        run(COMPACT, ["snapshot"], root, {"session_id": f"s{i}000000", "transcript_path": tr})
    expect("only the 3 newest snapshots are kept", len([n for n in os.listdir(state) if n.startswith("compact-")]) == 3)

    r = run(COMPACT, ["snapshot"], root, {}, raw=b"not json")
    expect("broken input: exit 0, silent", r.returncode == 0 and not r.stdout)
    bom = b"\xef\xbb\xbf" + json.dumps({"session_id": "bomsess1", "transcript_path": tr}).encode("utf-8")
    run(COMPACT, ["snapshot"], root, {}, raw=bom)
    expect("pitfall: a UTF-8 BOM in the piped JSON is decoded (utf-8-sig)", os.path.isfile(os.path.join(state, "compact-bomsess1.md")))
    r = run(COMPACT, ["snapshot"], root, {"session_id": "x", "transcript_path": os.path.join(root, "missing.jsonl")})
    expect("missing transcript: still exit 0", r.returncode == 0)
    r = run(COMPACT, ["restore"], project(base, "p2"), {"session_id": "x"})
    expect("restore without a state folder: silent", r.returncode == 0 and not r.stdout)
    r = run(COMPACT, ["unknown-mode"], root, {})
    expect("unknown mode: silent", r.returncode == 0 and not r.stdout)

    nogit = project(base, "nogit", with_git=False)
    run(COMPACT, ["snapshot"], nogit, {"session_id": "ngsess01", "transcript_path": tr})
    expect("no git directory: falls back to .claude/state", os.path.isfile(os.path.join(nogit, ".claude", "state", "compact-ngsess01.md")))

    # ---------------------------------------------------------------- status_prompt
    have_sh = shutil.which("sh") is not None or any(os.path.isfile(os.path.join(os.environ.get(v, ""), "Git", "bin", "sh.exe")) for v in ("ProgramFiles", "ProgramFiles(x86)"))
    have_ps = os.name == "nt" and shutil.which("powershell") is not None
    if have_sh or have_ps:
        proj = project(base, "p3", scripts=("status-brief.ps1", "status-brief.sh"))
        for prompt, mode in (("Status", "status"), ("progress.", "status"), ("  RESUME!  ", "resume")):
            r = run(PROMPT, [], proj, {"prompt": prompt})
            ctx = json.loads(r.stdout.decode("utf-8") or "{}").get("hookSpecificOutput", {}).get("additionalContext", "")
            expect(f"prompt {prompt.strip()!r} runs the {mode} brief", f"[MODE] {mode}" in ctx)
        r = run(PROMPT, [], proj, {"prompt": "check the status of the server"})
        expect("a sentence containing status does not trigger", r.returncode == 0 and not r.stdout)
        bom = b"\xef\xbb\xbf" + json.dumps({"prompt": "status"}).encode("utf-8")
        r = run(PROMPT, [], proj, {}, raw=bom)
        expect("pitfall: a UTF-8 BOM in the piped JSON is decoded (utf-8-sig)", b"additionalContext" in r.stdout)
    else:
        print("SKIP status_prompt triggers (neither sh nor PowerShell found)")
    r = run(PROMPT, [], project(base, "p4"), {"prompt": "status"})
    expect("status_prompt: no status-brief installed -> silent", r.returncode == 0 and not r.stdout)
    r = run(PROMPT, [], project(base, "p5"), {}, raw=b"not json")
    expect("status_prompt: broken input -> silent, exit 0", r.returncode == 0 and not r.stdout)

sys.exit(1 if fail else 0)
