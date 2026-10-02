"""TENJIN Real Desktop Notification Subsystem.

Dispatches local notifications for critical audit findings, verification failures,
and approval requests via platform-native mechanisms (Windows PowerShell balloon/toast
or console bell).
"""

from __future__ import annotations

import logging
import platform
import subprocess

from tenjin.core.capabilities import _find_executable
from tenjin.security.redaction import redact_secrets

logger = logging.getLogger("tenjin.notifications")


def send_desktop_notification(
    title: str,
    message: str,
    urgency: str = "normal",  # "low", "normal", "critical"
) -> bool:
    """Send a real desktop notification without third-party proprietary dependencies."""
    clean_title = redact_secrets(title).replace('"', '`"')
    clean_msg = redact_secrets(message).replace('"', '`"')

    logger.info("[NOTIFICATION %s] %s: %s", urgency.upper(), title, message)

    if platform.system() == "Windows":
        pwsh = _find_executable("pwsh") or _find_executable("powershell")
        if pwsh:
            # Native Windows balloon/toast via PowerShell
            ps_script = f"""
            [reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null
            $notify = New-Object System.Windows.Forms.NotifyIcon
            $notify.Icon = [System.Drawing.SystemIcons]::Information
            $notify.Visible = $True
            $notify.ShowBalloonTip(5000, "{clean_title}", "{clean_msg}", [System.Windows.Forms.ToolTipIcon]::Info)
            """
            try:
                subprocess.run(
                    [pwsh, "-NoProfile", "-Command", ps_script],
                    capture_output=True,
                    timeout=5.0,
                )
                return True
            except Exception as e:
                logger.debug("PowerShell balloon notification failed: %s", e)

    return False
