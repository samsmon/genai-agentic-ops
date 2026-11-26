"""terminate_process_tree must stop the target and its descendants, never the caller (POSIX).

The caller runs in its own session so that a regression kills only that helper and not the
test runner.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The target stays in the caller's process group; its child may or may not start a new session.
CALLER = textwrap.dedent(
    """
    import os, subprocess, sys, time
    from orchestrator.adapters.process_runner import terminate_process_tree

    target_code = (
        "import subprocess, sys, time;"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],"
        " start_new_session=" + sys.argv[1] + ");"
        "print(c.pid, flush=True); time.sleep(60)"
    )
    target = subprocess.Popen([sys.executable, "-c", target_code], stdout=subprocess.PIPE, text=True)
    grandchild = int(target.stdout.readline())
    terminate_process_tree(target.pid)
    target.wait(timeout=10)

    def running(pid):
        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(out) and not out.startswith("Z")

    for _ in range(100):
        if not running(grandchild):
            break
        time.sleep(0.05)
    print("caller-alive", "grandchild-running" if running(grandchild) else "grandchild-stopped")
    """
)


@unittest.skipIf(sys.platform == "win32", "POSIX process groups")
class TerminateProcessTreeTests(unittest.TestCase):
    def _run(self, grandchild_new_session: bool) -> None:
        res = subprocess.run(
            [sys.executable, "-B", "-c", CALLER, str(grandchild_new_session)],
            cwd=ROOT, capture_output=True, text=True, timeout=60, start_new_session=True,
        )
        self.assertEqual(res.returncode, 0, f"caller died or failed: {res.returncode} {res.stderr}")
        self.assertEqual(res.stdout.strip(), "caller-alive grandchild-stopped")

    def test_target_sharing_the_callers_group(self) -> None:
        self._run(False)

    def test_descendant_in_its_own_session_is_stopped(self) -> None:
        self._run(True)


if __name__ == "__main__":
    unittest.main()
