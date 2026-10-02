"""Unit tests for change risk engine."""

import pytest
from tenjin.core.constants import RiskLevel
from tenjin.policies.risk import evaluate_change_risk


def test_risk_critical_on_credentials_path():
    files = ["src/app.py", "credentials/service_account.json"]
    diff = "+ test"
    risk = evaluate_change_risk(files, diff)
    assert risk == RiskLevel.CRITICAL


def test_risk_high_on_auth_directory():
    files = ["app/auth/handler.py"]
    diff = "+ change"
    risk = evaluate_change_risk(files, diff, baseline_risk=RiskLevel.LOW)
    assert risk == RiskLevel.HIGH


def test_risk_high_on_large_diff():
    files = ["src/utils.py"]
    # 400 lines added
    diff = "\n".join([f"+ line {i}" for i in range(400)])
    risk = evaluate_change_risk(files, diff, baseline_risk=RiskLevel.LOW, max_lines_threshold=100)
    assert risk == RiskLevel.HIGH


def test_risk_trivial_for_minor_fix():
    files = ["docs/README.md"]
    diff = "+ updated docs"
    risk = evaluate_change_risk(files, diff, baseline_risk=RiskLevel.TRIVIAL)
    assert risk == RiskLevel.TRIVIAL
