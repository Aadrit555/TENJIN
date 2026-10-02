"""TENJIN Independent Verification Engine.

Crucial architecture property: Antigravity cannot be its own verifier.
This engine independently verifies that agent changes respect file scope, introduce no
new secrets, pass tests and linters, compile successfully, and actually resolve the audit finding.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from tenjin.audit.engine import AuditEngine
from tenjin.core.capabilities import CapabilityInventory
from tenjin.memory.models import FindingRecord
from tenjin.policies.policy import EffectivePolicy
from tenjin.repositories.project_detection import ProjectProfile
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
    failures: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


class VerificationEngine:
    """Executes non-simulated independent verification of repository modifications."""

    def __init__(self, capabilities: CapabilityInventory, audit_engine: AuditEngine):
        self.capabilities = capabilities
        self.audit_engine = audit_engine

    def verify_repair(
        self,
        repository_name: str,
        workspace_path: Path,
        finding: FindingRecord,
        run_id: str,
        changed_files: List[str],
        diff_text: str,
        policy: EffectivePolicy,
        project_profile: ProjectProfile,
    ) -> VerificationResult:
        """Run complete independent verification pipeline on modified workspace."""
        failures: List[str] = []
        details: Dict[str, Any] = {}

        # 1. Diff Validity & Scope Check
        diff_valid = True
        if not changed_files or not diff_text.strip():
            diff_valid = False
            failures.append("No actual file modifications detected in git diff.")

        # Check maximum file count limit
        if len(changed_files) > policy.max_files:
            diff_valid = False
            failures.append(f"Scope violation: modified {len(changed_files)} files (maximum allowed is {policy.max_files}).")

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

        # 6. Re-audit Changed Area to Confirm Finding Resolved
        re_audit_passed = True
        post_audit_findings = self.audit_engine.run_audit(
            repository_name=repository_name,
            workspace_path=workspace_path,
            run_id=f"re_audit_{run_id}",
        )

        # Check if the original finding fingerprint is still present
        still_present = any(pf.fingerprint == finding.fingerprint for pf in post_audit_findings)
        if still_present:
            re_audit_passed = False
            failures.append("Post-fix re-audit indicates the original finding remains unresolved.")

        # Check if new critical/high findings were introduced (regression)
        new_critical_or_high = [
            pf for pf in post_audit_findings if pf.severity.value in ["critical", "high"] and pf.fingerprint != finding.fingerprint
        ]
        if new_critical_or_high:
            re_audit_passed = False
            failures.append(f"Regression detected: change introduced {len(new_critical_or_high)} new high/critical findings.")

        details["re_audit_passed"] = re_audit_passed

        overall_passed = (
            diff_valid
            and secrets_clean
            and lint_passed
            and types_passed
            and tests_passed
            and re_audit_passed
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
            failures=failures,
            details=details,
        )

    def _run_command(self, cmd: List[str], cwd: Path, timeout: float = 180.0) -> tuple[int, str, str]:
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
