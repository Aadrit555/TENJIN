"""TENJIN Autonomous Engineering Run Coordinator.

Orchestrates the complete autonomous engineering pipeline for a daily repository maintenance mission:
Selection -> Isolated Workspace Prep -> Baseline Manifest (Deletion Guard) ->
10-Layer Audit -> Deduplication -> Capacity-Constrained Budget Planning ->
Antigravity Agent Delegation -> Independent Verification -> Pre-commit Diff Freeze ->
Incremental Git Commits -> Branch Push -> Optional PR -> Reporting -> System Memory Updates.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from tenjin.agents.antigravity import AntigravityRunner
from tenjin.agents.task_builder import build_evidence_package, build_mission_task_prompt
from tenjin.audit.deduplication import deduplicate_and_reconcile_findings
from tenjin.audit.engine import AuditEngine
from tenjin.core.capabilities import CapabilityInventory
from tenjin.core.config import TenjinConfig
from tenjin.core.constants import AutonomyLevel, FindingStatus, MissionType, State
from tenjin.git.repository import GitRepositoryOperator, compute_diff_hash
from tenjin.github.client import GitHubClient
from tenjin.memory.database import Database
from tenjin.memory.models import (
    AgentExecutionRecord,
    DailyMissionRecord,
    FindingRecord,
    GitActionRecord,
    HealthRecord,
    RepositoryRecord,
    RunRecord,
    VerificationRunRecord,
)
from tenjin.notifications.desktop import send_desktop_notification
from tenjin.orchestration.state_machine import RunStateMachine
from tenjin.policies.budget import BudgetPlanner
from tenjin.policies.policy import can_autofix_finding, resolve_effective_policy
from tenjin.reporting.report_generator import generate_json_report, generate_markdown_report
from tenjin.repositories.instructions import extract_repository_instructions
from tenjin.repositories.project_detection import detect_project_profile
from tenjin.repositories.workspace import WorkspaceManager
from tenjin.security.deletion_guard import DeletionGuard
from tenjin.verification.engine import VerificationEngine

logger = logging.getLogger("tenjin.orchestration.coordinator")


def utc_now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat()


class RunCoordinator:
    """Coordinates execution of a complete autonomous engineering run."""

    def __init__(
        self,
        db: Database,
        config: TenjinConfig,
        capabilities: CapabilityInventory,
        workspace_mgr: WorkspaceManager,
        audit_engine: AuditEngine,
        agent_runner: AntigravityRunner,
        github_client: GitHubClient,
    ):
        self.db = db
        self.config = config
        self.caps = capabilities
        self.workspace_mgr = workspace_mgr
        self.audit_engine = audit_engine
        self.agent_runner = agent_runner
        self.github_client = github_client

    def execute_repository_run(
        self,
        repository: RepositoryRecord,
        selection_rationale: str = "Autonomous selection",
        custom_run_id: Optional[str] = None,
        mission_type: MissionType = MissionType.FULL_MAINTENANCE,
    ) -> RunRecord:
        """Run the full autonomous engineering cycle for a chosen repository."""
        run_id = custom_run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        start_time = time.time()
        today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        run_rec = RunRecord(
            run_id=run_id,
            repository=repository.full_name,
            state=State.SELECTING,
            autonomy_level=self.config.safety.autonomy_level,
            selection_rationale=selection_rationale,
        )
        self.db.create_run(run_rec)
        sm = RunStateMachine(run_rec, self.db)

        # Initialize Daily Mission Record
        mission_rec = DailyMissionRecord(
            mission_id=run_id,
            repository=repository.full_name,
            mission_date=today_date,
            mission_type=mission_type,
            status="in_progress",
            budget_allocated=self.config.budget.daily_token_budget,
            started_at=utc_now_iso(),
        )
        try:
            self.db.create_daily_mission(mission_rec)
        except Exception as e:
            logger.warning("Could not persist initial daily mission record: %s", e)

        git_actions: List[GitActionRecord] = []
        verification_runs: List[VerificationRunRecord] = []
        all_findings: List[FindingRecord] = []

        try:
            # 1. PREPARING: Setup isolated workspace
            sm.transition_to(State.PREPARING, "Preparing isolated managed workspace")
            ws_ctx = self.workspace_mgr.prepare_workspace(repository)
            run_rec.base_sha = ws_ctx.base_sha
            mission_rec.base_sha = ws_ctx.base_sha
            self.db.update_run(run_rec)

            git_op = GitRepositoryOperator(ws_ctx.path, self.caps.git_path)

            # 2. CAPTURE IMMUTABLE BASELINE MANIFEST (Hard Deletion Guard)
            sm.transition_to(State.INVENTORYING, "Capturing immutable baseline manifest and project profile")
            deletion_guard = DeletionGuard(git_path=self.caps.git_path or "git")
            baseline_manifest = deletion_guard.capture_baseline(
                repo_path=ws_ctx.path,
                run_id=run_id,
                repository=repository.full_name,
            )
            try:
                self.db.create_baseline_manifest(baseline_manifest)
            except Exception as e:
                logger.warning("Failed to store baseline manifest in db: %s", e)

            # Detect ecosystem and instructions
            profile = detect_project_profile(ws_ctx.path, self.caps)
            repo_instructions = extract_repository_instructions(ws_ctx.path)

            # Resolve effective policy with strict fail-closed allowlist and account gates
            policy = resolve_effective_policy(
                global_cfg=self.config,
                repo_path=ws_ctx.path,
                repo_name_or_url=repository.full_name,
                active_antigravity_account=self.caps.antigravity.active_account,
            )

            if policy.block_reason:
                logger.info("Policy gate triggered: %s", policy.block_reason)

            # 3. AUDITING: Run 10-layer real engineering audit
            sm.transition_to(State.AUDITING, "Running deep 10-layer real engineering audit")
            raw_findings = self.audit_engine.run_audit(repository.full_name, ws_ctx.path, run_id)

            # Reconcile & deduplicate findings in SQLite
            all_findings = deduplicate_and_reconcile_findings(self.db, run_id, raw_findings)
            run_rec.findings_count = len(all_findings)
            self.db.update_run(run_rec)

            # 4. PLANNING: Budget-aware maintenance planning
            sm.transition_to(State.PLANNING, "Evaluating repair budget and scheduling daily work units")

            # Load any previously deferred tasks for this repository
            deferred_tasks = self.db.list_deferred_tasks(repository=repository.full_name)

            budget_planner = BudgetPlanner(self.config.budget)
            plan = budget_planner.create_maintenance_plan(
                mission_id=run_id,
                repository=repository.full_name,
                findings=all_findings,
                deferred_tasks=deferred_tasks,
                mission_type=mission_type,
            )

            # Persist any tasks that cannot fit in today's mission
            budget_planner.persist_deferred_work(self.db, plan)

            mission_rec.estimated_cost = plan.allocated_tokens
            mission_rec.findings_targeted = [item.item_id for item in plan.selected_work_items]

            # Filter selected work items against effective policy permissions
            actionable_items = []
            for item in plan.selected_work_items:
                # Find matching findings
                item_findings = [f for f in all_findings if f.id in item.finding_ids]
                if not item_findings and item.is_deferred_recovery:
                    actionable_items.append((item, None))
                    continue

                # Check if at least one finding in the item is allowed for autofix
                allowed = False
                for f in item_findings:
                    ok, _ = can_autofix_finding(f, policy)
                    if ok:
                        allowed = True
                        break
                if allowed:
                    actionable_items.append((item, item_findings[0] if item_findings else None))

            # Check if mutations are allowed by autonomy level and policy
            if (
                policy.autonomy_level < AutonomyLevel.LEVEL_3_COMMIT_BRANCH
                or not actionable_items
                or not policy.autonomous_fixes
            ):
                reason = policy.block_reason or "Read-only audit completed; no autonomous mutations permitted under policy"
                sm.transition_to(State.REPORTING, reason)
                mission_rec.status = "audit_completed"
            else:
                # 5. REPAIR & VERIFICATION OF PLANNED WORK ITEMS
                ver_engine = VerificationEngine(
                    capabilities=self.caps,
                    audit_engine=self.audit_engine,
                    db=self.db,
                )

                for item, primary_finding in actionable_items:
                    logger.info("Executing maintenance work item: %s", item.title)

                    branch_name = git_op.create_isolated_branch(f"forge_{run_id}_{item.item_id[:8]}")
                    git_actions.append(
                        GitActionRecord(
                            run_id=run_id,
                            repository=repository.full_name,
                            action_type="branch",
                            branch_name=branch_name,
                            base_sha=ws_ctx.base_sha,
                        )
                    )

                    # Build mission prompt for the work item
                    prompt = build_mission_task_prompt(
                        repository=repository,
                        base_sha=ws_ctx.base_sha,
                        work_item=item,
                        workspace_path=ws_ctx.path,
                        policy=policy,
                        repo_instructions_text=repo_instructions.sanitized_text,
                    )

                    # Invoke Antigravity CLI
                    sm.transition_to(State.AGENT_RUNNING, f"Invoking Antigravity for work item {item.item_id}")
                    try:
                        agent_res, raw_out, duration = self.agent_runner.run_repair_task(
                            workspace_path=ws_ctx.path,
                            task_prompt=prompt,
                        )
                        self.db.record_agent_execution(
                            AgentExecutionRecord(
                                run_id=run_id,
                                finding_id=item.item_id,
                                agent_interface="cli",
                                prompt=prompt,
                                raw_output=raw_out,
                                parsed_output=agent_res.model_dump(),
                                status=agent_res.status,
                                duration_seconds=duration,
                            )
                        )
                    except Exception as e:
                        logger.error("Antigravity execution failed for work item %s: %s", item.item_id, e)
                        continue

                    # INDEPENDENT VERIFICATION & DELETION GUARD
                    sm.transition_to(State.VERIFYING, f"Independently verifying changes for {item.title}")
                    diff_text = self.workspace_mgr.get_diff(ws_ctx.path)
                    changed_files = self.workspace_mgr.get_changed_files(ws_ctx.path)

                    ver_result = ver_engine.verify_repair(
                        repository_name=repository.full_name,
                        workspace_path=ws_ctx.path,
                        finding=primary_finding,
                        run_id=run_id,
                        changed_files=changed_files,
                        diff_text=diff_text,
                        policy=policy,
                        project_profile=profile,
                        baseline_manifest=baseline_manifest,
                        baseline_findings=all_findings,
                        targeted_finding_ids=item.finding_ids,
                    )

                    ver_rec = VerificationRunRecord(
                        run_id=run_id,
                        finding_id=item.item_id,
                        passed=ver_result.passed,
                        diff_valid=ver_result.diff_valid,
                        secrets_detected=not ver_result.secrets_clean,
                        tests_passed=ver_result.tests_passed,
                        lint_passed=ver_result.lint_passed,
                        types_passed=ver_result.types_passed,
                        security_passed=ver_result.security_passed,
                        details=ver_result.details,
                    )
                    self.db.record_verification_run(ver_rec)
                    verification_runs.append(ver_rec)

                    mission_rec.deletion_guard_passed = ver_result.deletion_guard_passed
                    mission_rec.verified_diff_hash = ver_result.diff_freeze_hash
                    mission_rec.findings_resolved.extend(ver_result.resolved_findings)
                    mission_rec.findings_unchanged.extend(ver_result.unchanged_findings)
                    mission_rec.findings_new.extend(ver_result.new_findings)

                    # COMMIT AFTER EVERY FILE / WORK ITEM
                    if ver_result.passed and policy.auto_commit:
                        sm.transition_to(State.COMMITTING, f"Committing verified work for {item.title}")
                        git_op.stage_files(changed_files)
                        commit_sha = git_op.commit_verified_changes(
                            scope=primary_finding.subcategory if primary_finding else "maintenance",
                            description=agent_res.suggested_commit_message or item.title,
                            finding_id=item.item_id,
                            run_id=run_id,
                        )
                        diff_hash = ver_result.diff_freeze_hash or compute_diff_hash(diff_text)
                        run_rec.head_sha = commit_sha
                        mission_rec.commit_sha = commit_sha
                        run_rec.fixed_count += len(ver_result.resolved_findings) or 1

                        # Mark resolved findings as FIXED in SQLite
                        for fid in ver_result.resolved_findings:
                            for f in all_findings:
                                if f.id == fid:
                                    f.status = FindingStatus.FIXED
                                    self.db.upsert_finding(f)

                        git_actions.append(
                            GitActionRecord(
                                run_id=run_id,
                                repository=repository.full_name,
                                action_type="commit",
                                branch_name=branch_name,
                                commit_sha=commit_sha,
                                diff_hash=diff_hash,
                            )
                        )

                        # PUSHING if policy permits
                        if policy.auto_push:
                            sm.transition_to(State.PUSHING, f"Pushing branch {branch_name} to remote")
                            git_op.push_branch(branch_name)
                            mission_rec.branch_pushed = branch_name
                            git_actions.append(
                                GitActionRecord(
                                    run_id=run_id,
                                    repository=repository.full_name,
                                    action_type="push",
                                    branch_name=branch_name,
                                )
                            )

                            # PULL REQUEST if policy permits
                            if policy.auto_pr:
                                pr_body = f"""## TENJIN Daily Maintenance Mission

- **Target Work Item**: {item.title}
- **Resolved Findings**: {', '.join(ver_result.resolved_findings) if ver_result.resolved_findings else 'Maintenance improvements'}
- **Verification**: Tests, linters, Deletion Guard, and diff freeze passed independently.
- **Commit SHA**: {commit_sha}
- **Mission ID**: {run_id}
"""
                                pr_res = self.github_client.create_pull_request(
                                    repository=repository.full_name,
                                    head_branch=branch_name,
                                    base_branch=repository.default_branch,
                                    title=f"chore(maintenance): {item.title}",
                                    body=pr_body,
                                )
                                mission_rec.pr_url = pr_res.get("url")
                                git_actions.append(
                                    GitActionRecord(
                                        run_id=run_id,
                                        repository=repository.full_name,
                                        action_type="pull_request",
                                        branch_name=branch_name,
                                        pr_url=pr_res.get("url"),
                                        pr_number=pr_res.get("number"),
                                    )
                                )

                sm.transition_to(State.REPORTING, "Generating final audit and mission reports")
                mission_rec.status = "completed"

            # 6. REPORTING: Generate reports
            reports_dir = Path(self.config.reports_dir)
            generate_json_report(run_rec, all_findings, git_actions, verification_runs, reports_dir)
            generate_markdown_report(run_rec, all_findings, git_actions, verification_runs, reports_dir)

            # Update repository memory and health score
            now_iso = utc_now_iso()
            repository.last_audit_at = now_iso
            crit = sum(1 for f in all_findings if f.severity.value == "critical" and f.status.value == "open")
            high = sum(1 for f in all_findings if f.severity.value == "high" and f.status.value == "open")
            med = sum(1 for f in all_findings if f.severity.value == "medium" and f.status.value == "open")
            low = sum(1 for f in all_findings if f.severity.value in ["low", "informational"] and f.status.value == "open")
            health = max(0.0, 100.0 - (crit * 25.0 + high * 10.0 + med * 3.0 + low * 1.0))
            repository.health_score = round(health, 1)
            self.db.upsert_repository(repository)
            self.db.record_health(
                HealthRecord(
                    repository=repository.full_name,
                    health_score=repository.health_score,
                    open_critical=crit,
                    open_high=high,
                    open_medium=med,
                    open_low=low,
                    freshness_hours=0.0,
                )
            )

            # Finish run
            sm.transition_to(State.COMPLETED, "Autonomous engineering maintenance completed successfully")
            run_rec.ended_at = now_iso
            run_rec.duration_seconds = round(time.time() - start_time, 2)
            self.db.update_run(run_rec)

            mission_rec.ended_at = now_iso
            mission_rec.summary = (
                f"Completed: {run_rec.fixed_count} findings resolved, "
                f"health score: {repository.health_score}"
            )
            try:
                self.db.update_daily_mission(mission_rec)
            except Exception as e:
                logger.debug("Failed to update daily mission record: %s", e)

            # Send notification
            send_desktop_notification(
                title=f"TENJIN Mission Complete: {repository.name}",
                message=f"Audit completed: {run_rec.findings_count} findings, {run_rec.fixed_count} resolved. Health: {repository.health_score}%",
                config=self.config.notifications,
            )

            return run_rec

        except Exception as e:
            logger.error("Run failed with unhandled exception: %s", e, exc_info=True)
            sm.transition_to(State.FAILED, f"Run encountered fatal error: {e}")
            run_rec.error_message = str(e)
            run_rec.ended_at = utc_now_iso()
            run_rec.duration_seconds = round(time.time() - start_time, 2)
            self.db.update_run(run_rec)

            mission_rec.status = "failed"
            mission_rec.error_message = str(e)
            mission_rec.ended_at = utc_now_iso()
            try:
                self.db.update_daily_mission(mission_rec)
            except Exception:
                pass

            return run_rec
