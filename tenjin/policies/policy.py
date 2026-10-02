"""TENJIN Hierarchical Policy Engine.

Enforces policy inheritance: Global Safety Policy strictly supersedes local
repository `.tenjin/policy.yaml` policies. Local repositories can restrict permissions,
but can NEVER elevate autonomy above global configuration boundaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import yaml

from tenjin.core.config import TenjinConfig
from tenjin.core.constants import AutonomyLevel, RiskLevel
from tenjin.memory.models import FindingRecord

logger = logging.getLogger("tenjin.policies")


@dataclass
class EffectivePolicy:
    """Resolved permissions and boundaries for repository operations."""
    autonomy_level: AutonomyLevel
    autonomous_fixes: bool
    auto_commit: bool
    auto_push: bool
    auto_pr: bool
    auto_merge: bool
    allowed_severities: List[str]
    protected_paths: List[str]
    excluded_paths: List[str]
    require_approval_for_high_risk: bool
    max_files: int
    max_lines: int
    allow_major_revamps: bool = True
    is_managed: bool = True
    antigravity_account_authorized: bool = True
    block_reason: Optional[str] = None


def normalize_repo_name(name_or_url: str) -> str:
    """Normalize a GitHub repository full name or URL to owner/repo format."""
    s = name_or_url.strip()
    if s.endswith(".git"):
        s = s[:-4]
    if "github.com/" in s:
        s = s.split("github.com/")[-1]
    return s.strip("/")


def is_repository_managed(name_or_url: str, managed_repos: List[str]) -> bool:
    """Check if repository matches any entry in the managed allowlist."""
    norm = normalize_repo_name(name_or_url).lower()
    for m in managed_repos:
        if norm == normalize_repo_name(m).lower():
            return True
    return False


def load_repository_policy(repo_path: Path) -> dict:
    """Read repository-specific policy file if present."""
    candidates = [
        repo_path / ".tenjin" / "policy.yaml",
        repo_path / ".tenjin" / "policy.yml",
        repo_path / ".forge" / "policy.yaml",
    ]
    for c in candidates:
        if c.is_file():
            try:
                data = yaml.safe_load(c.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.warning("Failed to parse repository policy file %s: %s", c, e)
    return {}


def resolve_effective_policy(
    global_cfg: TenjinConfig,
    repo_path: Path,
    repo_name_or_url: Optional[str] = None,
    active_antigravity_account: Optional[str] = None,
) -> EffectivePolicy:
    """Resolve effective policy, guaranteeing global boundaries cannot be relaxed by repo."""
    repo_policy = load_repository_policy(repo_path)
    global_safety = global_cfg.safety

    # Autonomy level capped by global config
    global_level = global_safety.autonomy_level
    repo_level = repo_policy.get("autonomy_level")
    if repo_level is not None:
        try:
            parsed_repo_level = AutonomyLevel(int(repo_level))
            effective_level = min(global_level, parsed_repo_level)
        except Exception:
            effective_level = global_level
    else:
        effective_level = global_level

    # Check managed status if repository identifier provided
    is_managed = True
    block_reason: Optional[str] = None
    if repo_name_or_url:
        is_managed = is_repository_managed(repo_name_or_url, global_cfg.managed_repositories)
        if not is_managed:
            effective_level = min(effective_level, AutonomyLevel.LEVEL_1_AUDIT_REPORT)
            block_reason = f"Repository '{repo_name_or_url}' is not in the managed allowlist (fail-closed)"

    # Check Antigravity account authorization
    account_authorized = True
    if active_antigravity_account is not None:
        expected = global_cfg.antigravity_expected_account.strip().lower()
        active = active_antigravity_account.strip().lower()
        if active != expected:
            account_authorized = False
            effective_level = min(effective_level, AutonomyLevel.LEVEL_1_AUDIT_REPORT)
            block_reason = f"Antigravity account mismatch: active is '{active_antigravity_account}', expected '{global_cfg.antigravity_expected_account}'"

    # Autonomous fixes allowed only if level >= 2 and not blocked
    can_mutate = is_managed and account_authorized
    auto_fixes = (
        can_mutate
        and effective_level >= AutonomyLevel.LEVEL_2_PROPOSE_REPAIRS
        and repo_policy.get("autonomous_fixes", True)
    )
    # Commit allowed only if level >= 3
    auto_commit = (
        can_mutate
        and effective_level >= AutonomyLevel.LEVEL_3_COMMIT_BRANCH
        and repo_policy.get("auto_commit", True)
    )
    # Push allowed only if level >= 4 and global config allows auto_push
    auto_push = (
        can_mutate
        and effective_level >= AutonomyLevel.LEVEL_4_PUSH_BRANCH
        and global_safety.auto_push_branch
        and repo_policy.get("auto_push", False)
    )
    # PR allowed only if level >= 5 and global config allows auto_pr
    auto_pr = (
        can_mutate
        and effective_level >= AutonomyLevel.LEVEL_5_PULL_REQUEST
        and global_safety.auto_create_pr
        and repo_policy.get("auto_pr", False)
    )
    # Merge allowed only if level >= 6 and global allows auto_merge
    auto_merge = (
        can_mutate
        and effective_level >= AutonomyLevel.LEVEL_6_AUTO_MERGE
        and global_safety.auto_merge
        and repo_policy.get("auto_merge", False)
    )

    # Union of protected paths (repositories can add more, cannot remove global ones)
    protected = list(
        set(global_safety.protected_paths + repo_policy.get("protected_paths", []))
    )
    excluded = list(
        set(global_safety.excluded_paths + repo_policy.get("excluded_paths", []))
    )

    allowed_sevs = [
        s
        for s in global_safety.allowed_severities_for_autofix
        if s in repo_policy.get("allowed_severities", global_safety.allowed_severities_for_autofix)
    ]

    return EffectivePolicy(
        autonomy_level=effective_level,
        autonomous_fixes=auto_fixes,
        auto_commit=auto_commit,
        auto_push=auto_push,
        auto_pr=auto_pr,
        auto_merge=auto_merge,
        allowed_severities=allowed_sevs,
        protected_paths=protected,
        excluded_paths=excluded,
        require_approval_for_high_risk=global_safety.require_human_approval_for_high_risk,
        max_files=global_safety.max_files_changed_for_autofix,
        max_lines=global_safety.max_lines_changed_for_autofix,
        allow_major_revamps=global_safety.allow_major_revamps,
        is_managed=is_managed,
        antigravity_account_authorized=account_authorized,
        block_reason=block_reason,
    )


def can_autofix_finding(finding: FindingRecord, policy: EffectivePolicy) -> Tuple[bool, str]:
    """Determine whether an individual finding is eligible for autonomous repair under policy."""
    if policy.block_reason and not policy.autonomous_fixes:
        return False, policy.block_reason

    if not policy.autonomous_fixes:
        return False, "Autonomous repairs are disabled by effective policy"

    if not policy.is_managed:
        return False, "Repository is not in the managed allowlist"

    if not policy.antigravity_account_authorized:
        return False, "Antigravity account is unauthorized or unauthenticated"

    if finding.risk in [RiskLevel.HIGH, RiskLevel.CRITICAL] and policy.require_approval_for_high_risk:
        return False, f"Finding has {finding.risk.value} risk requiring human approval"

    if finding.severity.value not in policy.allowed_severities:
        return False, f"Severity {finding.severity.value} is not in allowed autofix severities"

    if not finding.autofix_eligibility:
        return False, "Finding was marked ineligible for autonomous repair by audit engine"

    return True, "Eligible for autonomous repair"
