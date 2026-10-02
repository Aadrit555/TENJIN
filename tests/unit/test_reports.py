"""Unit tests for JSON and Markdown report generation with secret redaction."""

import json
import tempfile
from pathlib import Path
import pytest

from tenjin.core.constants import FindingSeverity, FindingSource, FindingStatus, RiskLevel, State
from tenjin.memory.models import FindingRecord, GitActionRecord, RunRecord, VerificationRunRecord
from tenjin.reporting.report_generator import generate_json_report, generate_markdown_report


def test_reports_redact_secrets_in_json_and_markdown():
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)

        run = RunRecord(
            run_id="run_report_01",
            repository="owner/repo",
            base_sha="abcdef1234567890",
            state=State.COMPLETED,
            duration_seconds=12.5,
        )

        secret_token = "ghp_1234567890abcdef1234567890abcdef1234"
        finding = FindingRecord(
            id="find_01",
            repository="owner/repo",
            run_id="run_report_01",
            category="security",
            subcategory="exposed_token",
            severity=FindingSeverity.CRITICAL,
            confidence=1.0,
            title="Exposed token",
            summary=f"Found {secret_token}",
            evidence=f"API token: {secret_token}",
            risk=RiskLevel.CRITICAL,
            fingerprint="fp01",
        )

        json_path = generate_json_report(run, [finding], [], [], out_dir)
        md_path = generate_markdown_report(run, [finding], [], [], out_dir)

        json_content = json_path.read_text(encoding="utf-8")
        md_content = md_path.read_text(encoding="utf-8")

        # Secret must not appear in either file
        assert secret_token not in json_content
        assert "[REDACTED_GITHUB_TOKEN]" in json_content

        assert secret_token not in md_content
        assert "[REDACTED_GITHUB_TOKEN]" in md_content
