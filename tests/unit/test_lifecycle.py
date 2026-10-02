"""Unit tests for ProcessLock, systemd generators, and lifecycle helpers."""

import tempfile
from pathlib import Path

from tenjin.core.lifecycle import (
    ProcessLock,
    check_startup_service_status,
    generate_systemd_service,
    generate_systemd_timer,
)


def test_process_lock_acquisition_and_release():
    with tempfile.TemporaryDirectory() as tmp_dir:
        pid_file = Path(tmp_dir) / "test.pid"
        lock1 = ProcessLock(pid_file)
        assert lock1.acquire() is True
        assert lock1.is_running() is True

        # Second lock attempt on same file
        lock2 = ProcessLock(pid_file)
        assert lock2.acquire() is False

        lock1.release()
        assert lock1.is_running() is False
        assert not pid_file.exists()


def test_systemd_service_and_timer_generation():
    service_content = generate_systemd_service(
        python_exe="/usr/bin/python3",
        working_dir=Path("/opt/tenjin"),
        user="tenjin-worker",
    )
    assert "[Unit]" in service_content
    assert "[Service]" in service_content
    assert "ExecStart=/usr/bin/python3 -m tenjin.cli.main start" in service_content
    assert "WorkingDirectory=/opt/tenjin" in service_content
    assert "User=tenjin-worker" in service_content
    assert "Restart=always" in service_content

    timer_content = generate_systemd_timer(schedule_time="03:30")
    assert "[Timer]" in timer_content
    assert "OnCalendar=*-*-* 03:30:00" in timer_content
    assert "Unit=tenjin.service" in timer_content


def test_check_startup_service_status_runs_without_crashing():
    configured, msg = check_startup_service_status()
    assert isinstance(configured, bool)
    assert isinstance(msg, str)
