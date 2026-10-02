"""TENJIN Worker Lifecycle and Service Integration.

Manages process daemonization, duplicate-worker prevention via PID files,
graceful signal handling, Windows Task Scheduler integration (`schtasks.exe`),
and Linux systemd service/timer units (`tenjin.service`, `tenjin.timer`)
for always-on remote worker deployment without requiring root/administrator rights.
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
SYSTEMD_SERVICE_NAME = "tenjin.service"
SYSTEMD_TIMER_NAME = "tenjin.timer"


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
            except Exception as e:
                logger.debug("Failed to inspect existing PID file: %s", e)

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


# =====================================================================
# Windows Task Scheduler Integration
# =====================================================================

def install_windows_startup_task(python_exe: str, base_dir: Path) -> Tuple[bool, str]:
    """Register TENJIN in Windows Task Scheduler to start on user login."""
    if platform.system() != "Windows":
        return False, "Task Scheduler is only supported on Windows hosts."

    schtasks = _find_executable("schtasks")
    if not schtasks:
        return False, "schtasks.exe not found on system."

    cmd_str = f'"{python_exe}" -m tenjin.cli.main start'

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


# =====================================================================
# Linux systemd Service & Timer Generators
# =====================================================================

def generate_systemd_service(
    python_exe: str,
    working_dir: Path,
    user: Optional[str] = None,
) -> str:
    """Generate systemd service unit file content for the TENJIN daemon."""
    user_line = f"User={user}\n" if user else ""
    posix_workdir = Path(working_dir).as_posix()
    return f"""[Unit]
Description=TENJIN Autonomous Software Engineering Daemon
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={posix_workdir}
ExecStart={python_exe} -m tenjin.cli.main start
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1
{user_line}StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""


def generate_systemd_timer(schedule_time: str = "02:00") -> str:
    """Generate systemd timer unit file content for scheduled daily execution."""
    return f"""[Unit]
Description=TENJIN Daily Maintenance Mission Timer
After=network.target

[Timer]
OnCalendar=*-*-* {schedule_time}:00
Persistent=true
Unit=tenjin.service

[Install]
WantedBy=timers.target
"""


def install_systemd_service(
    working_dir: Path,
    python_exe: Optional[str] = None,
    schedule_time: str = "02:00",
    user_mode: bool = True,
) -> Tuple[bool, str]:
    """Install systemd service and timer units for always-on remote worker deployment."""
    if platform.system() == "Windows":
        return False, "systemd is only supported on Linux/POSIX hosts."

    systemctl = _find_executable("systemctl")
    if not systemctl:
        return False, "systemctl executable not found on system."

    py_exe = python_exe or sys.executable
    service_content = generate_systemd_service(py_exe, working_dir)
    timer_content = generate_systemd_timer(schedule_time)

    # Determine unit destination directory (user-level by default)
    if user_mode:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
    else:
        unit_dir = Path("/etc/systemd/system")

    try:
        unit_dir.mkdir(parents=True, exist_ok=True)
        service_file = unit_dir / SYSTEMD_SERVICE_NAME
        timer_file = unit_dir / SYSTEMD_TIMER_NAME

        service_file.write_text(service_content, encoding="utf-8")
        timer_file.write_text(timer_content, encoding="utf-8")

        # Reload systemd and enable timer
        cmd_prefix = [systemctl, "--user"] if user_mode else [systemctl]
        subprocess.run(cmd_prefix + ["daemon-reload"], check=True, capture_output=True, timeout=15.0)
        subprocess.run(cmd_prefix + ["enable", "--now", SYSTEMD_TIMER_NAME], check=True, capture_output=True, timeout=15.0)

        return True, f"Successfully installed and enabled systemd service and timer in {unit_dir}."
    except Exception as e:
        return False, f"Failed to install systemd service: {e}"


def uninstall_systemd_service(user_mode: bool = True) -> Tuple[bool, str]:
    """Uninstall and disable systemd service and timer units."""
    if platform.system() == "Windows":
        return False, "systemd is only supported on Linux/POSIX hosts."

    systemctl = _find_executable("systemctl")
    if not systemctl:
        return False, "systemctl executable not found on system."

    cmd_prefix = [systemctl, "--user"] if user_mode else [systemctl]
    unit_dir = (Path.home() / ".config" / "systemd" / "user") if user_mode else Path("/etc/systemd/system")

    try:
        subprocess.run(cmd_prefix + ["stop", SYSTEMD_TIMER_NAME], capture_output=True, timeout=15.0)
        subprocess.run(cmd_prefix + ["disable", SYSTEMD_TIMER_NAME], capture_output=True, timeout=15.0)
        subprocess.run(cmd_prefix + ["stop", SYSTEMD_SERVICE_NAME], capture_output=True, timeout=15.0)
        subprocess.run(cmd_prefix + ["disable", SYSTEMD_SERVICE_NAME], capture_output=True, timeout=15.0)

        (unit_dir / SYSTEMD_TIMER_NAME).unlink(missing_ok=True)
        (unit_dir / SYSTEMD_SERVICE_NAME).unlink(missing_ok=True)

        subprocess.run(cmd_prefix + ["daemon-reload"], capture_output=True, timeout=15.0)
        return True, f"Successfully removed systemd units from {unit_dir}."
    except Exception as e:
        return False, f"Failed to uninstall systemd service: {e}"


def check_systemd_status(user_mode: bool = True) -> Tuple[bool, str]:
    """Check the status of the systemd service and timer."""
    if platform.system() == "Windows":
        return False, "Not a Linux host"

    systemctl = _find_executable("systemctl")
    if not systemctl:
        return False, "systemctl not available"

    cmd_prefix = [systemctl, "--user"] if user_mode else [systemctl]
    try:
        res = subprocess.run(
            cmd_prefix + ["is-active", SYSTEMD_SERVICE_NAME],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        status = res.stdout.strip()
        timer_res = subprocess.run(
            cmd_prefix + ["is-enabled", SYSTEMD_TIMER_NAME],
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        timer_status = timer_res.stdout.strip()
        is_active = status == "active" or timer_status == "enabled"
        return is_active, f"Service: {status}, Timer: {timer_status}"
    except Exception as e:
        return False, str(e)


# =====================================================================
# Cross-Platform Service Dispatch
# =====================================================================

def install_startup_service(
    python_exe: str,
    base_dir: Path,
    schedule_time: str = "02:00",
) -> Tuple[bool, str]:
    """Install OS-appropriate background service (Task Scheduler on Windows, systemd on Linux)."""
    if platform.system() == "Windows":
        return install_windows_startup_task(python_exe, base_dir)
    else:
        return install_systemd_service(base_dir, python_exe, schedule_time)


def uninstall_startup_service() -> Tuple[bool, str]:
    """Uninstall OS-appropriate background service."""
    if platform.system() == "Windows":
        return uninstall_windows_startup_task()
    else:
        return uninstall_systemd_service()


def check_startup_service_status() -> Tuple[bool, str]:
    """Query status of background startup service across Windows and Linux."""
    if platform.system() == "Windows":
        return check_windows_task_status()
    else:
        return check_systemd_status()
