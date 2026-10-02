"""TENJIN Autonomous Engineering Run Coordinator.

Orchestrates the complete autonomous engineering pipeline for a single repository run:
Discovery -> Selection -> Workspace Prep -> 10-Layer Audit -> Deduplication ->
Planning -> Antigravity Delegation -> Independent Verification -> Git Commit/Push/PR ->
Reporting -> System Memory Updates.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import List, Optional

from tenjin.agents.antigravity import AntigravityRunner
from tenjin.agents.task_builder import build_evidence_package
from tenjin.audit.deduplication import deduplicate_and_reconcile_findings
from tenjin.audit.engine import AuditEngine
from tenjin.core.capabilities import CapabilityInventory
from tenjin.core.config import TenjinConfig
from tenjin.core.constants import AutonomyLevel, FindingStatus, State
from tenjin.git.repository import GitRepositoryOperator, compute_diff_hash
from tenjin.github.client import GitHubClient
from tenjin.memory.database import Database
from tenjin.memory.models import (
    AgentExecutionRecord,
    FindingRecord,
    GitActionRecord,
    HealthRecord,
    MutationJournalRecord,
    RepositoryRecord,
    RunRecord,
    VerificationRunRecord,
)
from tenjin.notifications.desktop import send_desktop_notification
from tenjin.orchestration.state_machine import RunStateMachine
from tenjin.policies.policy import can_autofix_finding, resolve_effective_policy
from tenjin.policies.risk import evaluate_change_risk
from tenjin.reporting.report_generator import generate_json_report, generate_markdown_report
from tenjin.repositories.instructions import extract_repository_instructions
from tenjin.repositories.project_detection import detect_project_profile
from tenjin.repositories.workspace import WorkspaceManager

logger = logging.getLogger("tenjin.orchestration.coordinator")


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
    ) -> RunRecord:
        """Run the full autonomous engineering cycle for a chosen repository."""
        run_id = custom_run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        start_time = time.time()

        run_rec = RunRecord(
            run_id=run_id,
            repository=repository.full_name,
            state=State.SELECTING,
            autonomy_level=self.config.safety.autonomy_level,
            selection_rationale=selection_rationale,
        )
        self.db.create_run(run_rec)
        sm = RunStateMachine(run_rec, self.db)

        git_actions: List[GitActionRecord] = []
        verification_runs: List[VerificationRunRecord] = []
        all_findings: List[FindingRecord] = []

        try:
            # 1. PREPARING: Setup isolated workspace
            sm.transition_to(State.PREPARING, "Preparing isolated managed workspace")
            ws_ctx = self.workspace_mgr.prepare_workspace(repository)
            run_rec.base_sha = ws_ctx.base_sha
            self.db.update_run(run_rec)

            git_op = GitRepositoryOperator(ws_ctx.path, self.caps.git_path)

            # 2. INVENTORYING & PROJECT DETECTION
            sm.transition_to(State.INVENTORYING, "Inspecting files, ecosystem manifests, and instructions")
            profile = detect_project_profile(ws_ctx.path, self.caps)
            repo_instructions = extract_repository_instructions(ws_ctx.path)
            policy = resolve_effective_policy(self.config, ws_ctx.path)

            # 3. AUDITING: Run 10-layer audit
            sm.transition_to(State.AUDITING, "Running deep 10-layer real engineering audit")
            raw_findings = self.audit_engine.run_audit(repository.full_name, ws_ctx.path, run_id)

            # Reconcile & deduplicate findings in SQLite
            all_findings = deduplicate_and_reconcile_findings(self.db, run_id, raw_findings)
            run_rec.findings_count = len(all_findings)
            self.db.update_run(run_rec)

            # 4. PLANNING: Assess repair eligibility
            sm.transition_to(State.PLANNING, "Evaluating repair eligibility against risk and policy")
            eligible_findings: List[FindingRecord] = []
            for f in all_findings:
                if f.status == FindingStatus.OPEN:
                    allowed, reason = can_autofix_finding(f, policy)
                    if allowed:
                        eligible_findings.append(f)
                    else:
                        logger.info("Finding %s not eligible for autofix: %s", f.id, reason)

            # Check if mutations are allowed by autonomy level
            if policy.autonomy_level < AutonomyLevel.LEVEL_3_COMMIT_BRANCH or not eligible_findings:
                sm.transition_to(State.REPORTING, "Read-only audit completed; no autonomous mutations permitted")
            else:
                # 5. REPAIR & VERIFICATION LOOP
                repairs_attempted = 0
                max_repairs = min(len(eligible_findings), self.config.concurrency.max_repair_attempts_per_run)

                for finding in eligible_findings[:max_repairs]:
                    repairs_attempted += 1
                    logger.info("Starting repair for finding %s (%s)", finding.id, finding.title)

                    branch_name = git_op.create_isolated_branch(f"{run_id}_{finding.id}")
                    git_actions.append(
                        GitActionRecord(
                            run_id=run_id,
                            repository=repository.full_name,
                            action_type="branch",
                            branch_name=branch_name,
                            base_sha=ws_ctx.base_sha,
                        )
                    )

                    # Build targeted evidence prompt
                    prompt = build_evidence_package(
                        repository=repository,
                        base_sha=ws_ctx.base_sha,
                        finding=finding,
                        workspace_path=ws_ctx.path,
                        policy=policy,
                        repo_instructions_text=repo_instructions.sanitized_text,
                    )

                    # Invoke Antigravity
                    sm.transition_to(State.AGENT_RUNNING, f"Invoking Antigravity for finding {finding.id}")
                    try:
                        agent_res, raw_out, duration = self.agent_runner.run_repair_task(
                            workspace_path=ws_ctx.path,
                            task_prompt=prompt,
                        )
                        self.db.record_agent_execution(
                            AgentExecutionRecord(
                                run_id=run_id,
                                finding_id=finding.id,
                                agent_interface="cli",
                                prompt=prompt,
                                raw_output=raw_out,
                                parsed_output=agent_res.model_dump(),
                                status=agent_res.status,
                                duration_seconds=duration,
                            )
                        )
                    except Exception as e:
                        logger.error("Antigravity execution failed for finding %s: %s", finding.id, e)
                        continue

                    # INDEPENDENT VERIFICATION
                    sm.transition_to(State.VERIFYING, f"Independently verifying agent changes for {finding.id}")
                    diff_text = self.workspace_mgr.get_diff(ws_ctx.path)
                    changed_files = self.workspace_mgr.get_changed_files(ws_ctx.path)

                    ver_engine = from_verification_engine(self.caps, self.audit_engine)
                    ver_result = ver_engine.verify_repair(
                        repository_name=repository.full_name,
                        workspace_path=ws_ctx.path,
                        finding=finding,
                        run_id=run_id,
                        changed_files=changed_files,
                        diff_text=diff_text,
                        policy=policy,
                        project_profile=profile,
                    )

                    ver_rec = VerificationRunRecord(
                        run_id=run_id,
                        finding_id=finding.id,
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

                    if ver_result.passed and policy.auto_commit:
                        sm.transition_to(State.COMMITTING, f"Committing verified repair for {finding.id}")
                        git_op.stage_files(changed_files)
                        commit_sha = git_op.commit_verified_changes(
                            scope=finding.subcategory or "core",
                            description=agent_res.suggested_commit_message or finding.title,
                            finding_id=finding.id,
                            run_id=run_id,
                        )
                        diff_hash = compute_diff_hash(diff_text)
                        run_rec.head_sha = commit_sha
                        run_rec.fixed_count += 1
                        finding.status = FindingStatus.FIXED
                        self.db.upsert_finding(finding)

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
                                pr_body = f"""## TENJIN Autonomous Repair

- **Finding**: {finding.title} (`{finding.id}`)
- **Evidence**: {finding.evidence}
- **Verification**: Tests, linters, and re-audit passed independently.
- **Commit**: {commit_sha}
- **Run ID**: {run_id}
"""
                                pr_res = self.github_client.create_pull_request(
                                    repository=repository.full_name,
                                    head_branch=branch_name,
                                    base_branch=repository.default_branch,
                                    title=f"fix({finding.subcategory or 'core'}): {finding.title}",
                                    body=pr_body,
                                )
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

                sm.transition_to(State.REPORTING, "Generating final audit and mutation reports")

            # 6. REPORTING: Generate reports
            reports_dir = Path(self.config.reports_dir)
            generate_json_report(run_rec, all_findings, git_actions, verification_runs, reports_dir)
            generate_markdown_report(run_rec, all_findings, git_actions, verification_runs, reports_dir)

            # Update repository memory
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            repository.last_audit_at = now_iso
            # Recalculate health score (100 - critical*25 - high*10 - medium*3 - low*1)
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

            # Complete Run
            sm.transition_to(State.COMPLETED, "Autonomous engineering run finished successfully")
            run_rec.ended_at = now_iso
            run_rec.duration_seconds = round(time.time() - start_time, 2)
            self.db.update_run(run_rec)

            if crit > 0:
                send_desktop_notification(
                    title=f"TENJIN Alert: {repository.full_name}",
                    message=f"Discovered {crit} critical finding(s) requiring attention.",
                    urgency="critical",
                )

            return run_rec

        except Exception as e:
            logger.error("Run %s failed: %s", run_id, e, exc_info=True)
            run_rec.state = State.FAILED
            run_rec.error_message = str(e)
            run_rec.ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            run_rec.duration_seconds = round(time.time() - start_time, 2)
            self.db.update_run(run_rec)
            return run_rec


def from_verification_engine(caps: CapabilityInventory, audit_engine: AuditEngine):
    """Helper to lazily construct VerificationEngine."""
    from tenjin.verification.engine import VerificationEngine
    return VerificationEngine(caps, audit_engine)
