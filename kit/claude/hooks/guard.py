"""PreToolUse guard for Claude Code: enforces the written rules mechanically.

deny  -> exit 2 + stderr (the model sees the reason and must change approach)
ask   -> JSON permissionDecision=ask (the user decides)

Policies are plain constants below; edit them to fit the project. Runs only inside Claude Code,
so other agents rely on the git hooks and the written rules.
"""
import json
import os
import re
import sys

RULES_DOC = "AGENTS.md"      # named in block messages
BIG_BYTES = 24_000           # ~6k tokens; reading larger text files in full is wasteful
BIG_EXT = (".md", ".log", ".txt", ".json", ".yml", ".yaml", ".sql", ".csv")
READ_HINT = "Search first (grep) or read it in parts with offset/limit."

BLOCK_AGENT_TRAILERS = True   # commit/PR text must not carry agent attribution lines
BLOCK_IDENTITY_CHANGE = True  # agents must not set git author/committer identity
BLOCK_NO_VERIFY = True
BLOCK_SLEEP_LOOP = True
ASK_DESTRUCTIVE = True

TRAILER = re.compile(r"co-authored-by\s*:|signed-off-by\s*:|generated-by\s*:|generated with|\U0001F916", re.I)
IDENTITY = re.compile(
    r"--author\b|\bGIT_(AUTHOR|COMMITTER)_(NAME|EMAIL)\b|-c\s+user\.(name|email)\b"
    r"|\bgit\s+config\b[^\n]*\buser\.(name|email)\b",
    re.I,
)


def deny(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def ask(msg):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": msg}}))
    sys.exit(0)


def check_read(inp):
    path = inp.get("file_path", "")
    if inp.get("limit"):
        return
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size > BIG_BYTES and path.lower().endswith(BIG_EXT):
        deny(f"BLOCKED: {os.path.basename(path)} is {size // 1024} KB and was read in full without a limit. {READ_HINT}")


def check_command(cmd):
    is_commit = re.search(r"\bgit\b[^\n]*\bcommit\b", cmd)
    is_pr = re.search(r"\bgh\s+(pr|issue|release)\s+(create|edit|comment|review)\b", cmd)
    if BLOCK_AGENT_TRAILERS and (is_commit or is_pr) and TRAILER.search(cmd):
        deny("BLOCKED: commit/PR text must not carry agent attribution (Co-Authored-By, Signed-off-by, Generated with, robot emoji). "
             f"Project rules outrank tool defaults ({RULES_DOC}). Rewrite the message without that line.")
    if BLOCK_IDENTITY_CHANGE and IDENTITY.search(cmd) and re.search(r"\bgit\b", cmd):
        deny("BLOCKED: git identity (author, committer, user.name, user.email) belongs to the user; agents must not set it "
             f"({RULES_DOC}).")
    if BLOCK_NO_VERIFY and re.search(r"\bgit\b[^\n]*--no-verify\b", cmd):
        deny(f"BLOCKED: --no-verify is not allowed ({RULES_DOC}, Safety). Fix the cause of the failing hook instead.")
    if BLOCK_SLEEP_LOOP and re.search(r"\bwhile\b[^\n]*\bsleep\b|\buntil\b[^\n]*\bsleep\b|\bsleep\s+\d+\s*(&&|;)\s*\S", cmd):
        deny(f"BLOCKED: no polling or sleep loops ({RULES_DOC}, rule 2). Run it in the background, then stop calling tools and wait.")
    if ASK_DESTRUCTIVE and re.search(
        r"\bgit\s+push\b[^\n]*(--force\b|--force-with-lease|\s-f\b|--delete\b)"
        r"|\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*f|\bgit\s+branch\s+-D\b"
        r"|\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r|\bRemove-Item\b[^\n]*-Recurse[^\n]*-Force",
        cmd,
    ):
        ask("Destructive command (force push, reset --hard, clean -f, recursive delete, branch delete): explicit user confirmation required.")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never break a session over odd input
    tool, inp = data.get("tool_name"), data.get("tool_input", {})
    if tool == "Read":
        check_read(inp)
    elif tool in ("Bash", "PowerShell"):
        check_command(inp.get("command", ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
