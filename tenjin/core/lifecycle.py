"""TENJIN Worker Lifecycle and Windows Service Integration.

Manages process daemonization, duplicate-worker prevention via PID files,
graceful signal handling, and Windows Task Scheduler integration (`schtasks.exe`)
for user-level automatic startup after login without requiring admin rights.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from tenjin.core.capabilities import _find_executable

logger = logging.getLogger("tenjin.core.lifecycle")

TASK_NAME = "TENJIN_Personal_Engineer"


class ProcessLock:
    """PID-file based process lock to ensure single running daemon instance."""

    def __init__(self, pid_file_path: Path):
        self.pid_file = pid_file_path

    def acquire(self) -> bool:
        """Attempt to acquire worker process lock."""
        if self.pid_file.is_file():
            try:
                pid_str = self.pid_file.read_text().strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    # Check if process is actually alive
                    if self._is_pid_alive(pid):
                        return False
            except Exception:
                pass

        # Write current PID
        try:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            self.pid_file.write_text(str(os.getpid()), encoding="utf-8")
            return True
        except Exception:
            return False

    def release(self) -> None:
        """Release PID file on shutdown."""
        self.pid_file.unlink(missing_ok=True)

    def is_running(self) -> bool:
        """Check if active worker PID is alive."""
        if not self.pid_file.is_file():
            return False
        try:
            pid = int(self.pid_file.read_text().strip())
            return self._is_pid_alive(pid)
        except Exception:
            return False

    def _is_pid_alive(self, pid: int) -> bool:
        if platform.system() == "Windows":
            # Windows OpenProcess check
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False


def install_windows_startup_task(python_exe: str, base_dir: Path) -> Tuple[bool, str]:
    """Register TENJIN in Windows Task Scheduler to start on user login."""
    if platform.system() != "Windows":
        return False, "Task Scheduler is only supported on Windows hosts."

    schtasks = _find_executable("schtasks")
    if not schtasks:
        return False, "schtasks.exe not found on system."

    # Build command to start tenjin daemon
    cmd_str = f'"{python_exe}" -m tenjin.cli.main start'

    # Register task for current user on logon (does NOT require administrator privileges)
    create_args = [
        schtasks,
        "/Create",
        "/TN",
        TASK_NAME,
        "/TR",
        cmd_str,
        "/SC",
        "ONLOGON",
        "/F",
    ]

    try:
        res = subprocess.run(create_args, capture_output=True, text=True, timeout=15.0)
        if res.returncode == 0:
            return True, f"Successfully registered Windows Task '{TASK_NAME}' to run at user logon."
        else:
            return False, f"schtasks failed ({res.returncode}): {res.stderr.strip() or res.stdout.strip()}"
    except Exception as e:
        return False, f"Exception creating scheduled task: {e}"


def uninstall_windows_startup_task() -> Tuple[bool, str]:
    """Unregister TENJIN from Windows Task Scheduler."""
    if platform.system() != "Windows":
        return False, "Task Scheduler is only supported on Windows hosts."

    schtasks = _find_executable("schtasks")
    if not schtasks:
        return False, "schtasks.exe not found on system."

    delete_args = [
        schtasks,
        "/Delete",
        "/TN",
        TASK_NAME,
        "/F",
    ]

    try:
        res = subprocess.run(delete_args, capture_output=True, text=True, timeout=15.0)
        if res.returncode == 0:
            return True, f"Successfully removed Windows Task '{TASK_NAME}'."
        else:
            return False, f"schtasks delete failed: {res.stderr.strip() or res.stdout.strip()}"
    except Exception as e:
        return False, f"Exception deleting scheduled task: {e}"


def check_windows_task_status() -> Tuple[bool, str]:
    """Query current status of the TENJIN task in Task Scheduler."""
    if platform.system() != "Windows":
        return False, "Not a Windows host"

    schtasks = _find_executable("schtasks")
    if not schtasks:
        return False, "schtasks.exe not available"

    query_args = [schtasks, "/Query", "/TN", TASK_NAME]
    try:
        res = subprocess.run(query_args, capture_output=True, text=True, timeout=10.0)
        if res.returncode == 0:
            return True, "Configured and active in Windows Task Scheduler"
        else:
            return False, "Not configured in Windows Task Scheduler"
    except Exception as e:
        return False, str(e)
