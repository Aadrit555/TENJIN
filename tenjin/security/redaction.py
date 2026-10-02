"""TENJIN Centralized Secret Redaction Engine.

Provides deep regex and heuristic-based redaction for sensitive credentials,
tokens, private keys, connection strings, and passwords across all persistence
surfaces (logs, database, dashboard, reports, stdout/stderr).
"""

from __future__ import annotations

import re
from typing import List, Tuple

# Compiled regex patterns for well-known secrets and token formats
SECRET_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    # GitHub Tokens
    ("GITHUB_PAT", re.compile(r"github_pat_[a-zA-Z0-9_]{22,82}", re.IGNORECASE)),
    ("GITHUB_TOKEN", re.compile(r"gh[pousr]_[a-zA-Z0-9]{30,255}", re.IGNORECASE)),
    # Generic Bearer Tokens
    ("BEARER_TOKEN", re.compile(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE)),
    # Private Keys (RSA, OpenSSH, EC, PGP, etc.)
    (
        "PRIVATE_KEY",
        re.compile(
            r"-----BEGIN\s+(?:[A-Z0-9\s_-]+)?PRIVATE\s+KEY-----[\s\S]+?-----END\s+(?:[A-Z0-9\s_-]+)?PRIVATE\s+KEY-----",
            re.MULTILINE,
        ),
    ),
    # AWS Access Keys & Secrets
    ("AWS_ACCESS_KEY", re.compile(r"\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b")),
    ("AWS_SECRET_KEY", re.compile(r"(aws_secret_access_key\s*[:=]\s*)[a-zA-Z0-9/+=]{40}", re.IGNORECASE)),
    # Google API Keys
    ("GOOGLE_API_KEY", re.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    # Slack Tokens
    ("SLACK_TOKEN", re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}")),
    # Stripe Keys
    ("STRIPE_KEY", re.compile(r"\b(?:sk|pk)_(?:test|live)_[0-9a-zA-Z]{24,}\b")),
    # Database Connection Strings with Passwords
    (
        "DB_URI",
        re.compile(
            r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|mssql)://(?:\w+):([^@\s/:]+)@",
            re.IGNORECASE,
        ),
    ),
    # Generic Password / Secret Key Value Assignment
    (
        "KEY_VALUE_SECRET",
        re.compile(
            r"(?:password|passwd|secret|api_key|apikey|access_token|client_secret|auth_token)\s*[:=]\s*['\"]([^'\"\s]{8,})['\"]",
            re.IGNORECASE,
        ),
    ),
]


def redact_secrets(text: str) -> str:
    """Sanitize text by replacing all detected secrets with redaction labels."""
    if not text:
        return ""

    sanitized = text

    # Handle Database URIs separately to keep protocol and host
    for label, pattern in SECRET_PATTERNS:
        if label == "DB_URI":
            sanitized = pattern.sub(
                lambda m: m.group(0).replace(m.group(1), "[REDACTED_PASSWORD]"),
                sanitized,
            )
        elif label == "KEY_VALUE_SECRET":
            sanitized = pattern.sub(
                lambda m: m.group(0).replace(m.group(1), f"[REDACTED_{label}]"),
                sanitized,
            )
        elif label == "BEARER_TOKEN":
            sanitized = pattern.sub(r"\1[REDACTED_BEARER_TOKEN]", sanitized)
        else:
            sanitized = pattern.sub(f"[REDACTED_{label}]", sanitized)

    return sanitized


def contains_secrets(text: str) -> bool:
    """Check if text contains any recognized secrets."""
    if not text:
        return False

    for _, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            return True
    return False


def scan_diff_for_secrets(diff_text: str) -> List[Tuple[str, str]]:
    """Scan added lines in a git diff for secrets.

    Returns a list of (secret_type, matched_line_summary).
    """
    findings: List[Tuple[str, str]] = []
    if not diff_text:
        return findings

    for line in diff_text.splitlines():
        # Only inspect added lines in diffs
        if line.startswith("+") and not line.startswith("+++"):
            added_content = line[1:].strip()
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(added_content):
                    redacted_preview = redact_secrets(added_content)[:80]
                    findings.append((label, redacted_preview))
                    break

    return findings
