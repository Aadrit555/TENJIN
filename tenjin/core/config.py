"""TENJIN Dynamic Configuration Management.

Adheres strictly to Rule 1: No environment-specific paths, credentials, usernames,
or machine assumptions are hardcoded. All paths are resolved relative to user home
or local project root dynamically.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field

from tenjin.core.constants import AutonomyLevel


class GitHubConfig(BaseModel):
    """Configuration for GitHub discovery and API access."""
    token: Optional[str] = Field(default=None, description="GitHub PAT or token (falls back to gh CLI or env)")
    include_private: bool = Field(default=True, description="Discover private repositories accessible to user")
    include_forks: bool = Field(default=False, description="Include forked repositories in audit pool")
    excluded_repositories: List[str] = Field(default_factory=list, description="Repositories excluded by policy")
    included_topics: List[str] = Field(default_factory=list, description="Filter repositories by topic if specified")
    rate_limit_threshold: int = Field(default=50, description="Minimum API quota before pausing calls")


class SelectionWeightsConfig(BaseModel):
    """Configurable weights for autonomous repository selection."""
    stale_audit_weight: float = Field(default=0.35, description="Weight for time since last audit")
    activity_weight: float = Field(default=0.25, description="Weight for recent commit/push activity")
    unresolved_findings_weight: float = Field(default=0.25, description="Weight for open critical/high findings")
    exploration_weight: float = Field(default=0.15, description="Weight for random exploration to avoid starvation")
    cooldown_hours: float = Field(default=4.0, description="Minimum hours before re-auditing a repository")
    starvation_threshold_hours: float = Field(default=48.0, description="Hours after which stale repo priority spikes")


class ConcurrencyConfig(BaseModel):
    """Limits and concurrency bounds."""
    max_parallel_repositories: int = Field(default=1, description="Repository mutation concurrency must be 1")
    max_repair_attempts_per_run: int = Field(default=3, description="Max findings to attempt repairing per run")
    max_attempts_per_finding: int = Field(default=2, description="Max retries for an individual finding before quarantine")


class TimeoutConfig(BaseModel):
    """Subprocess and tool execution timeouts in seconds."""
    git_timeout_seconds: int = Field(default=120)
    scanner_timeout_seconds: int = Field(default=180)
    agent_timeout_seconds: int = Field(default=300)
    test_timeout_seconds: int = Field(default=240)


class SafetyPolicyConfig(BaseModel):
    """Global safety boundaries and auto-fix permissions."""
    autonomy_level: AutonomyLevel = Field(default=AutonomyLevel.LEVEL_1_AUDIT_REPORT)
    protected_paths: List[str] = Field(
        default_factory=lambda: [
            ".github/workflows/**",
            "credentials/**",
            "secrets/**",
            "*.pem",
            "*.key",
            "*.env*",
        ]
    )
    excluded_paths: List[str] = Field(
        default_factory=lambda: [
            "node_modules/**",
            "vendor/**",
            "dist/**",
            "build/**",
            ".venv/**",
            "__pycache__/**",
            ".git/**",
        ]
    )
    allowed_severities_for_autofix: List[str] = Field(
        default_factory=lambda: ["medium", "low", "informational"]
    )
    require_human_approval_for_high_risk: bool = Field(default=True)
    max_files_changed_for_autofix: int = Field(default=5)
    max_lines_changed_for_autofix: int = Field(default=150)
    auto_push_branch: bool = Field(default=False)
    auto_create_pr: bool = Field(default=False)
    auto_merge: bool = Field(default=False)


class DashboardConfig(BaseModel):
    """Local operational dashboard server configuration."""
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8765)
    enabled: bool = Field(default=True)


class NotificationConfig(BaseModel):
    """Desktop notification settings."""
    desktop_enabled: bool = Field(default=True)
    sound_enabled: bool = Field(default=False)


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = Field(default="INFO")
    json_format: bool = Field(default=False)
    max_bytes: int = Field(default=10 * 1024 * 1024)
    backup_count: int = Field(default=5)


class TenjinConfig(BaseModel):
    """Root configuration for TENJIN."""
    workspace_dir: str = Field(default="", description="Path for isolated repository worktrees")
    database_path: str = Field(default="", description="Path to SQLite database")
    reports_dir: str = Field(default="", description="Path to generated reports directory")
    logs_dir: str = Field(default="", description="Path to logs directory")
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    selection: SelectionWeightsConfig = Field(default_factory=SelectionWeightsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    safety: SafetyPolicyConfig = Field(default_factory=SafetyPolicyConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def sanitized_dict(self) -> Dict[str, Any]:
        """Return configuration dictionary with all secrets and credentials stripped."""
        data = self.model_dump()
        if data.get("github", {}).get("token"):
            data["github"]["token"] = "REDACTED"
        return data


def resolve_base_directory() -> Path:
    """Resolve active base directory without hardcoded user paths."""
    # Priority: TENJIN_HOME environment variable > current working directory if inside repo > user home .tenjin
    env_home = os.environ.get("TENJIN_HOME")
    if env_home:
        p = Path(env_home).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    cwd = Path.cwd().resolve()
    if (cwd / "pyproject.toml").exists() or (cwd / ".git").exists():
        return cwd

    default_home = Path.home() / ".tenjin"
    default_home.mkdir(parents=True, exist_ok=True)
    return default_home


def load_config(config_path: Optional[str | Path] = None) -> TenjinConfig:
    """Load configuration from specified file, search paths, or safe dynamic defaults."""
    base_dir = resolve_base_directory()

    candidates: List[Path] = []
    if config_path:
        candidates.append(Path(config_path).resolve())
    else:
        env_cfg = os.environ.get("TENJIN_CONFIG")
        if env_cfg:
            candidates.append(Path(env_cfg).resolve())
        candidates.append(base_dir / "config.yaml")
        candidates.append(base_dir / "config" / "config.yaml")
        candidates.append(Path.home() / ".tenjin" / "config.yaml")

    data: Dict[str, Any] = {}
    found_file = False
    for candidate in candidates:
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        data = content
                        found_file = True
                        break
            except Exception:
                pass

    cfg = TenjinConfig(**data)

    # Dynamic path assignment if not explicitly specified
    if not cfg.workspace_dir:
        cfg.workspace_dir = str(base_dir / "workspaces")
    if not cfg.database_path:
        cfg.database_path = str(base_dir / "data" / "tenjin.db")
    if not cfg.reports_dir:
        cfg.reports_dir = str(base_dir / "reports")
    if not cfg.logs_dir:
        cfg.logs_dir = str(base_dir / "logs")

    # Ensure required parent directories exist
    Path(cfg.workspace_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.database_path).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.reports_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.logs_dir).mkdir(parents=True, exist_ok=True)

    # Environment variable overrides
    env_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env_token:
        cfg.github.token = env_token

    return cfg


def save_config(cfg: TenjinConfig, destination: Optional[str | Path] = None) -> Path:
    """Save configuration to disk in YAML format."""
    base_dir = resolve_base_directory()
    dest = Path(destination).resolve() if destination else (base_dir / "config.yaml")
    dest.parent.mkdir(parents=True, exist_ok=True)

    data = cfg.model_dump()
    with open(dest, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    return dest
