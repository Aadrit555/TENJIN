"""TENJIN Budget-Aware Mission Planning Engine.

Evaluates available Antigravity context and token budget, reserves verification
and recovery capacity, groups related findings into coherent work items,
classifies tasks (FITS_TODAY, TOO_LARGE_TODAY, DEFERRED), and persists deferred work.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tenjin.core.config import BudgetConfig
from tenjin.core.constants import (
    DeferredStatus,
    FindingSeverity,
    MissionType,
    RiskLevel,
    WorkClassification,
)
from tenjin.memory.models import DeferredTaskRecord, FindingRecord

logger = logging.getLogger("tenjin.policies.budget")


def utc_now_iso() -> str:
    """Return current UTC time in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkItem:
    """A coherent maintenance work unit grouped from one or more findings."""
    item_id: str
    title: str
    finding_ids: List[str]
    severity: FindingSeverity
    risk: RiskLevel
    affected_files: List[str]
    estimated_tokens: int
    classification: WorkClassification = WorkClassification.FITS_TODAY
    deferral_reason: Optional[str] = None
    proposed_fix: Optional[str] = None
    evidence: str = ""
    is_deferred_recovery: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "finding_ids": self.finding_ids,
            "severity": self.severity.value if hasattr(self.severity, "value") else str(self.severity),
            "risk": self.risk.value if hasattr(self.risk, "value") else str(self.risk),
            "affected_files": self.affected_files,
            "estimated_tokens": self.estimated_tokens,
            "classification": self.classification.value if hasattr(self.classification, "value") else str(self.classification),
            "deferral_reason": self.deferral_reason,
            "proposed_fix": self.proposed_fix,
            "evidence": self.evidence,
            "is_deferred_recovery": self.is_deferred_recovery,
        }


@dataclass
class MaintenancePlan:
    """Budget-constrained plan for a daily engineering maintenance mission."""
    mission_id: str
    repository: str
    mission_type: MissionType
    total_daily_budget: int
    verification_reserve: int
    recovery_reserve: int
    available_execution_budget: int
    allocated_tokens: int = 0
    remaining_tokens: int = 0
    selected_work_items: List[WorkItem] = field(default_factory=list)
    deferred_work_items: List[WorkItem] = field(default_factory=list)
    blocked_work_items: List[WorkItem] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "repository": self.repository,
            "mission_type": self.mission_type.value if hasattr(self.mission_type, "value") else str(self.mission_type),
            "total_daily_budget": self.total_daily_budget,
            "verification_reserve": self.verification_reserve,
            "recovery_reserve": self.recovery_reserve,
            "available_execution_budget": self.available_execution_budget,
            "allocated_tokens": self.allocated_tokens,
            "remaining_tokens": self.remaining_tokens,
            "selected_work_items": [i.to_dict() for i in self.selected_work_items],
            "deferred_work_items": [i.to_dict() for i in self.deferred_work_items],
            "blocked_work_items": [i.to_dict() for i in self.blocked_work_items],
            "created_at": self.created_at,
        }


class BudgetPlanner:
    """Computes capacity allocations and schedules daily maintenance work."""

    def __init__(self, config: Optional[BudgetConfig] = None) -> None:
        self.config = config or BudgetConfig()

    def estimate_finding_tokens(self, finding: FindingRecord) -> int:
        """Estimate the token cost required to analyze and repair a finding."""
        base_tokens = 4000
        # Files impact
        files_cost = 2500 if finding.file else 1000
        # Text context volume
        evidence_tokens = len(finding.evidence or "") // 3
        summary_tokens = len(finding.summary or "") // 3
        fix_tokens = len(finding.suggested_fix or "") // 3
        # Complexity weight by severity
        severity_multiplier = {
            FindingSeverity.CRITICAL: 1.5,
            FindingSeverity.HIGH: 1.3,
            FindingSeverity.MEDIUM: 1.0,
            FindingSeverity.LOW: 0.8,
            FindingSeverity.INFORMATIONAL: 0.6,
        }.get(finding.severity, 1.0)

        estimated = int((base_tokens + files_cost + evidence_tokens + summary_tokens + fix_tokens) * severity_multiplier)
        # Clamp to realistic bounds
        return max(3000, min(35000, estimated))

    def group_findings_into_work_items(
        self,
        findings: List[FindingRecord],
        deferred_tasks: Optional[List[DeferredTaskRecord]] = None,
    ) -> List[WorkItem]:
        """Group related findings by file or subcategory to produce coherent work units."""
        items: List[WorkItem] = []

        # First, incorporate previously deferred tasks if present
        if deferred_tasks:
            for d in deferred_tasks:
                items.append(
                    WorkItem(
                        item_id=d.id,
                        title=f"[Previously Deferred] {d.title}",
                        finding_ids=d.finding_ids,
                        severity=FindingSeverity.HIGH,
                        risk=RiskLevel.MEDIUM,
                        affected_files=d.affected_files,
                        estimated_tokens=d.estimated_cost or 8000,
                        classification=WorkClassification.FITS_TODAY,
                        proposed_fix=d.proposed_plan,
                        evidence=d.evidence,
                        is_deferred_recovery=True,
                    )
                )

        # Group current findings by primary file if present, else by subcategory
        groups: Dict[str, List[FindingRecord]] = {}
        for f in findings:
            key = f.file if f.file else f"subcat:{f.subcategory or f.category}"
            groups.setdefault(key, []).append(f)

        for key, group_findings in groups.items():
            # Pick highest severity and risk in the group
            severity_order = [
                FindingSeverity.CRITICAL,
                FindingSeverity.HIGH,
                FindingSeverity.MEDIUM,
                FindingSeverity.LOW,
                FindingSeverity.INFORMATIONAL,
            ]
            highest_sev = min(
                (f.severity for f in group_findings),
                key=lambda s: severity_order.index(s) if s in severity_order else 99,
            )
            risk_order = [
                RiskLevel.CRITICAL,
                RiskLevel.HIGH,
                RiskLevel.MEDIUM,
                RiskLevel.LOW,
                RiskLevel.TRIVIAL,
            ]
            highest_risk = min(
                (f.risk for f in group_findings),
                key=lambda r: risk_order.index(r) if r in risk_order else 99,
            )

            all_files: List[str] = []
            for f in group_findings:
                if f.file and f.file not in all_files:
                    all_files.append(f.file)

            total_tokens = sum(self.estimate_finding_tokens(f) for f in group_findings)
            # Synergistic discount for multi-finding groups in same file
            if len(group_findings) > 1:
                total_tokens = int(total_tokens * 0.75)

            finding_ids = [f.id for f in group_findings]
            if key.startswith("subcat:"):
                title = f"Maintain {key[7:]} across repository ({len(group_findings)} findings)"
            else:
                title = f"Repair {key} ({len(group_findings)} findings)"

            primary_finding = group_findings[0]
            items.append(
                WorkItem(
                    item_id=f"work-{uuid.uuid4().hex[:8]}",
                    title=title,
                    finding_ids=finding_ids,
                    severity=highest_sev,
                    risk=highest_risk,
                    affected_files=all_files,
                    estimated_tokens=total_tokens,
                    proposed_fix=primary_finding.suggested_fix,
                    evidence=primary_finding.evidence or primary_finding.summary or "",
                    is_deferred_recovery=False,
                )
            )

        # Sort items: critical severity first, then recovery items, then higher cost
        severity_rank = {
            FindingSeverity.CRITICAL: 0,
            FindingSeverity.HIGH: 1,
            FindingSeverity.MEDIUM: 2,
            FindingSeverity.LOW: 3,
            FindingSeverity.INFORMATIONAL: 4,
        }
        items.sort(
            key=lambda item: (
                severity_rank.get(item.severity, 99),
                0 if item.is_deferred_recovery else 1,
                -item.estimated_tokens,
            )
        )
        return items

    def create_maintenance_plan(
        self,
        mission_id: str,
        repository: str,
        findings: List[FindingRecord],
        deferred_tasks: Optional[List[DeferredTaskRecord]] = None,
        mission_type: MissionType = MissionType.FULL_MAINTENANCE,
    ) -> MaintenancePlan:
        """Create a budget-constrained maintenance plan for today's mission."""
        total_budget = self.config.daily_token_budget
        verif_reserve = int(total_budget * self.config.verification_reserve_pct)
        recov_reserve = int(total_budget * self.config.recovery_reserve_pct)
        available_exec = total_budget - verif_reserve - recov_reserve

        plan = MaintenancePlan(
            mission_id=mission_id,
            repository=repository,
            mission_type=mission_type,
            total_daily_budget=total_budget,
            verification_reserve=verif_reserve,
            recovery_reserve=recov_reserve,
            available_execution_budget=available_exec,
            remaining_tokens=available_exec,
        )

        all_work_items = self.group_findings_into_work_items(findings, deferred_tasks)

        remaining_budget = available_exec
        allocated_budget = 0
        max_items = self.config.max_work_items_per_day

        for item in all_work_items:
            # Check if single item exceeds total available execution budget
            if item.estimated_tokens > available_exec:
                item.classification = WorkClassification.TOO_LARGE_TODAY
                item.deferral_reason = (
                    f"Estimated tokens ({item.estimated_tokens}) exceeds total execution budget ({available_exec})"
                )
                plan.deferred_work_items.append(item)
                continue

            # Check if it fits in remaining budget and item count cap
            if item.estimated_tokens <= remaining_budget and len(plan.selected_work_items) < max_items:
                item.classification = WorkClassification.FITS_TODAY
                remaining_budget -= item.estimated_tokens
                allocated_budget += item.estimated_tokens
                plan.selected_work_items.append(item)
            else:
                item.classification = WorkClassification.DEFERRED
                item.deferral_reason = (
                    f"Deferred: exceeds remaining daily mission budget ({remaining_budget} tokens left)"
                )
                plan.deferred_work_items.append(item)

        plan.allocated_tokens = allocated_budget
        plan.remaining_tokens = remaining_budget

        logger.info(
            "Maintenance plan created for %s: %d selected (%d tokens), %d deferred, %d remaining tokens",
            repository,
            len(plan.selected_work_items),
            plan.allocated_tokens,
            len(plan.deferred_work_items),
            plan.remaining_tokens,
        )
        return plan

    def persist_deferred_work(self, db: Any, plan: MaintenancePlan) -> List[DeferredTaskRecord]:
        """Persist deferred work items to SQLite storage for future missions."""
        records: List[DeferredTaskRecord] = []
        now = utc_now_iso()

        for item in plan.deferred_work_items:
            status = (
                DeferredStatus.DEFERRED_BUDGET
                if item.classification in [WorkClassification.DEFERRED, WorkClassification.TOO_LARGE_TODAY]
                else DeferredStatus.BLOCKED
            )
            rec = DeferredTaskRecord(
                id=item.item_id,
                repository=plan.repository,
                mission_id=plan.mission_id,
                finding_ids=item.finding_ids,
                title=item.title,
                evidence=item.evidence,
                proposed_plan=item.proposed_fix or "",
                affected_files=item.affected_files,
                estimated_cost=item.estimated_tokens,
                reason_for_deferral=item.deferral_reason or "Deferred due to mission capacity",
                status=status,
                attempts_count=0,
                created_at=now,
                updated_at=now,
            )
            try:
                db.create_deferred_task(rec)
                records.append(rec)
            except Exception as e:
                logger.error("Failed to persist deferred task %s: %s", rec.id, e)

        return records
