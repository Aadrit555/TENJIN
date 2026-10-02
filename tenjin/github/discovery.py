"""TENJIN Dynamic Repository Discovery Service.

Polls GitHub for real accessible repositories, extracts metadata,
applies exclusion and policy filters, and synchronizes state into SQLite memory.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from tenjin.core.config import TenjinConfig
from tenjin.github.client import GitHubClient
from tenjin.memory.database import Database
from tenjin.memory.models import RepositoryRecord

logger = logging.getLogger("tenjin.github.discovery")


class RepositoryDiscoveryService:
    """Discovers accessible user repositories and persists metadata."""

    def __init__(self, client: GitHubClient, database: Database, config: TenjinConfig):
        self.client = client
        self.db = database
        self.config = config

    def discover_and_sync(self) -> List[RepositoryRecord]:
        """Perform real discovery, filter repositories, and persist in SQLite."""
        logger.info("Initiating dynamic GitHub repository discovery...")
        raw_repos = self.client.list_accessible_repositories(
            include_private=self.config.github.include_private,
            include_forks=self.config.github.include_forks,
        )

        discovered: List[RepositoryRecord] = []

        for r in raw_repos:
            full_name = r.get("nameWithOwner") or f"{r.get('owner', {}).get('login')}/{r.get('name')}"
            if not full_name:
                continue

            # Policy exclusions
            if full_name in self.config.github.excluded_repositories:
                logger.info("Excluding repository by configuration policy: %s", full_name)
                continue

            if r.get("isArchived"):
                logger.debug("Skipping archived repository: %s", full_name)
                continue

            # Topic filtering if specified
            topics = [t["name"] if isinstance(t, dict) else str(t) for t in r.get("repositoryTopics", [])]
            if self.config.github.included_topics:
                if not any(t in self.config.github.included_topics for t in topics):
                    logger.debug("Skipping repository %s: missing required topics", full_name)
                    continue

            # Determine primary language
            lang: Optional[str] = None
            langs = r.get("languages", [])
            if langs and isinstance(langs, list) and len(langs) > 0:
                first = langs[0]
                if isinstance(first, dict):
                    lang = first.get("node", {}).get("name") or first.get("name")

            default_branch = "main"
            def_branch_ref = r.get("defaultBranchRef")
            if def_branch_ref and isinstance(def_branch_ref, dict):
                default_branch = def_branch_ref.get("name") or "main"

            clone_url = r.get("url") + ".git" if r.get("url") else f"https://github.com/{full_name}.git"

            owner = r.get("owner", {}).get("login") if isinstance(r.get("owner"), dict) else full_name.split("/")[0]

            record = RepositoryRecord(
                full_name=full_name,
                owner=owner,
                name=r.get("name", full_name.split("/")[-1]),
                url=r.get("url", f"https://github.com/{full_name}"),
                clone_url=clone_url,
                default_branch=default_branch,
                is_private=bool(r.get("isPrivate", False)),
                is_fork=bool(r.get("isFork", False)),
                is_archived=bool(r.get("isArchived", False)),
                language=lang,
                topics=topics,
                created_at=r.get("createdAt"),
                updated_at=r.get("updatedAt"),
                pushed_at=r.get("pushedAt"),
                permissions={},
                status="active",
            )

            self.db.upsert_repository(record)
            discovered.append(record)

        logger.info("Discovered and synchronized %d active repositories", len(discovered))
        return discovered
