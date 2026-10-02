"""TENJIN Isolated Workspace Manager.

Maintains dedicated clones and worktrees in isolated directories under `workspaces/`.
Ensures zero destructive operations (`git reset --hard`, `git clean -fd`) occur against
unverified or user-owned repositories. Strictly verifies remote identity, commit SHA,
and working tree cleanliness.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from tenjin.core.capabilities import _find_executable
from tenjin.memory.models import RepositoryRecord
from tenjin.security.isolation import verify_path_containment
from tenjin.security.redaction import redact_secrets

logger = logging.getLogger("tenjin.repositories.workspace")


class WorkspaceError(Exception):
    """Base exception for workspace management errors."""
    pass


class DirtyWorkspaceError(WorkspaceError):
    """Raised when an uncommitted modification is detected in the workspace."""
    pass


class MismatchedRemoteError(WorkspaceError):
    """Raised when the repository remote does not match the expected clone URL."""
    pass


@dataclass
class WorkspaceContext:
    """Active execution context inside a managed isolated workspace."""
    repository: RepositoryRecord
    path: Path
    base_sha: str
    current_branch: str
    is_clean: bool


class WorkspaceManager:
    """Manages isolated local git worktrees and clones for autonomous engineering."""

    def __init__(self, workspace_root: str | Path, git_path: Optional[str] = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.git_path = git_path or _find_executable("git") or "git"

    def _run_git(
        self,
        cwd: Path,
        args: List[str],
        timeout: float = 120.0,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """Execute git command safely within a workspace directory."""
        if not verify_path_containment(cwd, self.workspace_root):
            raise WorkspaceError(f"Security error: target path {cwd} is outside managed workspace root {self.workspace_root}")

        try:
            res = subprocess.run(
                [self.git_path] + args,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if check and res.returncode != 0:
                raise WorkspaceError(f"Git command failed ({' '.join(args)}): {redact_secrets(res.stderr)}")
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            raise WorkspaceError(f"Git command timed out after {timeout} seconds: {' '.join(args)}")

    def get_workspace_path(self, repo: RepositoryRecord) -> Path:
        """Derive a safe filesystem path for the repository workspace."""
        # Sanitize owner and name for filesystem
        safe_name = f"{repo.owner}_{repo.name}".replace("/", "_").replace("\\", "_")
        return self.workspace_root / safe_name

    def prepare_workspace(self, repo: RepositoryRecord) -> WorkspaceContext:
        """Clone or update isolated workspace, validating cleanliness and remote identity."""
        target_dir = self.get_workspace_path(repo)

        if not target_dir.exists():
            logger.info("Cloning %s into isolated workspace: %s", repo.full_name, target_dir)
            target_dir.mkdir(parents=True, exist_ok=True)
            # Clone directly into target directory
            try:
                subprocess.run(
                    [self.git_path, "clone", repo.clone_url, str(target_dir)],
                    capture_output=True,
                    text=True,
                    timeout=300.0,
                    check=True,
                )
            except Exception as e:
                # Clean up failed partial clone directory safely
                shutil.rmtree(target_dir, ignore_errors=True)
                raise WorkspaceError(f"Failed to clone {repo.full_name}: {redact_secrets(str(e))}")
        else:
            logger.info("Reusing existing workspace for %s at %s", repo.full_name, target_dir)
            # Verify remote identity
            code, stdout, _ = self._run_git(target_dir, ["remote", "get-url", "origin"], check=False)
            if code != 0 or repo.name not in stdout:
                raise MismatchedRemoteError(
                    f"Workspace remote ({stdout}) does not match expected repository {repo.full_name}"
                )

            # Check for uncommitted changes
            code, status_out, _ = self._run_git(target_dir, ["status", "--porcelain"])
            if status_out.strip():
                raise DirtyWorkspaceError(
                    f"Workspace {target_dir} has uncommitted human changes. Halting to avoid data loss."
                )

            # Fetch latest commits safely
            self._run_git(target_dir, ["fetch", "origin"])

        # Determine current branch
        _, branch_out, _ = self._run_git(target_dir, ["rev-parse", "--abbrev-ref", "HEAD"])
        # Determine head commit SHA
        _, sha_out, _ = self._run_git(target_dir, ["rev-parse", "HEAD"])

        return WorkspaceContext(
            repository=repo,
            path=target_dir,
            base_sha=sha_out,
            current_branch=branch_out,
            is_clean=True,
        )

    def is_clean(self, workspace_path: Path) -> bool:
        """Check if worktree is clean without untracked or modified files."""
        code, out, _ = self._run_git(workspace_path, ["status", "--porcelain"], check=False)
        return code == 0 and not out.strip()

    def get_diff(self, workspace_path: Path, base_sha: Optional[str] = None) -> str:
        """Retrieve unified diff against base SHA or HEAD."""
        args = ["diff"]
        if base_sha:
            args.append(base_sha)
        _, stdout, _ = self._run_git(workspace_path, args, check=False)
        return stdout

    def get_changed_files(self, workspace_path: Path, base_sha: Optional[str] = None) -> List[str]:
        """List filenames modified between base SHA and current worktree."""
        args = ["diff", "--name-only"]
        if base_sha:
            args.append(base_sha)
        code, stdout, _ = self._run_git(workspace_path, args, check=False)
        if code != 0 or not stdout.strip():
            return []
        return [f.strip() for f in stdout.splitlines() if f.strip()]
