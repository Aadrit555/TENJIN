"""TENJIN Real Git Automation and Repository Version Control.

Executes real, non-simulated Git branch creation, diff hashing, conventional commits,
and safe non-destructive branch pushing adhering to policy boundaries.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from tenjin.core.capabilities import _find_executable
from tenjin.security.redaction import redact_secrets

logger = logging.getLogger("tenjin.git")


class GitAutomationError(Exception):
    """Raised when a Git command or safety check fails."""
    pass


def compute_diff_hash(diff_text: str) -> str:
    """Compute a stable cryptographic digest of a unified git diff.

    Used to detect duplicate executions, replay anomalies, and unexpected worktree state.
    """
    normalized = re.sub(r"\bindex\s+[0-9a-f]+\.\.[0-9a-f]+\b", "index_hash", diff_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class GitRepositoryOperator:
    """Safely executes real Git operations inside an isolated workspace."""

    def __init__(self, workspace_path: Path, git_path: Optional[str] = None):
        self.workspace_path = workspace_path
        self.git_path = git_path or _find_executable("git") or "git"

    def _run(self, args: List[str], timeout: float = 60.0) -> Tuple[int, str, str]:
        """Execute a git command with output capture and timeout."""
        try:
            res = subprocess.run(
                [self.git_path] + args,
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired as e:
            raise GitAutomationError(f"Git command timed out: {' '.join(args)}") from e

    def create_isolated_branch(self, branch_identifier: str) -> str:
        """Create a dedicated autonomous branch named forge/<safe_id>."""
        safe_id = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", branch_identifier)
        branch_name = f"forge/{safe_id}"

        # Checkout new branch
        code, out, err = self._run(["checkout", "-b", branch_name])
        if code != 0:
            raise GitAutomationError(f"Failed to create branch {branch_name}: {redact_secrets(err)}")

        logger.info("Created autonomous branch %s in %s", branch_name, self.workspace_path.name)
        return branch_name

    def stage_files(self, files: List[str]) -> None:
        """Stage specific modified files."""
        if not files:
            return
        code, _, err = self._run(["add"] + files)
        if code != 0:
            raise GitAutomationError(f"Failed to stage files: {redact_secrets(err)}")

    def commit_verified_changes(
        self,
        scope: str,
        description: str,
        finding_id: str,
        run_id: str,
    ) -> str:
        """Commit staged changes using conventional commit format.

        Format: fix(<scope>): <description> [finding_id]
        """
        # Run git diff --check to prevent whitespace and merge conflict errors
        code, _, err = self._run(["diff", "--cached", "--check"])
        if code != 0:
            raise GitAutomationError(f"Git diff --check failed before commit: {redact_secrets(err)}")

        clean_scope = re.sub(r"[^a-zA-Z0-9_\-]", "", scope)[:30] or "core"
        clean_desc = re.sub(r"[\r\n]+", " ", description).strip()[:100]
        commit_msg = f"fix({clean_scope}): {clean_desc}\n\nTENJIN-Finding: {finding_id}\nTENJIN-Run: {run_id}"

        code, out, err = self._run(["commit", "-m", commit_msg])
        if code != 0:
            raise GitAutomationError(f"Git commit failed: {redact_secrets(err)}")

        # Fetch resulting commit SHA
        code, sha, _ = self._run(["rev-parse", "HEAD"])
        if code != 0 or not sha:
            raise GitAutomationError("Failed to retrieve commit SHA after commit")

        logger.info("Created verified commit %s on branch", sha[:8])
        return sha

    def push_branch(self, branch_name: str, remote: str = "origin") -> None:
        """Push autonomous branch to remote repository. Never force-pushes."""
        if branch_name in ["main", "master", "develop"]:
            raise GitAutomationError(f"Security error: refusing to push directly to default branch '{branch_name}'")

        code, out, err = self._run(["push", "-u", remote, branch_name], timeout=120.0)
        if code != 0:
            raise GitAutomationError(f"Git push failed for {branch_name}: {redact_secrets(err)}")

        logger.info("Successfully pushed branch %s to remote %s", branch_name, remote)
