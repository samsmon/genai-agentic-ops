"""Host and process creation time verification.

Provides process start-time verification to guard against PID reuse
staleness errors across Windows and POSIX platforms.
"""
from __future__ import annotations

import os
import platform
import socket
import sys
from typing import Any

IS_WINDOWS = platform.system() == "Windows"


def get_hostname() -> str:
    """Return local hostname."""
    return socket.gethostname()


def _get_windows_process_creation_time(pid: int) -> str | None:
    """Return creation time string for a Windows process, or None if dead."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None

    try:
        c_time, e_time, k_time, u_time = (
            FILETIME(),
            FILETIME(),
            FILETIME(),
            FILETIME(),
        )
        if kernel32.GetProcessTimes(
            handle,
            ctypes.byref(c_time),
            ctypes.byref(e_time),
            ctypes.byref(k_time),
            ctypes.byref(u_time),
        ):
            val = (c_time.dwHighDateTime << 32) | c_time.dwLowDateTime
            return str(val)
        return None
    finally:
        kernel32.CloseHandle(handle)


def _get_posix_process_creation_time(pid: int) -> str | None:
    """Return creation time string for a POSIX process, or None if dead."""
    try:
        os.kill(pid, 0)
    except OSError:
        return None

    stat_file = f"/proc/{pid}/stat"
    if os.path.isfile(stat_file):
        try:
            with open(stat_file, "r", encoding="utf-8") as f:
                content = f.read()
            # 22nd field is starttime in jiffies after command name in parentheses
            rparen = content.rfind(")")
            if rparen != -1:
                fields = content[rparen + 2 :].split()
                if len(fields) >= 20:
                    return fields[19]  # 22nd overall
        except OSError:
            pass

    return f"posix-{pid}"


def get_process_start_time(pid: int | None = None) -> str:
    """Return creation time string of process."""
    target_pid = os.getpid() if pid is None else pid
    if IS_WINDOWS:
        res = _get_windows_process_creation_time(target_pid)
        if res:
            return res
    else:
        res = _get_posix_process_creation_time(target_pid)
        if res:
            return res
    return f"fallback-{target_pid}"


def get_host_tuple() -> dict[str, Any]:
    """Return dictionary with hostname, pid, and process_start_time."""
    pid = os.getpid()
    return {
        "hostname": get_hostname(),
        "pid": pid,
        "process_start_time": get_process_start_time(pid),
    }


def is_process_alive(
    hostname: str, pid: int, process_start_time: str
) -> bool | None:
    """Check if process identified by (hostname, pid, start_time) is alive.

    Returns:
        True: Process is alive and start time matches.
        False: Process is definitely dead or PID was reused.
        None: Process is on a remote host (cannot verify locally).
    """
    if hostname != get_hostname():
        return None

    if IS_WINDOWS:
        current_time = _get_windows_process_creation_time(pid)
        if current_time is None:
            return False
        return current_time == process_start_time

    # POSIX
    try:
        os.kill(pid, 0)
    except OSError:
        return False

    current_time = _get_posix_process_creation_time(pid)
    if current_time is None:
        return False
    return current_time == process_start_time
