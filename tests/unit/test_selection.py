"""Unit tests for autonomous repository selection."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tenjin.core.config import TenjinConfig
from tenjin.memory.database import Database
from tenjin.memory.models import RepositoryRecord
from tenjin.orchestration.selector import RepositorySelector


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path)
    yield db
    Path(db_path).unlink(missing_ok=True)


def test_selection_prioritizes_never_audited_repository(temp_db):
    cfg = TenjinConfig()
    now = datetime.now(timezone.utc)

    # Repo A audited 1 hour ago (in cooldown)
    repo_a = RepositoryRecord(
        full_name="org/audited_recently",
        owner="org",
        name="audited_recently",
        url="https://github.com/org/audited_recently",
        clone_url="https://github.com/org/audited_recently.git",
        last_audit_at=(now - timedelta(hours=1)).isoformat(),
    )
    temp_db.upsert_repository(repo_a)

    # Repo B never audited
    repo_b = RepositoryRecord(
        full_name="org/never_audited",
        owner="org",
        name="never_audited",
        url="https://github.com/org/never_audited",
        clone_url="https://github.com/org/never_audited.git",
        last_audit_at=None,
    )
    temp_db.upsert_repository(repo_b)

    selector = RepositorySelector(temp_db, cfg)
    selected = selector.select_next_repository("test_run")
    assert selected is not None
    chosen_repo, decision = selected
    assert chosen_repo.full_name == "org/never_audited"
    assert decision.stale_audit_score == 1.0


def test_daily_managed_repository_random_selection(temp_db):
    cfg = TenjinConfig()
    cfg.managed_repositories = [
        "Aadrit555/DidSomethinSLM",
        "Aadrit555/Mimiq2",
        "Aadrit555/Little-Garden",
    ]
    selector = RepositorySelector(temp_db, cfg)

    # Automatically populates managed candidates and selects one uniformly at random
    selected = selector.select_daily_managed_repository("mission-random-1")
    assert selected is not None
    repo, decision = selected
    assert repo.full_name in cfg.managed_repositories
    assert decision.factors["selection_strategy"] == "uniform_random_managed"
    assert decision.factors["pool_size"] == 3
