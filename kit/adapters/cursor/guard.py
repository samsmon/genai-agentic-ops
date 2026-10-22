"""beforeShellExecution guard for Cursor: thin adapter over the agent-neutral policy core (kit/core/policy.py).

Input  (stdin): {"command": "...", "cwd": "...", "hook_event_name": "beforeShellExecution", ...}
Output (stdout): {"permission": "allow|deny|ask", "user_message": "...", "agent_message": "..."} and exit 0.
Fails open: odd input or a missing core answers allow.
"""
import importlib.util
import json
import os
import sys


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


def answer(permission, message=""):
    out = {"permission": permission}
    if message:
        out["user_message"] = message
        out["agent_message"] = message
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        answer("allow")
    policy = load_policy()
    if policy is None:
        sys.stderr.write("agentic-ops guard: core/policy.py not found, guard disabled (see kit/README.md install layout)\n")
        answer("allow")
    decision, message = policy.evaluate(command=data.get("command", ""))
    answer(decision, message)


if __name__ == "__main__":
    main()
