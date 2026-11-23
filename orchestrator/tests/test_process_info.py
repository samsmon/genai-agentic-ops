"""Tests for process liveness in orchestrator/governance/process_info.py."""
import subprocess
import sys
import time
import unittest

from orchestrator.governance.process_info import (
    IS_WINDOWS,
    get_hostname,
    get_process_start_time,
    is_process_alive,
)


class TestProcessAlive(unittest.TestCase):
    def _spawn(self) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

    def test_running_process_is_alive(self) -> None:
        proc = self._spawn()
        try:
            start = get_process_start_time(proc.pid)
            self.assertTrue(is_process_alive(get_hostname(), proc.pid, start))
        finally:
            proc.kill()
            proc.wait()

    def test_killed_process_with_open_handle_is_dead(self) -> None:
        """An exited process must not count as alive while a handle to it is open."""
        proc = self._spawn()
        start = get_process_start_time(proc.pid)
        proc.kill()
        deadline = time.time() + 10
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        self.assertIsNotNone(proc.poll())
        # Popen still holds its handle here (proc.wait/close not called).
        self.assertFalse(is_process_alive(get_hostname(), proc.pid, start))
        if IS_WINDOWS:
            proc._handle.Close()


if __name__ == "__main__":
    unittest.main()
