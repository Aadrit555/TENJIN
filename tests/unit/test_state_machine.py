"""Unit tests for the 22-state lifecycle state machine."""

import tempfile
from pathlib import Path
import pytest

from tenjin.core.constants import AutonomyLevel, State
from tenjin.memory.database import Database
from tenjin.memory.models import RunRecord
from tenjin.orchestration.state_machine import RunStateMachine, StateMachineError


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = Database(db_path)
    yield db
    Path(db_path).unlink(missing_ok=True)


def test_legal_state_transitions(temp_db):
    run = RunRecord(
        run_id="run_test_sm_1",
        repository="owner/repo",
        state=State.DISCOVERING,
        autonomy_level=AutonomyLevel.LEVEL_1_AUDIT_REPORT,
    )
    temp_db.create_run(run)
    sm = RunStateMachine(run, temp_db)

    # Valid progression
    sm.transition_to(State.QUEUED, "Repository discovered and queued")
    assert sm.current_state == State.QUEUED

    sm.transition_to(State.SELECTING, "Selected for audit")
    assert sm.current_state == State.SELECTING

    sm.transition_to(State.PREPARING, "Workspace setup")
    assert sm.current_state == State.PREPARING

    transitions = temp_db.get_state_transitions("run_test_sm_1")
    assert len(transitions) == 3
    assert transitions[0].from_state == State.DISCOVERING
    assert transitions[0].to_state == State.QUEUED


def test_illegal_state_transition_raises_error(temp_db):
    run = RunRecord(
        run_id="run_test_sm_2",
        repository="owner/repo",
        state=State.QUEUED,
        autonomy_level=AutonomyLevel.LEVEL_1_AUDIT_REPORT,
    )
    temp_db.create_run(run)
    sm = RunStateMachine(run, temp_db)

    # QUEUED directly to COMMITTING is illegal
    with pytest.raises(StateMachineError):
        sm.transition_to(State.COMMITTING, "Attempted illegal jump")
