"""PreToolUse guard for Antigravity: thin adapter over the agent-neutral policy core.

Input  (stdin, camelCase): {"toolCall": {"name": "run_command", "args": {"CommandLine": "...", "Cwd": "..."}}, "stepIdx": 19, ...}
Output (stdout): {"decision": "allow|ask|deny", "reason": "..."} and exit 0.

Live evidence (Gemini 3.8 Flash High on Windows, 2026-10-23): a "deny" answer blocks the command ("tool call denied by
pre-tool hook"); an "ask" answer did NOT stop `git push --force`, the IDE ran it without a prompt. So the core's "ask" is
answered as "deny" (ASK_AS = "deny") with a message that tells the agent to ask the user in the chat. The user then runs
the command in their own terminal, or sets ASK_AS = "ask" (or env AGENTIC_OPS_ASK_AS=ask) once the IDE enforces it.
Fails open: odd input or a missing core answers allow.
"""
import importlib.util
import json
import os
import sys

ASK_AS = os.environ.get("AGENTIC_OPS_ASK_AS", "deny")  # "deny" (default) or "ask"


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
    if decision == "ask" and ASK_AS == "deny":
        answer("deny", message + " Antigravity does not enforce an ask answer, so this command is blocked. "
                                 "Ask the user in the chat; the user runs it in their own terminal or lifts the guard.")
    answer(decision, message)


if __name__ == "__main__":
    main()
