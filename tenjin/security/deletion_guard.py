"""TENJIN Hard Deletion Guard.

Enforces Rule 4 and Rule 27: Strictly prohibits permanent deletion of existing
tracked repository files and assets. Captures immutable baseline manifests,
detects missing tracked files post-agent execution, restores deleted files from
the baseline SHA, and logs deletion violations.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tenjin.memory.database import Database
from tenjin.memory.models import BaselineManifestRecord, DeletionViolationRecord

logger = logging.getLogger("tenjin.security.deletion_guard")


class DeletionViolationError(Exception):
    """Raised when an existing tracked file was deleted during autonomous maintenance."""
    pass


class DeletionGuard:
    """Monitors and enforces preservation of all existing tracked repository assets."""

    def __init__(self, git_path: str = "git"):
        self.git_path = git_path

    def _run_git(self, cwd: Path, args: List[str]) -> Tuple[int, str, str]:
        """Run a git command in the repository workspace."""
        cmd = [self.git_path] + args
        try:
            res = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=60.0,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except Exception as e:
            logger.error("Git execution failed in %s (%s): %s", cwd, " ".join(args), e)
            return 1, "", str(e)

    def capture_baseline(self, repo_path: Path, run_id: str, repository: str) -> BaselineManifestRecord:
        """Capture the immutable manifest of all currently tracked files and their hashes."""
        code, sha_out, _ = self._run_git(repo_path, ["rev-parse", "HEAD"])
        base_sha = sha_out if code == 0 else "HEAD"

        code, files_out, _ = self._run_git(repo_path, ["ls-files"])
        tracked_files: List[str] = [line.strip() for line in files_out.splitlines() if line.strip()]

        file_hashes: Dict[str, str] = {}
        for rel_path in tracked_files:
            full_path = repo_path / rel_path
            if full_path.is_file():
                try:
                    content = full_path.read_bytes()
                    file_hashes[rel_path] = hashlib.sha256(content).hexdigest()
                except Exception as e:
                    logger.debug("Failed to hash file %s: %s", rel_path, e)
                    file_hashes[rel_path] = ""

        manifest = BaselineManifestRecord(
            run_id=run_id,
            repository=repository,
            base_sha=base_sha,
            tracked_files=tracked_files,
            file_hashes=file_hashes,
        )
        logger.info(
            "Captured baseline manifest for %s (run %s): %d tracked files at SHA %s",
            repository,
            run_id,
            len(tracked_files),
            base_sha[:8] if base_sha else "unknown",
        )
        return manifest

    def check_for_deletions(self, repo_path: Path, baseline: BaselineManifestRecord) -> List[str]:
        """Detect any baseline tracked file that has been permanently removed or deleted."""
        deleted_files: List[str] = []

        # 1. Inspect git status for deleted files
        code, status_out, _ = self._run_git(repo_path, ["status", "--porcelain"])
        if code == 0:
            for line in status_out.splitlines():
                if len(line) >= 4:
                    status_flag = line[:2]
                    file_name = line[3:].strip()
                    if "D" in status_flag and file_name in baseline.tracked_files:
                        if file_name not in deleted_files:
                            deleted_files.append(file_name)

        # 2. Inspect filesystem for missing files that existed in baseline
        for rel_file in baseline.tracked_files:
            file_path = repo_path / rel_file
            if not file_path.exists() and rel_file not in deleted_files:
                deleted_files.append(rel_file)

        return deleted_files

    def enforce_and_restore(
        self,
        repo_path: Path,
        baseline: BaselineManifestRecord,
        run_id: str,
        db: Database,
    ) -> bool:
        """Inspect for deletions, restore any deleted files, and record violation.

        Returns True if no deletions occurred.
        Returns False if deletions were detected and restored.
        """
        deleted_files = self.check_for_deletions(repo_path, baseline)
        if not deleted_files:
            return True

        logger.warning(
            "DELETION GUARD TRIGGERED in %s (run %s): %d existing tracked files were deleted: %s",
            baseline.repository,
            run_id,
            len(deleted_files),
            deleted_files,
        )

        # Restore each deleted file from baseline SHA
        for rel_file in deleted_files:
            restore_code, _, restore_err = self._run_git(
                repo_path, ["checkout", baseline.base_sha, "--", rel_file]
            )
            restored = restore_code == 0
            if not restored:
                # If git checkout failed, attempt fallback checkout from HEAD
                self._run_git(repo_path, ["checkout", "HEAD", "--", rel_file])
                restored = (repo_path / rel_file).exists()

            violation = DeletionViolationRecord(
                run_id=run_id,
                repository=baseline.repository,
                deleted_file=rel_file,
                restored=restored,
            )
            db.record_deletion_violation(violation)
            logger.info("Restored deleted tracked file %s (success: %s)", rel_file, restored)

        return False
