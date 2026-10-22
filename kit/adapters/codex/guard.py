"""PreToolUse guard for Codex: thin adapter over the agent-neutral policy core (kit/core/policy.py).

Input  (stdin): {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "..."}, ...}
Deny   -> exit 2 + reason on stderr (documented Codex behavior).
Ask    -> Codex does not support "ask" yet, so an ask decision is turned into a deny that tells the
          agent to get the user's confirmation first (CODEX_ASK_AS = "deny"; "allow" lets it through).
Fails open: odd input or a missing core never blocks a session.
"""
import importlib.util
import json
import os
import sys

CODEX_ASK_AS = "deny"


def load_policy():
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
        sys.exit(0)
    if data.get("tool_name") != "Bash":
        sys.exit(0)
    policy = load_policy()
    if policy is None:
        sys.stderr.write("agentic-ops guard: core/policy.py not found, guard disabled (see kit/README.md install layout)\n")
        sys.exit(0)
    decision, message = policy.evaluate(command=(data.get("tool_input") or {}).get("command", ""))
    if decision == "ask":
        if CODEX_ASK_AS != "deny":
            sys.exit(0)
        message = "CONFIRMATION REQUIRED (this hook cannot ask in Codex): stop and ask the user before running this. " + message
        decision = "deny"
    if decision == "deny":
        sys.stderr.write(message + "\n")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
