"""Unit tests for finding fingerprinting, deduplication, and regression promotion."""

import tempfile
from pathlib import Path

import pytest

from tenjin.audit.deduplication import (
    compute_finding_fingerprint,
    deduplicate_and_reconcile_findings,
)
from tenjin.core.constants import FindingSeverity, FindingStatus
from tenjin.memory.database import Database
from tenjin.memory.models import FindingRecord, RunRecord


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path)
    yield db
    Path(db_path).unlink(missing_ok=True)


def test_fingerprint_stability_across_minor_whitespace():
    fp1 = compute_finding_fingerprint("owner/repo", "security", "sqli", "src/db.py", "SELECT * FROM users WHERE id=1")
    fp2 = compute_finding_fingerprint("owner/repo", "security", "sqli", "src/db.py", "  SELECT   *  FROM users WHERE id=1  ")
    assert fp1 == fp2


def test_regression_promotion_fixed_to_recurring(temp_db):
    from tenjin.memory.models import RepositoryRecord
    temp_db.upsert_repository(RepositoryRecord(
        full_name="owner/repo", owner="owner", name="repo",
        url="https://github.com/owner/repo", clone_url="https://github.com/owner/repo.git"
    ))
    run1 = RunRecord(run_id="run_1", repository="owner/repo")
    temp_db.create_run(run1)

    fp = compute_finding_fingerprint("owner/repo", "security", "secret", "app.py", "Hardcoded token")

    # Initial finding detected and later marked FIXED
    initial_f = FindingRecord(
        id="find_001",
        repository="owner/repo",
        run_id="run_1",
        category="security",
        subcategory="secret",
        severity=FindingSeverity.HIGH,
        confidence=1.0,
        title="Hardcoded token",
        summary="Secret token found",
        evidence="Hardcoded token",
        file="app.py",
        fingerprint=fp,
        status=FindingStatus.FIXED,
    )
    temp_db.upsert_finding(initial_f)

    # Subsequent run redetects same issue
    run2 = RunRecord(run_id="run_2", repository="owner/repo")
    temp_db.create_run(run2)

    fresh_finding = FindingRecord(
        id="find_002",
        repository="owner/repo",
        run_id="run_2",
        category="security",
        subcategory="secret",
        severity=FindingSeverity.HIGH,
        confidence=1.0,
        title="Hardcoded token",
        summary="Secret token found",
        evidence="Hardcoded token",
        file="app.py",
        fingerprint=fp,
        status=FindingStatus.OPEN,
    )

    reconciled = deduplicate_and_reconcile_findings(temp_db, "run_2", [fresh_finding])
    assert len(reconciled) == 1
    # Preserved original ID
    assert reconciled[0].id == "find_001"
    # Promoted to RECURRING!
    assert reconciled[0].status == FindingStatus.RECURRING
