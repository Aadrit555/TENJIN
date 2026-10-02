"""TENJIN Persistent Scheduler and Concurrency Manager.

Coordinates autonomous execution cycles, enforces a strict mutation concurrency
limit of 1 per repository, and provides persistent pause/resume and emergency stop controls.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Optional, Set

from tenjin.core.config import TenjinConfig
from tenjin.memory.database import Database
from tenjin.memory.models import RepositoryRecord
from tenjin.orchestration.coordinator import RunCoordinator
from tenjin.orchestration.selector import RepositorySelector

logger = logging.getLogger("tenjin.orchestration.scheduler")


class SchedulerState:
    """Thread-safe persistent scheduler control flags."""

    def __init__(self, state_file_dir: Path):
        self.pause_file = state_file_dir / "paused.flag"
        self.emergency_file = state_file_dir / "emergency.flag"

    @property
    def is_paused(self) -> bool:
        return self.pause_file.is_file()

    @property
    def is_emergency_stopped(self) -> bool:
        return self.emergency_file.is_file()

    def pause(self) -> None:
        self.pause_file.touch()
        logger.warning("TENJIN scheduler paused: all new mutation jobs suspended")

    def resume(self) -> None:
        self.pause_file.unlink(missing_ok=True)
        self.emergency_file.unlink(missing_ok=True)
        logger.info("TENJIN scheduler resumed")

    def emergency_stop(self) -> None:
        self.emergency_file.touch()
        self.pause_file.touch()
        logger.critical("EMERGENCY STOP ACTIVATED: All mutations and pushes halted immediately")


class AutonomousScheduler:
    """Manages autonomous scheduling cycles with concurrency bounds."""

    def __init__(
        self,
        db: Database,
        config: TenjinConfig,
        coordinator: RunCoordinator,
        selector: RepositorySelector,
    ):
        self.db = db
        self.config = config
        self.coordinator = coordinator
        self.selector = selector

        state_dir = Path(config.database_path).parent
        self.state_ctrl = SchedulerState(state_dir)
        self._active_repositories: Set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def run_single_cycle(self) -> Optional[str]:
        """Perform a single autonomous cycle: select repository and execute run."""
        if self.state_ctrl.is_emergency_stopped:
            logger.warning("Scheduler cycle aborted: EMERGENCY STOP is active")
            return None

        if self.state_ctrl.is_paused:
            logger.info("Scheduler cycle paused by administrative command")
            return None

        # Autonomously select next repository
        run_id = f"run_{int(time.time())}"
        selection_res = self.selector.select_next_repository(run_id)
        if not selection_res:
            logger.info("No repositories available or all are in cooldown")
            return None

        repo, decision = selection_res

        # Enforce concurrency limit (concurrency = 1 per repository)
        with self._lock:
            if repo.full_name in self._active_repositories:
                logger.warning("Repository %s already has an active mutation lock; skipping", repo.full_name)
                return None
            self._active_repositories.add(repo.full_name)

        try:
            logger.info("Starting autonomous run %s for repository %s", run_id, repo.full_name)
            run_rec = self.coordinator.execute_repository_run(
                repository=repo,
                selection_rationale=f"Score {decision.score:.2f} (stale: {decision.stale_audit_score}, act: {decision.activity_score})",
                custom_run_id=run_id,
            )
            return run_rec.run_id
        finally:
            with self._lock:
                self._active_repositories.discard(repo.full_name)

    def run_daemon_loop(self, poll_interval_seconds: float = 60.0) -> None:
        """Run continuous background loop until stopped."""
        logger.info("Starting TENJIN autonomous scheduler loop (interval: %.1fs)", poll_interval_seconds)
        while not self._stop_event.is_set():
            try:
                self.run_single_cycle()
            except Exception as e:
                logger.error("Error in scheduler loop: %s", e, exc_info=True)

            self._stop_event.wait(timeout=poll_interval_seconds)

    def stop(self) -> None:
        """Signal background loop to terminate gracefully."""
        self._stop_event.set()
