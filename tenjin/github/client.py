"""TENJIN Real GitHub Client.

Interfaces with GitHub using authenticated GitHub CLI (`gh`) or direct GitHub REST API.
Implements rate limit monitoring, exponential backoff, structured error handling,
and least-privilege token usage.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any, Dict, List, Optional

import httpx

from tenjin.core.capabilities import _find_executable
from tenjin.security.redaction import redact_secrets

logger = logging.getLogger("tenjin.github")


class GitHubClientError(Exception):
    """Base exception for GitHub client operations."""
    pass


class GitHubRateLimitError(GitHubClientError):
    """Raised when GitHub rate limit is exceeded."""
    pass


class GitHubClient:
    """Production GitHub client supporting both GitHub CLI and HTTPS REST API."""

    def __init__(
        self,
        token: Optional[str] = None,
        gh_cli_path: Optional[str] = None,
        rate_limit_threshold: int = 50,
    ):
        self.token = token
        self.gh_cli_path = gh_cli_path or _find_executable("gh")
        self.rate_limit_threshold = rate_limit_threshold
        self._api_base = "https://api.github.com"

    def is_authenticated(self) -> bool:
        """Check whether we have valid credentials via CLI or token."""
        if self.token:
            return True
        if self.gh_cli_path:
            res = subprocess.run(
                [self.gh_cli_path, "auth", "status"],
                capture_output=True,
                text=True,
            )
            return res.returncode == 0
        return False

    def list_accessible_repositories(
        self,
        include_private: bool = True,
        include_forks: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Discover real accessible repositories via GitHub CLI or REST API."""
        # Prefer GitHub CLI if authenticated
        if self.gh_cli_path:
            try:
                cmd = [
                    self.gh_cli_path,
                    "repo",
                    "list",
                    "--limit",
                    str(limit),
                    "--json",
                    "name,nameWithOwner,owner,url,isPrivate,isFork,isArchived,defaultBranchRef,languages,pushedAt,createdAt,updatedAt,description,repositoryTopics",
                ]
                if not include_forks:
                    cmd.append("--no-archived")

                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30.0)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    filtered = []
                    for item in data:
                        if not include_forks and item.get("isFork"):
                            continue
                        if not include_private and item.get("isPrivate"):
                            continue
                        filtered.append(item)
                    return filtered
            except Exception as e:
                logger.warning("GitHub CLI discovery encountered an error: %s. Falling back to REST API.", e)

        # Fallback to REST API if token available
        return self._list_repos_via_rest(include_private, include_forks, limit)

    def _list_repos_via_rest(
        self,
        include_private: bool = True,
        include_forks: bool = False,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query user repositories via GitHub REST API."""
        if not self.token:
            # Attempt to extract token from gh auth token
            if self.gh_cli_path:
                res = subprocess.run([self.gh_cli_path, "auth", "token"], capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    self.token = res.stdout.strip()

        if not self.token:
            raise GitHubClientError("No GitHub authentication found (neither gh CLI auth nor GITHUB_TOKEN)")

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.token}",
            "User-Agent": "TENJIN-Autonomous-Agent",
        }

        visibility = "all" if include_private else "public"
        url = f"{self._api_base}/user/repos?per_page={min(limit, 100)}&visibility={visibility}&sort=pushed"

        retries = 3
        backoff = 2.0
        while retries > 0:
            try:
                resp = httpx.get(url, headers=headers, timeout=20.0)
                if resp.status_code == 403 and "rate limit" in resp.text.lower():
                    raise GitHubRateLimitError("GitHub API rate limit exceeded")
                resp.raise_for_status()
                raw_list = resp.json()

                repos = []
                for r in raw_list:
                    if not include_forks and r.get("fork"):
                        continue
                    if r.get("archived"):
                        continue

                    repos.append(
                        {
                            "name": r.get("name"),
                            "nameWithOwner": r.get("full_name"),
                            "owner": {"login": r.get("owner", {}).get("login", "")},
                            "url": r.get("html_url"),
                            "isPrivate": r.get("private", False),
                            "isFork": r.get("fork", False),
                            "isArchived": r.get("archived", False),
                            "defaultBranchRef": {"name": r.get("default_branch", "main")},
                            "languages": [{"node": {"name": r.get("language")}}] if r.get("language") else [],
                            "pushedAt": r.get("pushed_at"),
                            "createdAt": r.get("created_at"),
                            "updatedAt": r.get("updated_at"),
                            "description": r.get("description"),
                            "repositoryTopics": [{"name": t} for t in r.get("topics", [])],
                        }
                    )
                return repos
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                retries -= 1
                if retries <= 0:
                    raise GitHubClientError(f"GitHub API error: {redact_secrets(str(e))}") from e
                time.sleep(backoff)
                backoff *= 2

        return []

    def create_pull_request(
        self,
        repository: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
    ) -> Dict[str, Any]:
        """Create a real pull request using gh CLI or GitHub REST API."""
        clean_body = redact_secrets(body)

        # Prefer gh CLI
        if self.gh_cli_path:
            try:
                cmd = [
                    self.gh_cli_path,
                    "pr",
                    "create",
                    "--repo",
                    repository,
                    "--head",
                    head_branch,
                    "--base",
                    base_branch,
                    "--title",
                    title,
                    "--body",
                    clean_body,
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30.0)
                if res.returncode == 0:
                    url = res.stdout.strip()
                    return {"url": url, "status": "created"}
                else:
                    logger.warning("gh pr create failed: %s", redact_secrets(res.stderr))
            except Exception as e:
                logger.warning("gh pr create exception: %s", e)

        # Fallback to REST API
        if not self.token and self.gh_cli_path:
            res = subprocess.run([self.gh_cli_path, "auth", "token"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                self.token = res.stdout.strip()

        if not self.token:
            raise GitHubClientError("Unable to create PR: no GitHub authentication token available")

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"token {self.token}",
            "User-Agent": "TENJIN-Autonomous-Agent",
        }
        url = f"{self._api_base}/repos/{repository}/pulls"
        payload = {
            "title": title,
            "head": head_branch,
            "base": base_branch,
            "body": clean_body,
        }

        resp = httpx.post(url, json=payload, headers=headers, timeout=25.0)
        if resp.status_code == 201:
            data = resp.json()
            return {
                "url": data.get("html_url"),
                "number": data.get("number"),
                "status": "created",
            }
        else:
            raise GitHubClientError(f"PR creation failed ({resp.status_code}): {redact_secrets(resp.text)}")
