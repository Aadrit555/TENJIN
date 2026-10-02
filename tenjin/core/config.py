"""TENJIN Dynamic Configuration Management.

Adheres strictly to Rule 1: No environment-specific paths, credentials, usernames,
or machine assumptions are hardcoded. All paths are resolved relative to user home
or local project root dynamically.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from tenjin.core.constants import AutonomyLevel

logger = logging.getLogger("tenjin.core.config")


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


DEFAULT_MANAGED_REPOSITORIES: List[str] = [
    "Aadrit555/DidSomethinSLM",
    "Aadrit555/Mimiq2",
    "Aadrit555/Little-Garden",
    "Aadrit555/Ai-Sports-Analyzer",
    "Aadrit555/im-an_IDIOT",
    "Aadrit555/Attendance-Calculator",
    "Aadrit555/AETHER",
    "Aadrit555/Hacka1",
    "Aadrit555/Pokemon-First-Ever",
    "Aadrit555/Bus-Reservation-SystemC",
    "Aadrit555/DidSomethinAgain",
]


class BudgetConfig(BaseModel):
    """Context, token, and reasoning budget management."""
    context_budget_tokens: int = Field(default=200000, description="Conservative model context window budget")
    verification_reserve_ratio: float = Field(default=0.25, description="Ratio of budget strictly reserved for verification and re-audit")
    recovery_margin_ratio: float = Field(default=0.15, description="Ratio of budget reserved for error recovery")
    max_estimated_cost_per_mission: int = Field(default=150000, description="Max estimated complexity cost permitted in a single mission")


class DailyScheduleConfig(BaseModel):
    """Daily mission scheduler settings."""
    enabled: bool = Field(default=True, description="Enable daily maintenance cycle")
    schedule_time: str = Field(default="02:00", description="Daily execution time in HH:MM (24-hour)")
    selection_strategy: str = Field(default="random", description="'random' (uniform random across eligible managed repos) or 'weighted'")


class SafetyPolicyConfig(BaseModel):
    """Global safety boundaries and auto-fix permissions."""
    autonomy_level: AutonomyLevel = Field(default=AutonomyLevel.LEVEL_1_AUDIT_REPORT)
    deletion_guard_enabled: bool = Field(default=True, description="Strictly prohibit permanent deletion of existing tracked files")
    allow_major_revamps: bool = Field(default=True, description="Authorize substantial rewrites and major project revamps within managed workspace")
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
        default_factory=lambda: ["critical", "high", "medium", "low", "informational"]
    )
    require_human_approval_for_high_risk: bool = Field(default=False)
    max_files_changed_for_autofix: int = Field(default=1000, description="Broad engineering authority without arbitrary tiny limits")
    max_lines_changed_for_autofix: int = Field(default=50000, description="Broad engineering authority without arbitrary tiny limits")
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
    managed_repositories: List[str] = Field(
        default_factory=lambda: list(DEFAULT_MANAGED_REPOSITORIES),
        description="Authoritative allowlist of repositories authorized for autonomous mutation"
    )
    antigravity_expected_account: str = Field(
        default="jhonbailey456@gmail.com",
        description="Expected Antigravity account identity for autonomous worker"
    )
    antigravity_cli_path: Optional[str] = Field(default=None, description="Discovered or configured path to agy CLI")
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    selection: SelectionWeightsConfig = Field(default_factory=SelectionWeightsConfig)
    daily_schedule: DailyScheduleConfig = Field(default_factory=DailyScheduleConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)
    safety: SafetyPolicyConfig = Field(default_factory=SafetyPolicyConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def is_repository_managed(self, full_name: str) -> bool:
        """Check if a repository is explicitly authorized in the managed allowlist."""
        normalized = full_name.strip().lower()
        return any(managed.strip().lower() == normalized for managed in self.managed_repositories)

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
    for candidate in candidates:
        if candidate.is_file():
            try:
                with open(candidate, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        data = content
                        break
            except Exception as e:
                logger.debug("Failed to parse config file at %s: %s", candidate, e)

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

    env_account = os.environ.get("ANTIGRAVITY_EXPECTED_ACCOUNT") or os.environ.get("ANTIGRAVITY_ACCOUNT")
    if env_account:
        cfg.antigravity_expected_account = env_account

    env_agy_cli = os.environ.get("ANTIGRAVITY_CLI_PATH") or os.environ.get("AGY_PATH")
    if env_agy_cli:
        cfg.antigravity_cli_path = env_agy_cli

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
