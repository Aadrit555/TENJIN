"""Unit tests for AutonomousScheduler recovery and controls."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from tenjin.core.config import TenjinConfig
from tenjin.core.constants import State
from tenjin.memory.database import Database
from tenjin.memory.models import RepositoryRecord, RunRecord
from tenjin.orchestration.scheduler import AutonomousScheduler, SchedulerState


def test_scheduler_state_flags():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        state_ctrl = SchedulerState(tmp_path)

        assert not state_ctrl.is_paused
        assert not state_ctrl.is_emergency_stopped

        state_ctrl.pause()
        assert state_ctrl.is_paused
        assert not state_ctrl.is_emergency_stopped

        state_ctrl.resume()
        assert not state_ctrl.is_paused
        assert not state_ctrl.is_emergency_stopped

        state_ctrl.emergency_stop()
        assert state_ctrl.is_emergency_stopped
        assert state_ctrl.is_paused

        state_ctrl.resume()
        assert not state_ctrl.is_emergency_stopped
        assert not state_ctrl.is_paused


def test_scheduler_recovers_interrupted_runs():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test.db"
        db = Database(db_path)

        repo = RepositoryRecord(
            full_name="Aadrit555/Mimiq2",
            owner="Aadrit555",
            name="Mimiq2",
            url="https://github.com/Aadrit555/Mimiq2",
            default_branch="main",
            clone_url="https://github.com/Aadrit555/Mimiq2.git",
            ssh_url="git@github.com:Aadrit555/Mimiq2.git",
            is_managed=True,
        )
        db.upsert_repository(repo)

        # Create an interrupted run stuck in AGENT_RUNNING
        stuck_run = RunRecord(
            run_id="stuck_run_1",
            repository="Aadrit555/Mimiq2",
            state=State.AGENT_RUNNING,
        )
        db.create_run(stuck_run)

        cfg = TenjinConfig(database_path=str(db_path))
        mock_coordinator = MagicMock()
        mock_selector = MagicMock()

        scheduler = AutonomousScheduler(
            db=db,
            config=cfg,
            coordinator=mock_coordinator,
            selector=mock_selector,
        )

        # The startup check should have recovered the run
        recovered_runs = db.list_runs()
        assert len(recovered_runs) == 1
        assert recovered_runs[0].state == State.FAILED
        assert "interrupted" in (recovered_runs[0].error_message or "").lower()
