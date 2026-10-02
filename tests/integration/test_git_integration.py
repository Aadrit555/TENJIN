"""Integration tests executing real Git operations on temporary local repositories."""

import subprocess
import tempfile
from pathlib import Path
import pytest

from tenjin.git.repository import GitRepositoryOperator, compute_diff_hash
from tenjin.memory.models import RepositoryRecord
from tenjin.repositories.workspace import WorkspaceManager


@pytest.fixture
def real_git_repo():
    """Create a real local Git repository for integration testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_path = Path(tmp_dir) / "test_repo"
        repo_path.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "TENJIN Tester"], check=True)
        subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "tester@tenjin.local"], check=True)

        # Create initial commit
        initial_file = repo_path / "README.md"
        initial_file.write_text("# Test Repo\nInitial content.", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo_path), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "chore: initial commit"], check=True)

        yield repo_path


def test_real_git_branch_commit_and_diff_hash(real_git_repo):
    git_op = GitRepositoryOperator(real_git_repo)

    # 1. Create isolated branch
    branch_name = git_op.create_isolated_branch("run_123_find_456")
    assert branch_name == "forge/run_123_find_456"

    # 2. Modify a file
    target = real_git_repo / "README.md"
    target.write_text("# Test Repo\nFixed content via TENJIN.", encoding="utf-8")

    # 3. Compute diff hash
    diff_text = subprocess.run(
        ["git", "-C", str(real_git_repo), "diff"],
        capture_output=True,
        text=True,
    ).stdout
    assert "Fixed content via TENJIN" in diff_text
    diff_hash = compute_diff_hash(diff_text)
    assert len(diff_hash) == 64

    # 4. Stage and commit
    git_op.stage_files(["README.md"])
    commit_sha = git_op.commit_verified_changes(
        scope="docs",
        description="update readme documentation",
        finding_id="find_456",
        run_id="run_123",
    )

    assert len(commit_sha) == 40

    # 5. Verify git log contains commit message and finding metadata
    log_out = subprocess.run(
        ["git", "-C", str(real_git_repo), "log", "-1"],
        capture_output=True,
        text=True,
    ).stdout
    assert "fix(docs): update readme documentation" in log_out
    assert "TENJIN-Finding: find_456" in log_out
