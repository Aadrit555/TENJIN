"""TENJIN Independent Verification Engine.

Crucial architecture property: Antigravity cannot be its own verifier.
This engine independently verifies that agent changes respect file scope, introduce no
new secrets, pass tests and linters, compile successfully, preserve existing tracked files
(Deletion Guard), freeze the diff hash before commit, and actually resolve the audit findings.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tenjin.audit.engine import AuditEngine
from tenjin.core.capabilities import CapabilityInventory
from tenjin.core.constants import FindingResolution, FindingSeverity
from tenjin.memory.database import Database
from tenjin.memory.models import (
    BaselineManifestRecord,
    DiffFreezeRecord,
    FindingRecord,
)
from tenjin.policies.policy import EffectivePolicy
from tenjin.repositories.project_detection import ProjectProfile
from tenjin.security.deletion_guard import DeletionGuard
from tenjin.security.isolation import get_sanitized_environment
from tenjin.security.redaction import redact_secrets, scan_diff_for_secrets

logger = logging.getLogger("tenjin.verification")


@dataclass
class VerificationResult:
    """Consolidated outcome of the independent verification pipeline."""
    passed: bool
    diff_valid: bool
    secrets_clean: bool
    tests_passed: bool
    lint_passed: bool
    types_passed: bool
    security_passed: bool
    re_audit_passed: bool
    deletion_guard_passed: bool = True
    diff_freeze_hash: Optional[str] = None
    diff_freeze_verified: bool = True
    resolved_findings: List[str] = field(default_factory=list)
    unchanged_findings: List[str] = field(default_factory=list)
    new_findings: List[str] = field(default_factory=list)
    failures: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class VerificationEngine:
    """Executes non-simulated independent verification of repository modifications."""

    def __init__(
        self,
        capabilities: CapabilityInventory,
        audit_engine: AuditEngine,
        db: Optional[Database] = None,
    ):
        self.capabilities = capabilities
        self.audit_engine = audit_engine
        self.db = db

    def compute_diff_hash(self, workspace_path: Path) -> str:
        """Compute the SHA-256 fingerprint of the current workspace Git diff."""
        git_path = self.capabilities.git_path or "git"
        try:
            res = subprocess.run(
                [git_path, "diff", "HEAD"],
                cwd=str(workspace_path),
                capture_output=True,
                text=True,
                timeout=30.0,
            )
            raw_diff = res.stdout if res.returncode == 0 else ""
            return hashlib.sha256(raw_diff.encode("utf-8")).hexdigest()
        except Exception as e:
            logger.error("Failed to compute diff hash in %s: %s", workspace_path, e)
            return ""

    def verify_repair(
        self,
        repository_name: str,
        workspace_path: Path,
        finding: Optional[FindingRecord],
        run_id: str,
        changed_files: List[str],
        diff_text: str,
        policy: EffectivePolicy,
        project_profile: ProjectProfile,
        baseline_manifest: Optional[BaselineManifestRecord] = None,
        baseline_findings: Optional[List[FindingRecord]] = None,
        targeted_finding_ids: Optional[List[str]] = None,
    ) -> VerificationResult:
        """Run complete independent verification pipeline on modified workspace."""
        failures: List[str] = []
        details: Dict[str, Any] = {}

        # 0. Enforce Deletion Guard
        deletion_guard_passed = True
        if self.db and baseline_manifest:
            guard = DeletionGuard(git_path=self.capabilities.git_path or "git")
            no_deletions = guard.enforce_and_restore(
                repo_path=workspace_path,
                baseline=baseline_manifest,
                run_id=run_id,
                db=self.db,
            )
            if not no_deletions:
                deletion_guard_passed = False
                failures.append(
                    "Deletion Guard violation: agent attempted permanent deletion of existing tracked files; files were restored from baseline."
                )
        details["deletion_guard_passed"] = deletion_guard_passed

        # 1. Diff Validity & Scope Check
        diff_valid = True
        if not changed_files or not diff_text.strip():
            diff_valid = False
            failures.append("No actual file modifications detected in git diff.")

        # Check maximum file count limit
        if len(changed_files) > policy.max_files:
            diff_valid = False
            failures.append(
                f"Scope violation: modified {len(changed_files)} files (maximum allowed is {policy.max_files})."
            )

        # Check for protected paths
        for f in changed_files:
            norm_f = f.replace("\\", "/")
            for prot in policy.protected_paths:
                if Path(norm_f).match(prot):
                    diff_valid = False
                    failures.append(f"Scope violation: touched protected path '{f}'.")

        details["diff_valid"] = diff_valid

        # 2. Secret Scan on Diff
        detected_secrets = scan_diff_for_secrets(diff_text)
        secrets_clean = len(detected_secrets) == 0
        if not secrets_clean:
            for sec_type, preview in detected_secrets:
                failures.append(f"Security violation: diff introduces potential secret '{sec_type}': {preview}")
        details["secrets_clean"] = secrets_clean

        # 3. Execute Relevant Linters
        lint_passed = True
        for cmd in project_profile.lint_commands:
            code, out, err = self._run_command(cmd, workspace_path)
            if code != 0:
                lint_passed = False
                failures.append(f"Linter check failed ({' '.join(cmd)}): {redact_secrets(err or out)[:200]}")
        details["lint_passed"] = lint_passed

        # 4. Execute Type Checks
        types_passed = True
        for cmd in project_profile.type_check_commands:
            code, out, err = self._run_command(cmd, workspace_path)
            if code != 0:
                types_passed = False
                failures.append(f"Type check failed ({' '.join(cmd)}): {redact_secrets(err or out)[:200]}")
        details["types_passed"] = types_passed

        # 5. Execute Project Tests
        tests_passed = True
        for cmd in project_profile.test_commands:
            code, out, err = self._run_command(cmd, workspace_path)
            if code != 0:
                tests_passed = False
                failures.append(f"Test suite failed ({' '.join(cmd)}): {redact_secrets(err or out)[:200]}")
        details["tests_passed"] = tests_passed

        # 6. Post-Audit & Baseline Finding Resolution Comparison
        re_audit_passed = True
        post_audit_findings = self.audit_engine.run_audit(
            repository_name=repository_name,
            workspace_path=workspace_path,
            run_id=f"re_audit_{run_id}",
        )

        resolved_ids: List[str] = []
        unchanged_ids: List[str] = []
        new_ids: List[str] = []

        target_ids = set(targeted_finding_ids or ([finding.id] if finding else []))
        baseline_fps = {f.fingerprint: f for f in (baseline_findings or ([finding] if finding else []))}
        post_fps = {f.fingerprint: f for f in post_audit_findings}

        # Check resolution of targeted baseline findings
        for fp, bf in baseline_fps.items():
            if bf.id in target_ids or not target_ids:
                if fp in post_fps:
                    unchanged_ids.append(bf.id)
                else:
                    resolved_ids.append(bf.id)

        # Check for new findings introduced by the fix
        for fp, pf in post_fps.items():
            if fp not in baseline_fps:
                new_ids.append(pf.id)
                # Fail if new finding is critical or high
                if pf.severity in [FindingSeverity.CRITICAL, FindingSeverity.HIGH]:
                    re_audit_passed = False
                    failures.append(
                        f"Regression: change introduced new {pf.severity.value} finding '{pf.title}' in {pf.file or 'workspace'}."
                    )

        # If we had targeted findings and none were resolved, verification fails
        if target_ids and not resolved_ids and unchanged_ids:
            re_audit_passed = False
            failures.append("Post-fix re-audit indicates target finding(s) remain unresolved.")

        details["re_audit_passed"] = re_audit_passed
        details["resolved_count"] = len(resolved_ids)
        details["unchanged_count"] = len(unchanged_ids)
        details["new_count"] = len(new_ids)

        # 7. Final Diff Freeze immediately before staging
        diff_freeze_hash = self.compute_diff_hash(workspace_path)
        diff_freeze_verified = bool(diff_freeze_hash)
        if self.db and diff_freeze_hash:
            freeze_record = DiffFreezeRecord(
                run_id=run_id,
                repository=repository_name,
                verified_diff_hash=diff_freeze_hash,
                pre_commit_diff_hash=diff_freeze_hash,
                is_match=True,
            )
            try:
                self.db.record_diff_freeze(freeze_record)
            except Exception as e:
                logger.error("Failed to record diff freeze: %s", e)

        overall_passed = (
            deletion_guard_passed
            and diff_valid
            and secrets_clean
            and lint_passed
            and types_passed
            and tests_passed
            and re_audit_passed
            and diff_freeze_verified
        )

        return VerificationResult(
            passed=overall_passed,
            diff_valid=diff_valid,
            secrets_clean=secrets_clean,
            tests_passed=tests_passed,
            lint_passed=lint_passed,
            types_passed=types_passed,
            security_passed=secrets_clean,
            re_audit_passed=re_audit_passed,
            deletion_guard_passed=deletion_guard_passed,
            diff_freeze_hash=diff_freeze_hash,
            diff_freeze_verified=diff_freeze_verified,
            resolved_findings=resolved_ids,
            unchanged_findings=unchanged_ids,
            new_findings=new_ids,
            failures=failures,
            details=details,
        )

    def _run_command(self, cmd: List[str], cwd: Path, timeout: float = 180.0) -> Tuple[int, str, str]:
        """Safely execute a verification command within the isolated workspace."""
        try:
            env = get_sanitized_environment()
            res = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout} seconds"
        except Exception as e:
            return -1, "", str(e)
