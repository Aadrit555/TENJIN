"""Unit tests for independent verification engine, deletion guard, and diff freeze."""

import tempfile
from pathlib import Path

from tenjin.audit.engine import AuditEngine
from tenjin.core.capabilities import discover_capabilities
from tenjin.core.constants import AutonomyLevel, FindingSeverity, RiskLevel
from tenjin.memory.database import Database
from tenjin.memory.models import BaselineManifestRecord, FindingRecord, RepositoryRecord, RunRecord
from tenjin.policies.policy import EffectivePolicy
from tenjin.repositories.project_detection import ProjectProfile
from tenjin.verification.engine import VerificationEngine


def test_verification_diff_freeze_and_scope():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.upsert_repository(RepositoryRecord(
            full_name="Aadrit555/Mimiq2",
            owner="Aadrit555",
            name="Mimiq2",
            url="https://github.com/Aadrit555/Mimiq2",
            default_branch="main",
            clone_url="https://github.com/Aadrit555/Mimiq2.git",
            ssh_url="git@github.com:Aadrit555/Mimiq2.git",
            is_managed=True,
        ))
        db.create_run(RunRecord(
            run_id="run-1",
            repository="Aadrit555/Mimiq2",
        ))

        caps = discover_capabilities()
        audit_engine = AuditEngine(caps)
        engine = VerificationEngine(caps, audit_engine, db)

        # Baseline finding
        finding = FindingRecord(
            id="find-01",
            repository="Aadrit555/Mimiq2",
            run_id="run-1",
            category="quality",
            subcategory="syntax",
            severity=FindingSeverity.LOW,
            confidence=0.9,
            title="Syntax issue",
            summary="Syntax warning",
            evidence="evidence",
            risk=RiskLevel.LOW,
            autofix_eligibility=True,
            fingerprint="fp-01",
        )

        policy = EffectivePolicy(
            autonomy_level=AutonomyLevel.LEVEL_3_COMMIT_BRANCH,
            autonomous_fixes=True,
            auto_commit=True,
            auto_push=False,
            auto_pr=False,
            auto_merge=False,
            allowed_severities=["low", "medium", "high"],
            protected_paths=[".github/workflows/**"],
            excluded_paths=[],
            require_approval_for_high_risk=False,
            max_files=10,
            max_lines=500,
        )

        profile = ProjectProfile(
            ecosystem="python",
            languages=["python"],
        )

        # 1. Scope violation: touching protected path
        res = engine.verify_repair(
            repository_name="Aadrit555/Mimiq2",
            workspace_path=tmp_path,
            finding=finding,
            run_id="run-1",
            changed_files=[".github/workflows/deploy.yml"],
            diff_text="+ test",
            policy=policy,
            project_profile=profile,
            baseline_findings=[finding],
        )
        assert res.diff_valid is False
        assert res.passed is False
        assert any("protected path" in f for f in res.failures)

        # 2. Secret violation
        res_secret = engine.verify_repair(
            repository_name="Aadrit555/Mimiq2",
            workspace_path=tmp_path,
            finding=finding,
            run_id="run-1",
            changed_files=["src/auth.py"],
            diff_text="+ secret_key = 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'",
            policy=policy,
            project_profile=profile,
            baseline_findings=[finding],
        )
        assert res_secret.secrets_clean is False
        assert res_secret.passed is False


def test_verification_deletion_guard_integration():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.upsert_repository(RepositoryRecord(
            full_name="Aadrit555/Mimiq2",
            owner="Aadrit555",
            name="Mimiq2",
            url="https://github.com/Aadrit555/Mimiq2",
            default_branch="main",
            clone_url="https://github.com/Aadrit555/Mimiq2.git",
            ssh_url="git@github.com:Aadrit555/Mimiq2.git",
            is_managed=True,
        ))
        db.create_run(RunRecord(
            run_id="run-dg",
            repository="Aadrit555/Mimiq2",
        ))

        caps = discover_capabilities()
        audit_engine = AuditEngine(caps)
        engine = VerificationEngine(caps, audit_engine, db)

        # Create a tracked file in baseline
        manifest = BaselineManifestRecord(
            run_id="run-dg",
            repository="Aadrit555/Mimiq2",
            base_sha="HEAD",
            tracked_files=["important_file.py"],
            file_hashes={"important_file.py": "abc123hash"},
        )
        # The file does not exist on disk, simulating agent deleting it!
        policy = EffectivePolicy(
            autonomy_level=AutonomyLevel.LEVEL_3_COMMIT_BRANCH,
            autonomous_fixes=True,
            auto_commit=True,
            auto_push=False,
            auto_pr=False,
            auto_merge=False,
            allowed_severities=["low"],
            protected_paths=[],
            excluded_paths=[],
            require_approval_for_high_risk=False,
            max_files=10,
            max_lines=500,
        )
        profile = ProjectProfile(
            ecosystem="python",
            languages=["python"],
        )

        res = engine.verify_repair(
            repository_name="Aadrit555/Mimiq2",
            workspace_path=tmp_path,
            finding=None,
            run_id="run-dg",
            changed_files=["src/app.py"],
            diff_text="+ fixed",
            policy=policy,
            project_profile=profile,
            baseline_manifest=manifest,
        )
        assert res.deletion_guard_passed is False
        assert res.passed is False
        assert any("Deletion Guard violation" in f for f in res.failures)
