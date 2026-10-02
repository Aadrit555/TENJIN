"""TENJIN Persistent Lifecycle State Machine.

Manages all 22 explicit states across the repository lifecycle, recording every
transition, reason, and metadata event into SQLite. Guarantees restart safety
and strict transition legality.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from tenjin.core.constants import State
from tenjin.memory.database import Database
from tenjin.memory.models import RunRecord, StateTransitionRecord

logger = logging.getLogger("tenjin.orchestration.state_machine")


# Valid outgoing transitions for each lifecycle state
LEGAL_TRANSITIONS: Dict[State, Set[State]] = {
    State.DISCOVERING: {State.QUEUED, State.FAILED},
    State.QUEUED: {State.SELECTING, State.BLOCKED, State.SKIPPED},
    State.SELECTING: {State.PREPARING, State.SKIPPED, State.FAILED},
    State.PREPARING: {State.SYNCING, State.INVENTORYING, State.BLOCKED, State.FAILED},
    State.SYNCING: {State.INVENTORYING, State.FAILED},
    State.INVENTORYING: {State.AUDITING, State.FAILED},
    State.AUDITING: {State.PLANNING, State.FAILED},
    State.PLANNING: {State.WAITING_FOR_AGENT, State.REPORTING, State.COMPLETED, State.SKIPPED},
    State.WAITING_FOR_AGENT: {State.AGENT_RUNNING, State.BLOCKED, State.FAILED},
    State.AGENT_RUNNING: {State.VERIFYING, State.FAILED, State.QUARANTINED},
    State.VERIFYING: {State.READY_TO_COMMIT, State.REPAIRING, State.REPORTING, State.FAILED},
    State.REPAIRING: {State.REVERIFYING, State.FAILED, State.QUARANTINED},
    State.REVERIFYING: {State.READY_TO_COMMIT, State.FAILED, State.QUARANTINED},
    State.READY_TO_COMMIT: {State.COMMITTING, State.BLOCKED, State.FAILED},
    State.COMMITTING: {State.PUSHING, State.REPORTING, State.FAILED},
    State.PUSHING: {State.REPORTING, State.FAILED},
    State.REPORTING: {State.COMPLETED, State.FAILED},
    State.COMPLETED: {State.QUEUED},
    State.SKIPPED: {State.QUEUED},
    State.BLOCKED: {State.QUEUED},
    State.FAILED: {State.QUEUED},
    State.QUARANTINED: {State.QUEUED},
}


class StateMachineError(Exception):
    """Raised when an illegal state transition is attempted."""
    pass


class RunStateMachine:
    """Controls transitions and persistence for a single autonomous run."""

    def __init__(self, run: RunRecord, db: Database):
        self.run = run
        self.db = db
        self.current_state = run.state

    def transition_to(
        self,
        new_state: State,
        reason: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Execute a state transition, persist the audit record, and update run status."""
        # Check legality (allow transition to FAILED or BLOCKED from any state)
        if new_state not in [State.FAILED, State.BLOCKED]:
            allowed = LEGAL_TRANSITIONS.get(self.current_state, set())
            if new_state not in allowed:
                raise StateMachineError(
                    f"Illegal state transition from {self.current_state.value} to {new_state.value} for run {self.run.run_id}"
                )

        old_state = self.current_state
        self.current_state = new_state
        self.run.state = new_state

        transition_rec = StateTransitionRecord(
            run_id=self.run.run_id,
            repository=self.run.repository,
            from_state=old_state,
            to_state=new_state,
            reason=reason,
            metadata=metadata or {},
        )

        self.db.record_state_transition(transition_rec)
        self.db.update_run(self.run)

        logger.info(
            "State transition for run %s: %s -> %s (Reason: %s)",
            self.run.run_id,
            old_state.value,
            new_state.value,
            reason,
        )
