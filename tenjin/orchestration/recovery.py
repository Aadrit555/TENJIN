"""TENJIN Crash and Reboot State Recovery Engine.

Reconciles persisted database state against actual Git working trees, commit SHAs,
and remotes following unexpected reboots, power losses, or unhandled crashes.
Git state is treated as authoritative.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from tenjin.core.constants import State
from tenjin.memory.database import Database
from tenjin.memory.models import RunRecord
from tenjin.repositories.workspace import WorkspaceManager

logger = logging.getLogger("tenjin.orchestration.recovery")


class CrashRecoveryEngine:
    """Detects and reconciles interrupted runs against authoritative Git state."""

    def __init__(self, db: Database, workspace_mgr: WorkspaceManager):
        self.db = db
        self.workspace_mgr = workspace_mgr

    def recover_incomplete_runs(self) -> List[RunRecord]:
        """Scan SQLite for runs that were interrupted before reaching terminal state."""
        recovered: List[RunRecord] = []
        recent_runs = self.db.list_runs(limit=20)

        terminal_states = {State.COMPLETED, State.FAILED, State.SKIPPED, State.BLOCKED, State.QUARANTINED}

        for run in recent_runs:
            if run.state in terminal_states:
                continue

            logger.warning("Discovered interrupted run %s in state %s. Initiating recovery...", run.run_id, run.state.value)

            # Retrieve repository
            repo = self.db.get_repository(run.repository)
            if not repo:
                run.state = State.FAILED
                run.error_message = "Recovery failed: repository no longer exists in database"
                self.db.update_run(run)
                recovered.append(run)
                continue

            workspace_dir = self.workspace_mgr.get_workspace_path(repo)
            if not workspace_dir.exists():
                run.state = State.FAILED
                run.error_message = "Interrupted run recovered: workspace directory does not exist"
                self.db.update_run(run)
                recovered.append(run)
                continue

            # Check actual Git state
            try:
                is_clean = self.workspace_mgr.is_clean(workspace_dir)
                if not is_clean and run.state in [State.AGENT_RUNNING, State.REPAIRING, State.VERIFYING]:
                    # Unverified modifications in worktree from crashed session
                    run.state = State.QUARANTINED
                    run.error_message = "Interrupted during active mutation: unverified worktree quarantined for safety"
                else:
                    run.state = State.FAILED
                    run.error_message = f"Process interrupted while in state {run.state.value}; safely marked failed on startup"

                self.db.update_run(run)
                recovered.append(run)
            except Exception as e:
                logger.error("Failed during Git reconciliation for %s: %s", run.run_id, e)
                run.state = State.FAILED
                run.error_message = f"Recovery failure: {e}"
                self.db.update_run(run)
                recovered.append(run)

        return recovered
