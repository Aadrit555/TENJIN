# TENJIN Configuration Reference

TENJIN is configured via a global `config.yaml` file and optional repository-level `.tenjin/policy.yaml` files.

---

## Configuration Loading Precedence

1. Explicit `--config <path>` command line argument.
2. `TENJIN_CONFIG` environment variable.
3. `<project_root>/config.yaml`.
4. `~/.tenjin/config.yaml`.
5. Safe dynamic defaults (resolved relative to execution root).

---

## Global Configuration Schema (`config.yaml`)

```yaml
# Directory Paths (Leave empty to dynamically resolve in project root)
workspace_dir: ""    # Directory for isolated clones: ./workspaces
database_path: ""    # Path to SQLite database: ./data/tenjin.db
reports_dir: ""      # Directory for JSON & Markdown reports: ./reports
logs_dir: ""         # Directory for runtime logs: ./logs

github:
  token: null                  # Or via GITHUB_TOKEN env / gh CLI keyring
  include_private: true        # Inspect private repositories accessible to user
  include_forks: false         # Exclude forked repositories from audit pool
  excluded_repositories: []    # Exclude specific repositories (e.g. ["owner/repo"])
  included_topics: []          # Filter repositories by topic if desired
  rate_limit_threshold: 50     # Pause when API quota falls below this threshold

selection:
  stale_audit_weight: 0.35     # Weight for time elapsed since last audit
  activity_weight: 0.25        # Weight for recent commit/push activity
  unresolved_findings_weight: 0.25 # Weight for open critical/high findings
  exploration_weight: 0.15     # Random tie-breaker to prevent starvation
  cooldown_hours: 4.0          # Minimum hours before re-auditing a repository
  starvation_threshold_hours: 48.0 # Hours after which priority spikes

concurrency:
  max_parallel_repositories: 1 # Concurrency lock (must be 1 for mutations)
  max_repair_attempts_per_run: 3 # Max findings attempted in a single run
  max_attempts_per_finding: 2  # Max retries before quarantining a finding

timeouts:
  git_timeout_seconds: 120
  scanner_timeout_seconds: 180
  agent_timeout_seconds: 300
  test_timeout_seconds: 240

safety:
  autonomy_level: 1            # 0: Observe, 1: Audit+Report, 2: Propose, 3: Commit, 4: Push, 5: PR, 6: Merge
  protected_paths:             # Paths the autonomous agent can never modify
    - ".github/workflows/**"
    - "credentials/**"
    - "secrets/**"
    - "*.pem"
    - "*.key"
    - "*.env*"
  excluded_paths:              # Paths ignored during inventory and audit
    - "node_modules/**"
    - "vendor/**"
    - "dist/**"
    - "build/**"
    - ".venv/**"
    - "__pycache__/**"
  allowed_severities_for_autofix:
    - "medium"
    - "low"
    - "informational"
  require_human_approval_for_high_risk: true
  max_files_changed_for_autofix: 5
  max_lines_changed_for_autofix: 150
  auto_push_branch: false      # Push forge/<id> branch to remote
  auto_create_pr: false        # Open pull request on remote
  auto_merge: false            # Auto-merge PR (requires Level 6)

dashboard:
  host: "127.0.0.1"            # Bind strictly to localhost
  port: 8765
  enabled: true
```

---

## Repository Policy (`.tenjin/policy.yaml`)

Individual repositories can restrict permissions by placing a `.tenjin/policy.yaml` file in their root.

> **CRITICAL RULE**: A repository policy can **restrict** permissions, but can **never elevate** autonomy beyond TENJIN's global safety boundaries. Global policy always takes precedence.

Example `.tenjin/policy.yaml`:
```yaml
autonomous_fixes: true
auto_commit: true
auto_push: false
auto_pr: false
allowed_severities:
  - "low"
  - "informational"
protected_paths:
  - "legacy/**"
  - "database/schema.sql"
```
