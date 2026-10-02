"""Unit tests for BudgetPlanner and maintenance mission scheduling."""

import tempfile
from pathlib import Path

from tenjin.core.config import BudgetConfig
from tenjin.core.constants import FindingSeverity, MissionType, RiskLevel, WorkClassification
from tenjin.memory.database import Database
from tenjin.memory.models import FindingRecord
from tenjin.policies.budget import BudgetPlanner


def test_budget_capacity_reservation():
    cfg = BudgetConfig(
        daily_token_budget=100000,
        verification_reserve_pct=0.25,
        recovery_reserve_pct=0.15,
        max_work_items_per_day=5,
    )
    planner = BudgetPlanner(cfg)

    # 100k total: 25k verification reserve, 15k recovery reserve, 60k available execution
    findings = [
        FindingRecord(
            id=f"f{i}",
            repository="Aadrit555/Mimiq2",
            run_id="run_1",
            category="quality",
            subcategory="code_style",
            severity=FindingSeverity.MEDIUM,
            confidence=0.8,
            title=f"Style issue {i}",
            summary="Style violation",
            evidence="Code snippet",
            file="app/main.py",
            risk=RiskLevel.LOW,
            autofix_eligibility=True,
            fingerprint=f"fp{i}",
        )
        for i in range(10)
    ]

    plan = planner.create_maintenance_plan(
        mission_id="mission-001",
        repository="Aadrit555/Mimiq2",
        findings=findings,
        mission_type=MissionType.FULL_MAINTENANCE,
    )

    assert plan.total_daily_budget == 100000
    assert plan.verification_reserve == 25000
    assert plan.recovery_reserve == 15000
    assert plan.available_execution_budget == 60000
    assert plan.allocated_tokens <= 60000
    assert plan.remaining_tokens >= 0
    assert len(plan.selected_work_items) > 0


def test_budget_classification_and_deferral():
    cfg = BudgetConfig(
        daily_token_budget=20000,
        verification_reserve_pct=0.25,
        recovery_reserve_pct=0.15,
        max_work_items_per_day=2,
    )
    planner = BudgetPlanner(cfg)

    # Available execution budget: 20000 - 5000 - 3000 = 12000 tokens
    findings = [
        FindingRecord(
            id="f_crit",
            repository="Aadrit555/Mimiq2",
            run_id="run_1",
            category="security",
            subcategory="sql_injection",
            severity=FindingSeverity.CRITICAL,
            confidence=0.95,
            title="SQL Injection",
            summary="Critical vulnerability in db layer",
            evidence="query = 'SELECT * FROM users WHERE id=' + user_input",
            file="db/queries.py",
            risk=RiskLevel.HIGH,
            autofix_eligibility=True,
            fingerprint="fp_sql",
        ),
        FindingRecord(
            id="f_med_1",
            repository="Aadrit555/Mimiq2",
            run_id="run_1",
            category="quality",
            subcategory="lint",
            severity=FindingSeverity.MEDIUM,
            confidence=0.8,
            title="Lint violation",
            summary="Unused imports",
            evidence="import os",
            file="src/util1.py",
            risk=RiskLevel.LOW,
            autofix_eligibility=True,
            fingerprint="fp_l1",
        ),
        FindingRecord(
            id="f_med_2",
            repository="Aadrit555/Mimiq2",
            run_id="run_1",
            category="quality",
            subcategory="lint",
            severity=FindingSeverity.MEDIUM,
            confidence=0.8,
            title="Lint violation 2",
            summary="Unused imports",
            evidence="import sys",
            file="src/util2.py",
            risk=RiskLevel.LOW,
            autofix_eligibility=True,
            fingerprint="fp_l2",
        ),
    ]

    plan = planner.create_maintenance_plan(
        mission_id="mission-002",
        repository="Aadrit555/Mimiq2",
        findings=findings,
    )

    # High severity SQL injection fits first
    assert len(plan.selected_work_items) >= 1
    assert any(i.classification == WorkClassification.FITS_TODAY for i in plan.selected_work_items)

    # Deferred items exist due to budget or cap
    assert len(plan.deferred_work_items) > 0
    assert any(i.classification == WorkClassification.DEFERRED for i in plan.deferred_work_items)


def test_persist_deferred_work_to_database():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_tenjin.db"
        db = Database(db_path)
        # Register repo first to satisfy foreign key
        from tenjin.memory.models import RepositoryRecord
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

        cfg = BudgetConfig(
            daily_token_budget=10000,
            verification_reserve_pct=0.25,
            recovery_reserve_pct=0.15,
            max_work_items_per_day=1,
        )
        planner = BudgetPlanner(cfg)

        findings = [
            FindingRecord(
                id=f"f_{i}",
                repository="Aadrit555/Mimiq2",
                run_id="run_1",
                category="quality",
                subcategory="lint",
                severity=FindingSeverity.LOW,
                confidence=0.8,
                title=f"Lint finding {i}",
                summary="Summary",
                evidence="Evidence",
                file=f"src/file_{i}.py",
                risk=RiskLevel.LOW,
                autofix_eligibility=True,
                fingerprint=f"fp_{i}",
            )
            for i in range(4)
        ]

        plan = planner.create_maintenance_plan("mission-003", "Aadrit555/Mimiq2", findings)
        saved_records = planner.persist_deferred_work(db, plan)

        assert len(saved_records) > 0
        persisted = db.list_deferred_tasks(repository="Aadrit555/Mimiq2")
        assert len(persisted) == len(saved_records)
        assert persisted[0].repository == "Aadrit555/Mimiq2"
