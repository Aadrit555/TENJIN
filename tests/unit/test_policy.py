"""Unit tests for policy resolution and autofix permissions."""

import tempfile
from pathlib import Path

from tenjin.core.config import TenjinConfig
from tenjin.core.constants import AutonomyLevel, FindingSeverity, RiskLevel
from tenjin.memory.models import FindingRecord
from tenjin.policies.policy import can_autofix_finding, resolve_effective_policy


def test_global_policy_caps_repository_autonomy():
    global_cfg = TenjinConfig()
    global_cfg.safety.autonomy_level = AutonomyLevel.LEVEL_1_AUDIT_REPORT

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        tenjin_dir = tmp_path / ".tenjin"
        tenjin_dir.mkdir()
        # Repo attempts to grant itself LEVEL 5 (Pull Request)
        (tenjin_dir / "policy.yaml").write_text("autonomy_level: 5\nauto_pr: true")

        effective = resolve_effective_policy(global_cfg, tmp_path)
        # Global LEVEL 1 strictly caps repository level
        assert effective.autonomy_level == AutonomyLevel.LEVEL_1_AUDIT_REPORT
        assert effective.auto_pr is False


def test_autofix_blocked_for_high_risk():
    global_cfg = TenjinConfig()
    global_cfg.safety.autonomy_level = AutonomyLevel.LEVEL_3_COMMIT_BRANCH
    global_cfg.safety.require_human_approval_for_high_risk = True

    effective = resolve_effective_policy(global_cfg, Path.cwd())

    finding = FindingRecord(
        id="f1",
        repository="owner/repo",
        run_id="run_1",
        category="security",
        subcategory="auth_bypass",
        severity=FindingSeverity.HIGH,
        confidence=0.9,
        title="High risk finding",
        summary="Summary",
        evidence="Evidence",
        risk=RiskLevel.HIGH,
        autofix_eligibility=True,
        fingerprint="fp1",
    )

    allowed, reason = can_autofix_finding(finding, effective)
    assert allowed is False
    assert "human approval" in reason


def test_unmanaged_repository_blocks_mutations():
    global_cfg = TenjinConfig()
    global_cfg.safety.autonomy_level = AutonomyLevel.LEVEL_5_PULL_REQUEST
    global_cfg.managed_repositories = ["Aadrit555/Mimiq2", "Aadrit555/Little-Garden"]

    effective = resolve_effective_policy(
        global_cfg, Path.cwd(), repo_name_or_url="SomeOtherUser/UntrustedRepo"
    )
    assert effective.is_managed is False
    assert effective.autonomous_fixes is False
    assert effective.auto_commit is False
    assert effective.auto_push is False
    assert effective.auto_pr is False
    assert effective.autonomy_level <= AutonomyLevel.LEVEL_1_AUDIT_REPORT
    assert "not in the managed allowlist" in (effective.block_reason or "")


def test_antigravity_account_mismatch_blocks_mutations():
    global_cfg = TenjinConfig()
    global_cfg.safety.autonomy_level = AutonomyLevel.LEVEL_5_PULL_REQUEST
    global_cfg.antigravity_expected_account = "jhonbailey456@gmail.com"

    effective = resolve_effective_policy(
        global_cfg,
        Path.cwd(),
        repo_name_or_url="Aadrit555/Mimiq2",
        active_antigravity_account="wrong_account@gmail.com",
    )
    assert effective.antigravity_account_authorized is False
    assert effective.autonomous_fixes is False
    assert effective.auto_commit is False
    assert "account mismatch" in (effective.block_reason or "").lower()
