"""TENJIN Persistent Domain Models.

Strongly-typed Pydantic domain models for repositories, audit runs,
finding history, state transitions, agent executions, Git actions, and health tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from tenjin.core.constants import (
    AutonomyLevel,
    DeferredStatus,
    FindingResolution,
    FindingSeverity,
    FindingSource,
    FindingStatus,
    MissionType,
    RiskLevel,
    State,
    WorkClassification,
)


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class RepositoryRecord(BaseModel):
    """Metadata and tracking record for a managed GitHub repository."""
    full_name: str = Field(description="owner/repo format")
    owner: str
    name: str
    url: str
    clone_url: str
    default_branch: str = "main"
    is_managed: bool = False
    is_private: bool = False
    is_fork: bool = False
    is_archived: bool = False
    language: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pushed_at: Optional[str] = None
    permissions: Dict[str, bool] = Field(default_factory=dict)
    last_audit_at: Optional[str] = None
    health_score: float = 100.0
    status: str = "active"


class StateTransitionRecord(BaseModel):
    """Record of an explicit lifecycle state transition."""
    id: Optional[int] = None
    run_id: str
    repository: str
    from_state: State
    to_state: State
    reason: str
    timestamp: str = Field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FindingRecord(BaseModel):
    """Detailed evidence-backed finding produced by the audit engine."""
    id: str
    repository: str
    run_id: str
    category: str
    subcategory: str
    severity: FindingSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    summary: str
    evidence: str
    file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    affected_component: Optional[str] = None
    risk: RiskLevel = RiskLevel.LOW
    suggested_fix: Optional[str] = None
    required_tests: List[str] = Field(default_factory=list)
    autofix_eligibility: bool = False
    source: FindingSource = FindingSource.DETERMINISTIC
    fingerprint: str
    detected_at: str = Field(default_factory=utc_now_iso)
    status: FindingStatus = FindingStatus.OPEN


class FindingHistoryRecord(BaseModel):
    """Historical audit events for a finding fingerprint."""
    id: Optional[int] = None
    fingerprint: str
    repository: str
    run_id: str
    action: str
    timestamp: str = Field(default_factory=utc_now_iso)
    details: Dict[str, Any] = Field(default_factory=dict)


class SelectionDecisionRecord(BaseModel):
    """Structured rationale for selecting a repository in an autonomous run."""
    id: Optional[int] = None
    run_id: str
    repository: str
    score: float
    stale_audit_score: float
    activity_score: float
    unresolved_findings_score: float
    exploration_score: float
    factors: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now_iso)


class RunRecord(BaseModel):
    """Top-level record of an autonomous engineering audit/repair run."""
    run_id: str
    repository: str
    base_sha: Optional[str] = None
    head_sha: Optional[str] = None
    state: State = State.DISCOVERING
    started_at: str = Field(default_factory=utc_now_iso)
    ended_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    autonomy_level: AutonomyLevel = AutonomyLevel.LEVEL_1_AUDIT_REPORT
    selection_rationale: Optional[str] = None
    findings_count: int = 0
    fixed_count: int = 0
    error_message: Optional[str] = None


class AgentExecutionRecord(BaseModel):
    """Record of an Antigravity agent invocation."""
    id: Optional[int] = None
    run_id: str
    finding_id: str
    agent_interface: str
    model_name: Optional[str] = None
    prompt: str
    raw_output: str
    parsed_output: Dict[str, Any] = Field(default_factory=dict)
    status: str
    duration_seconds: float = 0.0
    timestamp: str = Field(default_factory=utc_now_iso)


class VerificationRunRecord(BaseModel):
    """Independent verification test and security results."""
    id: Optional[int] = None
    run_id: str
    finding_id: str
    passed: bool
    diff_valid: bool
    secrets_detected: bool
    tests_passed: bool
    lint_passed: bool
    types_passed: bool
    security_passed: bool
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now_iso)


class GitActionRecord(BaseModel):
    """Record of a branch, commit, push, or pull request."""
    id: Optional[int] = None
    run_id: str
    repository: str
    action_type: str  # "branch", "commit", "push", "pull_request"
    branch_name: Optional[str] = None
    base_sha: Optional[str] = None
    commit_sha: Optional[str] = None
    diff_hash: Optional[str] = None
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    status: str = "success"
    timestamp: str = Field(default_factory=utc_now_iso)


class HealthRecord(BaseModel):
    """Snapshot of repository health metric components over time."""
    id: Optional[int] = None
    repository: str
    health_score: float
    open_critical: int
    open_high: int
    open_medium: int
    open_low: int
    freshness_hours: float
    timestamp: str = Field(default_factory=utc_now_iso)


class MutationJournalRecord(BaseModel):
    """Audit journal of attempted and verified workspace mutations."""
    id: Optional[int] = None
    run_id: str
    repository: str
    base_sha: str
    intended_branch: str
    intended_files: List[str]
    actual_files_changed: List[str] = Field(default_factory=list)
    final_diff_hash: Optional[str] = None
    commit_sha: Optional[str] = None
    verified: bool = False
    timestamp: str = Field(default_factory=utc_now_iso)


class DailyMissionRecord(BaseModel):
    """Record of a daily maintenance mission executed on a selected repository."""
    mission_id: str
    repository: str
    mission_date: str
    mission_type: MissionType = MissionType.FULL_MAINTENANCE
    status: str = "planned"
    base_sha: Optional[str] = None
    head_sha: Optional[str] = None
    estimated_cost: int = 0
    budget_allocated: int = 0
    findings_targeted: List[str] = Field(default_factory=list)
    findings_resolved: List[str] = Field(default_factory=list)
    findings_unchanged: List[str] = Field(default_factory=list)
    findings_new: List[str] = Field(default_factory=list)
    deletion_guard_passed: bool = True
    verified_diff_hash: Optional[str] = None
    commit_sha: Optional[str] = None
    branch_pushed: Optional[str] = None
    pr_url: Optional[str] = None
    summary: Optional[str] = None
    started_at: str = Field(default_factory=utc_now_iso)
    ended_at: Optional[str] = None
    error_message: Optional[str] = None


class DeferredTaskRecord(BaseModel):
    """Record of maintenance work deferred due to budget, risk, or dependencies."""
    id: str
    repository: str
    mission_id: str
    finding_ids: List[str] = Field(default_factory=list)
    title: str
    evidence: str
    proposed_plan: str
    affected_files: List[str] = Field(default_factory=list)
    estimated_cost: int = 0
    reason_for_deferral: str
    status: DeferredStatus = DeferredStatus.DEFERRED_BUDGET
    attempts_count: int = 0
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class BaselineManifestRecord(BaseModel):
    """Immutable snapshot of tracked files and hashes prior to mutation."""
    id: Optional[int] = None
    run_id: str
    repository: str
    base_sha: str
    tracked_files: List[str] = Field(default_factory=list)
    file_hashes: Dict[str, str] = Field(default_factory=dict)
    captured_at: str = Field(default_factory=utc_now_iso)


class DeletionViolationRecord(BaseModel):
    """Record of an attempted permanent deletion of an existing tracked file."""
    id: Optional[int] = None
    run_id: str
    repository: str
    deleted_file: str
    restored: bool = False
    detected_at: str = Field(default_factory=utc_now_iso)


class DiffFreezeRecord(BaseModel):
    """Verified diff hash validation immediately prior to Git staging."""
    id: Optional[int] = None
    run_id: str
    repository: str
    verified_diff_hash: str
    pre_commit_diff_hash: str
    is_match: bool
    frozen_at: str = Field(default_factory=utc_now_iso)

