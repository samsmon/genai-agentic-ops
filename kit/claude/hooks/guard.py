"""PreToolUse guard for Claude Code: thin adapter over the agent-neutral policy core (kit/core/policy.py).

deny  -> exit 2 + stderr (the model sees the reason and must change approach)
ask   -> JSON permissionDecision=ask (the user decides)

Edit the policy constants in core/policy.py, not here. Runs only inside Claude Code; other agents use
their own adapter (kit/adapters/) or rely on the git hooks and the written rules.
"""
import importlib.util
import json
import os
import sys


def load_policy():
    """Find core/policy.py: AGENTIC_OPS_POLICY, the kit layout, or the installed layout. None if missing."""
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.environ.get("AGENTIC_OPS_POLICY", ""),
              os.path.join(here, "..", "..", "core", "policy.py"),
              os.path.join(here, "..", "..", "scripts", "agentic-ops", "core", "policy.py")):
        if c and os.path.isfile(c):
            spec = importlib.util.spec_from_file_location("agentic_ops_policy", c)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never break a session over odd input
    policy = load_policy()
    if policy is None:
        sys.stderr.write("agentic-ops guard: core/policy.py not found, guard disabled (see kit/README.md install layout)\n")
        sys.exit(0)
    tool, inp = data.get("tool_name"), data.get("tool_input", {})
    if tool == "Read":
        path = inp.get("file_path", "")
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        decision, message = policy.evaluate(read_path=path, read_size=size, read_limited=bool(inp.get("limit")))
    elif tool in ("Bash", "PowerShell"):
        decision, message = policy.evaluate(command=inp.get("command", ""))
    else:
        sys.exit(0)
    if decision == "deny":
        sys.stderr.write(message + "\n")
        sys.exit(2)
    if decision == "ask":
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": message}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
