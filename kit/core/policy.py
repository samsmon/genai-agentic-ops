"""Agent-neutral policy core: decides allow / ask / deny for one shell command or one file read.

Pure logic, standard library only, no I/O. Every hook adapter (Claude Code, Codex, Cursor, OpenCode,
Antigravity) reads its own tool's payload, calls evaluate(), and answers in its own tool's format.

    decision, message = evaluate(command="git push --force")          # ('ask', '...')
    decision, message = evaluate(read_path="docs/x.md", read_size=90_000, read_limited=False)

Command line (used by adapters that cannot import Python, such as the OpenCode plugin):
    echo '{"command": "git reset --hard"}' | python -I policy.py
    -> {"decision": "ask", "message": "..."}      (always exit 0; bad input means allow)

Policies are plain constants below; edit them to fit the project.
"""
import json
import re
import sys

RULES_DOC = "AGENTS.md"      # named in block messages
BIG_BYTES = 24_000           # ~6k tokens; reading larger text files in full is wasteful
BIG_EXT = (".md", ".log", ".txt", ".json", ".yml", ".yaml", ".sql", ".csv")
READ_HINT = "Search first (grep) or read it in parts with offset/limit."

BLOCK_AGENT_TRAILERS = True   # commit/PR text must not carry agent attribution lines
BLOCK_IDENTITY_CHANGE = True  # agents must not set git author/committer identity
BLOCK_NO_VERIFY = True
BLOCK_HOOK_BYPASS = True      # agents must not use the user-only escape hatches of the commit-msg hook
BLOCK_SLEEP_LOOP = True
ASK_DESTRUCTIVE = True

ALLOW, ASK, DENY = "allow", "ask", "deny"

_BYPASS_VARS = (
    r"(?:ALLOW_AGENT_TRAILER|SKIP_COMMIT_FORMAT|ALLOW_SECRET_PATTERN"
    r"|SECRET_SCAN_SKIP|ALLOW_BIG_FILES|ALLOW_LARGE_SOURCE)"
)
TRAILER = re.compile(r"co-authored-by\s*:|signed-off-by\s*:|generated-by\s*:|generated with|\U0001F916", re.I)
BYPASS = re.compile(
    rf"\b{_BYPASS_VARS}\s*="
    rf"|\$env:{_BYPASS_VARS}\b|\bEnv:{_BYPASS_VARS}\b"
    rf"|\bSet-Item\b[^\n]*\b(?:env:|env\\|env/)?{_BYPASS_VARS}\b"
    rf"|\b(?:export|setenv)\s+{_BYPASS_VARS}\b"
    rf"|SetEnvironmentVariable\([^)]*{_BYPASS_VARS}",
    re.I,
)
IDENTITY = re.compile(
    r"--author\b|\bGIT_(AUTHOR|COMMITTER)_(NAME|EMAIL)\b|-c\s+user\.(name|email)\b"
    r"|\bgit\b[^\n;|&]*\bconfig\b"
    r"(?!(?![^\n;|&]*\s(?:--replace-all|--add|--unset|--unset-all)\b)"
    r"[^\n;|&]*\s(?:--get|--get-all|--list)(?=\s|$))"
    r"[^\n;|&]*\buser\.(name|email)\b",
    re.I,
)
SLEEP = re.compile(
    r"\b(?:while|until)\b[^\n]*\b(?:sleep|Start-Sleep)\b"
    r"|\b(?:sleep\s+\d+|Start-Sleep\b[^\n]*)\s*(?:&&|;)\s*\S"
    r"|(?:^|[;|&{(]\s*)Start-Sleep\b"
    r"|\bStart-Sleep\s+(?:-(?:Seconds|Milliseconds|s|m)\b|\d+)",
    re.I,
)
DESTRUCTIVE = re.compile(
    r"\bgit\s+push\b[^\n]*(--force\b|--force-with-lease|\s-f\b|--delete\b)"
    r"|\bgit\s+reset\s+--hard\b|\bgit\s+clean\s+-[a-z]*f|\bgit\s+branch\s+(-D\b|--delete\b)"
    r"|\bgit\s+tag\s+(-d\b|--delete\b)"
    r"|\bgit\b(?:\s+-C\s+\S+)?\s+restore\b[^\n;|&]*\s\.(?=\s|$|[;|&])"
    r"|\bgit\b(?:\s+-C\s+\S+)?\s+checkout\b[^\n;|&]*\s--\s+\.(?=\s|$|[;|&])"
    r"|\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r"
    r"|\b(?:rmdir|rd)\b[^\n;|&]*(?:/s(?=\s|/|$)[^\n;|&]*/q(?=\s|/|$)|/q(?=\s|/|$)[^\n;|&]*/s(?=\s|/|$))"
    r"|\bRemove-Item\b[^\n;|&]*(?:-(?:r|rec|recurse)\b[^\n;|&]*-(?:fo|for|forc|force)\b|-(?:fo|for|forc|force)\b[^\n;|&]*-(?:r|rec|recurse)\b)",
    re.I,
)


def check_command(cmd):
    if BLOCK_HOOK_BYPASS and BYPASS.search(cmd):
        return DENY, ("BLOCKED: hook override variables (ALLOW_AGENT_TRAILER, SKIP_COMMIT_FORMAT, ALLOW_SECRET_PATTERN, "
                      "SECRET_SCAN_SKIP, ALLOW_BIG_FILES, ALLOW_LARGE_SOURCE) are escape hatches for the user's own terminal; "
                      f"agents must not set them ({RULES_DOC}). Fix the underlying check so the hook passes.")
    is_commit = re.search(r"\bgit\b[^\n]*\bcommit\b", cmd)
    is_pr = re.search(r"\bgh\s+(pr|issue|release)\s+(create|edit|comment|review)\b", cmd)
    if BLOCK_AGENT_TRAILERS and (is_commit or is_pr) and TRAILER.search(cmd):
        return DENY, ("BLOCKED: commit/PR text must not carry agent attribution (Co-Authored-By, Signed-off-by, Generated with, robot emoji). "
                      f"Project rules outrank tool defaults ({RULES_DOC}). Rewrite the message without that line.")
    if BLOCK_IDENTITY_CHANGE and IDENTITY.search(cmd) and re.search(r"\bgit\b", cmd):
        return DENY, ("BLOCKED: git identity (author, committer, user.name, user.email) belongs to the user; agents must not set it "
                      f"({RULES_DOC}).")
    if BLOCK_NO_VERIFY and re.search(r"\bgit\b[^\n]*--no-verify\b", cmd):
        return DENY, f"BLOCKED: --no-verify is not allowed ({RULES_DOC}, Safety). Fix the cause of the failing hook instead."
    if BLOCK_SLEEP_LOOP and SLEEP.search(cmd):
        return DENY, f"BLOCKED: no polling or sleep loops ({RULES_DOC}, rule 2). Run it in the background, then stop calling tools and wait."
    if ASK_DESTRUCTIVE and DESTRUCTIVE.search(cmd):
        return ASK, "Destructive command (force push, reset --hard, clean -f, recursive delete, branch delete, discard .): explicit user confirmation required."
    return ALLOW, ""


def check_read(path, size, limited):
    if limited or not path or size is None:
        return ALLOW, ""
    if size > BIG_BYTES and str(path).lower().endswith(BIG_EXT):
        name = re.split(r"[\\/]", str(path))[-1]
        return DENY, f"BLOCKED: {name} is {size // 1024} KB and was read in full without a limit. {READ_HINT}"
    return ALLOW, ""


def evaluate(command=None, read_path=None, read_size=None, read_limited=False):
    """Return (decision, message). decision is 'allow', 'ask' or 'deny'; message explains ask/deny."""
    if command:
        d, m = check_command(str(command))
        if d != ALLOW:
            return d, m
    if read_path:
        return check_read(read_path, read_size, read_limited)
    return ALLOW, ""


def _main():
    try:
        data = json.load(sys.stdin)
        d, m = evaluate(data.get("command"), data.get("read_path"), data.get("read_size"), bool(data.get("read_limited")))
    except Exception:  # never break a session over odd input
        d, m = ALLOW, ""
    sys.stdout.write(json.dumps({"decision": d, "message": m}))


if __name__ == "__main__":
    _main()
