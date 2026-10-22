"""PreToolUse guard for Antigravity (experimental): thin adapter over the agent-neutral policy core.

Input  (stdin, camelCase): {"toolCall": {"name": "run_command", "args": {"CommandLine": "...", "Cwd": "..."}}, "stepIdx": 19, ...}
Output (stdout): {"decision": "allow|ask|deny", "reason": "..."} and exit 0.
Experimental: the docs show the input and the "ask" output verbatim; the "deny" output shape (decision + reason)
is taken from the field description and was not shown as a full example. Not run inside Antigravity yet.
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


def answer(decision, reason=""):
    out = {"decision": decision}
    if reason:
        out["reason"] = reason
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
        call = data.get("toolCall") or {}
        command = (call.get("args") or {}).get("CommandLine", "")
    except Exception:
        answer("allow")
    if call.get("name") != "run_command":
        answer("allow")
    policy = load_policy()
    if policy is None:
        sys.stderr.write("agentic-ops guard: core/policy.py not found, guard disabled (see kit/README.md install layout)\n")
        answer("allow")
    decision, message = policy.evaluate(command=command)
    answer(decision, message)


if __name__ == "__main__":
    main()
