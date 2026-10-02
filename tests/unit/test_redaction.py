"""Unit tests for centralized secret redaction and diff scanning."""

import pytest
from tenjin.security.redaction import contains_secrets, redact_secrets, scan_diff_for_secrets


def test_redact_github_tokens():
    text = "Found secret: ghp_1234567890abcdef1234567890abcdef1234 in file."
    redacted = redact_secrets(text)
    assert "ghp_" not in redacted
    assert "[REDACTED_GITHUB_TOKEN]" in redacted


def test_redact_github_fine_grained_pat():
    text = "Access via github_pat_11AABCDEF01234567890_abcdefghijklmnopqrstuvwxyz1234567890"
    redacted = redact_secrets(text)
    assert "github_pat_" not in redacted
    assert "[REDACTED_GITHUB_PAT]" in redacted


def test_redact_bearer_token():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test"
    redacted = redact_secrets(text)
    assert "eyJhbGciOi" not in redacted
    assert "[REDACTED_BEARER_TOKEN]" in redacted


def test_redact_private_key():
    key = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y3yZ...
-----END RSA PRIVATE KEY-----"""
    redacted = redact_secrets(key)
    assert "MIIEowIBAAKCAQEA" not in redacted
    assert "[REDACTED_PRIVATE_KEY]" in redacted


def test_redact_database_uri_password():
    uri = "Connecting to postgresql://admin:SuperSecretPassword123!@localhost:5432/production"
    redacted = redact_secrets(uri)
    assert "SuperSecretPassword123!" not in redacted
    assert "[REDACTED_PASSWORD]" in redacted
    assert "admin" in redacted
    assert "localhost:5432" in redacted


def test_contains_secrets():
    assert contains_secrets("My token is gho_abcdefghijklmnopqrstuvwxyz123456") is True
    assert contains_secrets("Clean message without secrets") is False


def test_scan_diff_for_secrets():
    diff = """--- a/config.py
+++ b/config.py
@@ -1,3 +1,4 @@
 def get_auth():
+    token = "ghp_1234567890abcdef1234567890abcdef1234"
     return token
"""
    findings = scan_diff_for_secrets(diff)
    assert len(findings) == 1
    assert findings[0][0] == "GITHUB_TOKEN"
    assert "ghp_" not in findings[0][1]
