"""TENJIN Agent and Process Isolation.

Ensures child processes, scanners, and agent repair tasks execute in an isolated
environment with sanitized environment variables and bounded workspace paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional, Set

# Environment variables that must never leak to arbitrary repository child processes
SENSITIVE_ENV_VARS: Set[str] = {
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "AZURE_CLIENT_SECRET",
    "SLACK_BOT_TOKEN",
    "DISCORD_TOKEN",
    "NPM_TOKEN",
    "PYPI_API_TOKEN",
    "SSH_AUTH_SOCK",
    "SSH_PRIVATE_KEY",
}


def get_sanitized_environment(extra_vars: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return an isolated environment dictionary with sensitive tokens scrubbed."""
    clean_env: Dict[str, str] = {}

    for k, v in os.environ.items():
        if k.upper() not in SENSITIVE_ENV_VARS and not any(
            secret_term in k.lower() for secret_term in ["token", "secret", "password", "apikey", "api_key"]
        ):
            clean_env[k] = v

    if extra_vars:
        for k, v in extra_vars.items():
            clean_env[k] = v

    return clean_env


def verify_path_containment(child_path: str | Path, parent_workspace: str | Path) -> bool:
    r"""Verify that a path is strictly contained within the designated workspace.

    Prevents directory traversal attacks (e.g. `../../etc/passwd` or `..\..\Windows`).
    """
    try:
        resolved_parent = Path(parent_workspace).resolve()
        resolved_child = Path(child_path).resolve()
        return resolved_parent in resolved_child.parents or resolved_child == resolved_parent
    except Exception:
        return False
