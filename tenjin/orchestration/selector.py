"""TENJIN Autonomous Repository Selection Engine.

Supports both uniform random daily selection across the managed 11-repository
allowlist and weighted multi-factor scoring (audit staleness, push activity,
open high-severity findings, starvation thresholds). Records structured rationale.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from tenjin.core.config import TenjinConfig
from tenjin.memory.database import Database
from tenjin.memory.models import RepositoryRecord, SelectionDecisionRecord
from tenjin.policies.policy import is_repository_managed

logger = logging.getLogger("tenjin.orchestration.selector")


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string to UTC datetime."""
    if not dt_str:
        return None
    try:
        cleaned = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except Exception:
        return None


class RepositorySelector:
    """Ranks and selects repositories for autonomous engineering attention."""

    def __init__(self, db: Database, config: TenjinConfig):
        self.db = db
        self.config = config

    def select_daily_managed_repository(
        self,
        mission_id: str,
    ) -> Optional[Tuple[RepositoryRecord, SelectionDecisionRecord]]:
        """Uniform random daily selection strictly across the managed 11-repository allowlist."""
        all_repos = self.db.list_repositories()
        managed_list = self.config.managed_repositories

        # Filter to repositories present in the managed allowlist
        candidates = [
            r for r in all_repos
            if is_repository_managed(r.full_name, managed_list)
        ]

        if not candidates:
            # If no managed repositories exist in DB, register them now from authoritative list
            for full_name in managed_list:
                parts = full_name.split("/")
                owner = parts[0] if len(parts) > 1 else ""
                name = parts[1] if len(parts) > 1 else full_name
                r = RepositoryRecord(
                    full_name=full_name,
                    owner=owner,
                    name=name,
                    url=f"https://github.com/{full_name}",
                    clone_url=f"https://github.com/{full_name}.git",
                    ssh_url=f"git@github.com:{full_name}.git",
                    is_managed=True,
                )
                self.db.upsert_repository(r)
                candidates.append(r)

        # Uniform random choice among managed candidates
        chosen = random.choice(candidates)

        decision = SelectionDecisionRecord(
            run_id=mission_id,
            repository=chosen.full_name,
            score=1.0,
            stale_audit_score=1.0,
            activity_score=1.0,
            unresolved_findings_score=0.0,
            exploration_score=1.0,
            factors={
                "selection_strategy": "uniform_random_managed",
                "pool_size": len(candidates),
                "managed_allowlist_size": len(managed_list),
            },
        )
        self.db.record_selection_decision(decision)
        logger.info(
            "Uniform random selection selected managed repository %s (out of %d candidates) for mission %s",
            chosen.full_name,
            len(candidates),
            mission_id,
        )
        return chosen, decision

    def select_next_repository(
        self,
        run_id: str,
        strategy: Optional[str] = None,
    ) -> Optional[Tuple[RepositoryRecord, SelectionDecisionRecord]]:
        """Select next repository using configured or specified strategy."""
        chosen_strategy = strategy or self.config.schedule.selection_strategy

        if chosen_strategy == "random":
            all_repos = self.db.list_repositories()
            managed_candidates = [
                r for r in all_repos
                if is_repository_managed(r.full_name, self.config.managed_repositories)
            ]
            if managed_candidates:
                return self.select_daily_managed_repository(run_id)

        return self._select_weighted_repository(run_id)

    def _select_weighted_repository(
        self, run_id: str
    ) -> Optional[Tuple[RepositoryRecord, SelectionDecisionRecord]]:
        """Weighted multi-factor repository selection."""
        repositories = self.db.list_repositories()
        if not repositories:
            logger.info("No repositories available in database for selection.")
            return None

        now = datetime.now(timezone.utc)
        cfg_sel = self.config.selection

        scored_candidates: List[Tuple[float, RepositoryRecord, SelectionDecisionRecord]] = []

        for repo in repositories:
            # 1. Stale Audit Factor (0.0 to 1.0)
            stale_score = 0.0
            last_audit = parse_iso_datetime(repo.last_audit_at)
            if not last_audit:
                stale_score = 1.0
            else:
                elapsed_hours = (now - last_audit).total_seconds() / 3600.0
                if elapsed_hours < cfg_sel.cooldown_hours:
                    logger.debug("Skipping %s: in cooldown period (%.1f h < %.1f h)", repo.full_name, elapsed_hours, cfg_sel.cooldown_hours)
                    continue

                if elapsed_hours >= cfg_sel.starvation_threshold_hours:
                    stale_score = 1.0
                else:
                    stale_score = min(1.0, elapsed_hours / cfg_sel.starvation_threshold_hours)

            # 2. Activity Factor (0.0 to 1.0)
            activity_score = 0.0
            last_push = parse_iso_datetime(repo.pushed_at)
            if last_push:
                push_age_days = (now - last_push).total_seconds() / 86400.0
                activity_score = max(0.0, 1.0 - (push_age_days / 14.0))

            # 3. Unresolved Findings Factor (0.0 to 1.0)
            open_findings = self.db.list_findings(repository=repo.full_name)
            critical_high_count = sum(
                1 for f in open_findings
                if f.severity.value in ["critical", "high"] and f.status.value == "open"
            )
            findings_score = min(1.0, critical_high_count * 0.3)

            # 4. Exploration Contribution (stochastic tie-breaker)
            exploration_score = random.uniform(0.0, 1.0)

            # Weighted Aggregate Score
            total_score = (
                (stale_score * cfg_sel.stale_audit_weight)
                + (activity_score * cfg_sel.activity_weight)
                + (findings_score * cfg_sel.unresolved_findings_weight)
                + (exploration_score * cfg_sel.exploration_weight)
            )

            decision = SelectionDecisionRecord(
                run_id=run_id,
                repository=repo.full_name,
                score=round(total_score, 4),
                stale_audit_score=round(stale_score, 4),
                activity_score=round(activity_score, 4),
                unresolved_findings_score=round(findings_score, 4),
                exploration_score=round(exploration_score, 4),
                factors={
                    "never_audited": last_audit is None,
                    "hours_since_audit": round((now - last_audit).total_seconds() / 3600.0, 1) if last_audit else None,
                    "critical_high_findings": critical_high_count,
                    "weights_applied": {
                        "stale_audit": cfg_sel.stale_audit_weight,
                        "activity": cfg_sel.activity_weight,
                        "findings": cfg_sel.unresolved_findings_weight,
                        "exploration": cfg_sel.exploration_weight,
                    },
                },
            )

            scored_candidates.append((total_score, repo, decision))

        if not scored_candidates:
            logger.info("All repositories are currently in cooldown.")
            return None

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_repo, best_decision = scored_candidates[0]

        # Record decision in database
        self.db.record_selection_decision(best_decision)
        logger.info(
            "Autonomously selected %s with decision score %.4f (stale: %.2f, activity: %.2f, findings: %.2f)",
            best_repo.full_name,
            best_score,
            best_decision.stale_audit_score,
            best_decision.activity_score,
            best_decision.unresolved_findings_score,
        )

        return best_repo, best_decision
