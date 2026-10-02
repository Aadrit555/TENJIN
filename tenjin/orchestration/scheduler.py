"""TENJIN Persistent Scheduler and Concurrency Manager.

Coordinates autonomous daily maintenance missions, enforces strict concurrency
bounds (1 mutation per repository), manages crash/restart recovery, handles
token/quota wait periods, and provides persistent pause/resume and emergency stop controls.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Set

from tenjin.core.config import TenjinConfig
from tenjin.core.constants import State
from tenjin.memory.database import Database
from tenjin.orchestration.coordinator import RunCoordinator
from tenjin.orchestration.selector import RepositorySelector

logger = logging.getLogger("tenjin.orchestration.scheduler")


class SchedulerState:
    """Thread-safe persistent scheduler control flags."""

    def __init__(self, state_file_dir: Path):
        self.state_file_dir = state_file_dir
        self.state_file_dir.mkdir(parents=True, exist_ok=True)
        self.pause_file = state_file_dir / "paused.flag"
        self.emergency_file = state_file_dir / "emergency.flag"

    @property
    def is_paused(self) -> bool:
        """Check if scheduler is paused (soft suspension of new runs)."""
        return self.pause_file.is_file()

    @property
    def is_emergency_stopped(self) -> bool:
        """Check if emergency stop is engaged (hard immediate block)."""
        return self.emergency_file.is_file()

    def pause(self) -> None:
        """Pause scheduling of new missions."""
        self.pause_file.touch()
        logger.warning("TENJIN scheduler paused: all new mutation jobs suspended")

    def resume(self) -> None:
        """Resume normal scheduling."""
        self.pause_file.unlink(missing_ok=True)
        self.emergency_file.unlink(missing_ok=True)
        logger.info("TENJIN scheduler resumed")

    def emergency_stop(self) -> None:
        """Hard emergency stop: halt immediately and block any further operations."""
        self.emergency_file.touch()
        self.pause_file.touch()
        logger.critical("EMERGENCY STOP ACTIVATED: All mutations, commits, and pushes halted immediately")


class AutonomousScheduler:
    """Manages autonomous scheduling cycles with concurrency bounds and recovery."""

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

        state_dir = Path(config.database_path).parent if config.database_path else Path.cwd()
        self.state_ctrl = SchedulerState(state_dir)
        self._active_repositories: Set[str] = set()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Perform startup recovery check
        self.recover_interrupted_runs()

    def recover_interrupted_runs(self) -> int:
        """Detect and cleanly recover any runs interrupted by host reboot or unexpected process exit."""
        terminal_states = [
            State.COMPLETED.value,
            State.FAILED.value,
            State.SKIPPED.value,
            State.BLOCKED.value,
            State.QUARANTINED.value,
        ]
        recovered_count = 0
        try:
            active_runs = self.db.list_runs()
            now_iso = datetime.now(timezone.utc).isoformat()

            for run in active_runs:
                if run.state.value not in terminal_states:
                    logger.warning(
                        "Recovering interrupted run %s (was in state %s) from previous session",
                        run.run_id,
                        run.state.value,
                    )
                    run.state = State.FAILED
                    run.error_message = "Execution interrupted by system reboot or worker process termination; cleanly recovered."
                    run.ended_at = now_iso
                    self.db.update_run(run)
                    recovered_count += 1

            if recovered_count > 0:
                logger.info("Cleanly recovered %d interrupted runs on scheduler startup", recovered_count)
        except Exception as e:
            logger.error("Failed to run startup recovery check: %s", e)

        return recovered_count

    def run_daily_mission(self) -> Optional[str]:
        """Execute exactly one daily maintenance mission on a randomly selected managed repository."""
        if self.state_ctrl.is_emergency_stopped:
            logger.warning("Daily mission aborted: EMERGENCY STOP is active")
            return None

        if self.state_ctrl.is_paused:
            logger.info("Daily mission suspended: scheduler is paused")
            return None

        mission_id = f"mission_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Uniform random selection from the authoritative 11-repository allowlist
        selection_res = self.selector.select_daily_managed_repository(mission_id)
        if not selection_res:
            logger.warning("No eligible managed repositories available for today's mission")
            return None

        repo, decision = selection_res

        # Concurrency safety lock: strictly 1 mutation per repository at any time
        with self._lock:
            if repo.full_name in self._active_repositories:
                logger.warning("Repository %s already has an active mutation lock; skipping", repo.full_name)
                return None
            self._active_repositories.add(repo.full_name)

        try:
            logger.info("Starting daily maintenance mission %s for managed repository %s", mission_id, repo.full_name)
            run_rec = self.coordinator.execute_repository_run(
                repository=repo,
                selection_rationale=f"Daily random selection from managed allowlist (pool size: {decision.factors.get('pool_size', 11)})",
                custom_run_id=mission_id,
            )
            return run_rec.run_id
        finally:
            with self._lock:
                self._active_repositories.discard(repo.full_name)

    def run_single_cycle(self) -> Optional[str]:
        """Perform a single autonomous cycle: delegates to daily mission or weighted selection."""
        if self.config.schedule.selection_strategy == "random":
            return self.run_daily_mission()

        if self.state_ctrl.is_emergency_stopped or self.state_ctrl.is_paused:
            return None

        run_id = f"run_{int(time.time())}"
        selection_res = self.selector.select_next_repository(run_id)
        if not selection_res:
            return None

        repo, decision = selection_res
        with self._lock:
            if repo.full_name in self._active_repositories:
                return None
            self._active_repositories.add(repo.full_name)

        try:
            run_rec = self.coordinator.execute_repository_run(
                repository=repo,
                selection_rationale=f"Score {decision.score:.2f}",
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
