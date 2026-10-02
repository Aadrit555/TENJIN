```text
 ███████████ ██████████ ██████   █████       █████ █████ ██████   █████
░█░░░███░░░█░░███░░░░░█░░██████ ░░███       ░░███ ░░███ ░░██████ ░░███ 
░   ░███  ░  ░███  █ ░  ░███░███ ░███        ░███  ░███  ░███░███ ░███ 
    ░███     ░██████    ░███░░███░███        ░███  ░███  ░███░░███░███ 
    ░███     ░███░░█    ░███ ░░██████        ░███  ░███  ░███ ░░██████ 
    ░███     ░███ ░   █ ░███  ░░█████  ███   ░███  ░███  ░███  ░░█████ 
    █████    ██████████ █████  ░░█████░░████████   █████ █████  ░░█████
   ░░░░░    ░░░░░░░░░░ ░░░░░    ░░░░░  ░░░░░░░░   ░░░░░ ░░░░░    ░░░░░ 
```

A local autonomous software-engineering system that watches your GitHub repositories, identifies code needing maintenance, audits repositories for real issues, delegates fixes to Antigravity, independently verifies modifications, and commits verified work.

[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests Passing](https://img.shields.io/badge/tests-24%20passed-brightgreen.svg)](tests/)
[![Lint: Ruff](https://img.shields.io/badge/linter-ruff%20clean-black.svg)](https://docs.astral.sh/ruff/)
[![Type Checker: Mypy](https://img.shields.io/badge/type--check-mypy%20strict-blue.svg)](https://mypy-lang.org/)

<p align="center">
  <img src="assets/tenjin-hero.jpg" alt="Tenjin - Kami of Scholarship and Learning" width="320">
</p>

TENJIN is a local tool that looks after your GitHub repositories. It finds repositories that need attention, checks the code for real problems, sends valid fixes to Antigravity, checks the changes independently, and can commit and push the verified work.

---

## 1. What TENJIN Does

TENJIN continuously runs a disciplined maintenance cycle across your repositories on your local workstation:

```text
GitHub
  ↓
Find repositories (via GitHub CLI or REST API)
  ↓
Choose one (based on staleness, open findings, and recent changes)
  ↓
Audit it (using a 10-layer real engineering inspection)
  ↓
Find real issues (syntax errors, leaked secrets, linter failures, broken tests)
  ↓
Send repair task to Antigravity (bounded prompt with file scope and evidence)
  ↓
Apply changes (in an isolated Git workspace)
  ↓
Run tests (independent pytest, npm test, cargo test, etc.)
  ↓
Check the fix again (verify diff, check linters, confirm finding resolved)
  ↓
Commit (conventional commit on a forge/<run_id> branch)
  ↓
Push branch / create PR (only if allowed by repository policy)
  ↓
Save the result (SQLite memory with audit logs and health history)
  ↓
Choose another repository
```

Every action is real. TENJIN does not simulate agent responses, does not generate fake commits, does not fabricate passing tests, and does not alter repositories outside configured policies.

---

## 2. Why It Exists

Most developers have multiple repositories that gradually collect:

* broken test suites caused by dependency changes
* leaked secrets or unredacted credentials
* outdated dependencies with known vulnerabilities
* bad or swallowed error handling
* missing type annotations and linting errors
* unfinished documentation or incorrect README instructions
* stale configuration files
* code that was written months ago and never inspected again

Keeping dozens of personal or organization projects healthy takes hours of routine work. TENJIN handles that routine maintenance automatically on your workstation.

TENJIN is not designed to create meaningless commits or artificially inflate GitHub contribution graphs. It only creates a Git commit when it discovers a genuine problem, produces an actual fix, and independently proves the fix works through tests and static analysis.

---

## 3. How It Works

TENJIN runs as a local background process and coordinates ten distinct stages:

### 1. Discover
TENJIN queries your GitHub account using the official GitHub CLI (`gh`) or a configured `GITHUB_TOKEN`. It downloads metadata for every repository you can access—including visibility, default branch, stars, and open issues—and synchronizes the metadata into a local SQLite database.

### 2. Select
TENJIN selects the next repository to audit using an anti-starvation scoring algorithm. Repositories that have never been audited, have been neglected the longest, or currently hold unresolved findings receive highest priority.

### 3. Prepare
TENJIN creates an isolated clone of the selected repository in a dedicated local directory (`workspaces/<owner>_<repo>`). If a clone already exists, TENJIN checks for uncommitted human changes. If uncommitted work is found, TENJIN immediately halts the run to prevent any data loss. If clean, it fetches and fast-forwards the default branch.

### 4. Audit
TENJIN inspects the repository using ten independent layers:
1. Manifest and file inventory
2. Syntax validation and AST parsing
3. Security and secret scanning
4. Dependency declarations and lockfiles
5. Linters and type checkers (Ruff, Mypy, ESLint, Clippy, etc.)
6. Test suite discovery and test runner execution
7. Cyclomatic complexity and error-handling analysis
8. Documentation and instruction verification
9. CI workflow configuration checks
10. Structural project analysis

### 5. Repair
When an actionable finding matches the repository's autonomy policy, TENJIN prepares a bounded task package for Antigravity. It extracts the code evidence, allowed file boundaries, and reproduction steps, and invokes the local Antigravity CLI (`agy.exe`).

### 6. Verify
TENJIN never trusts the agent's own assessment of whether its code worked. An independent verification engine validates:
* that the agent only touched files within its allowed boundary
* that no new secrets or high-entropy tokens were introduced
* that all relevant test suites pass
* that linters and type checkers exit cleanly
* that the targeted finding is resolved upon re-auditing the workspace

### 7. Commit
If and only if verification succeeds, TENJIN switches to a dedicated branch (`forge/<run_id>`) and creates a standard conventional commit:
```text
fix(security): sanitize exposed credential in auth.py [tenjin-run: run_1790900501]
```

### 8. Push / Pull Request
Depending on the configured autonomy level:
* **Level 1–3**: Work remains local or committed locally.
* **Level 4**: The branch is pushed to GitHub.
* **Level 5**: A GitHub Pull Request is created with full audit evidence and verification logs.
* **Level 6**: Automated merge (strictly opt-in with explicit branch protections).

### 9. Remember
Every run, finding, test result, state transition, and Git operation is recorded in a local SQLite database with write-ahead logging (WAL). If a previously resolved finding reappears in future audits, TENJIN flags it as a recurring regression.

### 10. Repeat
TENJIN updates the repository's health score, releases workspace locks, and proceeds to the next repository in the queue.

---

## 4. Main Features

| Feature | What it does |
|---|---|
| **Dynamic Discovery** | Discovers accessible repositories via GitHub CLI keyring or REST API without hardcoding usernames. |
| **Toolchain Inventory** | Dynamically detects available host compilers, linters, runtimes, and security scanners. |
| **Repository Selector** | Uses mathematical anti-starvation ranking to ensure all repositories receive maintenance. |
| **Isolated Workspaces** | Clones repositories into isolated directories without touching your main working trees. |
| **10-Layer Audit Engine** | Performs AST parsing, secret scanning, dependency checks, test runs, and linter passes. |
| **Deterministic Fingerprints** | Generates normalized SHA-256 hashes for each finding to track recurrence and fixes across runs. |
| **Antigravity Delegation** | Dispatches bounded repair tasks with strict JSON schemas to the local Antigravity engine. |
| **Independent Verification** | Runs automated tests, linter passes, diff reviews, and re-audits before accepting any change. |
| **Conventional Git Ops** | Creates isolated `forge/<id>` branches, conventional commits, and verified pull requests. |
| **Hierarchical Policies** | Resolves policies hierarchically: Global defaults → Repository overrides → Finding rules. |
| **Instruction Hierarchy** | Defends against prompt injection by isolating repository instructions from system rules. |
| **Secret Redaction** | Automatically masks API tokens, private keys, and passwords before logging or storing findings. |
| **Data Loss Prevention** | Halts immediately if uncommitted human changes are detected in an active workspace. |
| **Persistent SQLite Memory** | Stores complete audit history, metrics, and state transitions in SQLite with WAL mode. |
| **Background Scheduler** | Runs continuously as a background process with PID locking and Windows Task Scheduler support. |
| **Operational Web Console** | Serves an informational REST API and telemetry web console on port 8765. |
| **Desktop Notifications** | Sends real native toast notifications for critical security findings. |

---

## 5. Repository Selection

TENJIN does not pick repositories from a hardcoded list. It evaluates all accessible repositories and calculates a dynamic priority score for each one:

$$\text{Priority Score} = S_{\text{staleness}} + W_c \cdot N_{\text{critical}} + W_h \cdot N_{\text{high}} + W_m \cdot N_{\text{medium}} - P_{\text{failures}} + J_{\text{jitter}}$$

* **Staleness ($S_{\text{staleness}}$)**: Repositories that have never been audited receive maximum priority ($100{,}000$ points). For previously audited repositories, priority scales with hours elapsed since the last audit.
* **Open Findings ($N$)**: Repositories with open security or reliability issues receive higher priority based on finding severity.
* **Failure Penalty ($P_{\text{failures}}$)**: Exponential backoff is applied to repositories where recent repair attempts failed, preventing repetitive retry loops.
* **Anti-Starvation Jitter ($J_{\text{jitter}}$)**: A small random exploration factor ensures low-activity repositories are periodically audited even when high-activity repositories exist.

Selection policies can also explicitly pin specific repositories, exclude forks, or filter repositories by visibility.

---

## 6. Auditing

TENJIN audits repositories using ten real inspection layers:

```text
┌────────────────────────────────────────────────────────┐
│               TENJIN 10-LAYER AUDIT ENGINE             │
├────┬───────────────────────┬───────────────────────────┤
│ 1  │ Inventory             │ Manifests, AST, structure │
│ 2  │ Syntax & Build        │ ast.parse, compilation    │
│ 3  │ Security & Secrets    │ PATs, tokens, keys, regex │
│ 4  │ Dependencies          │ Lockfiles, vulnerable pkg │
│ 5  │ Linters & Typing      │ Ruff, Mypy, ESLint, etc.  │
│ 6  │ Test Suites           │ Pytest, npm test, cargo   │
│ 7  │ Quality & Complexity  │ Complexity, swallowed err │
│ 8  │ Documentation         │ README accuracy, commands │
│ 9  │ CI Workflows          │ GitHub Actions, checks    │
│ 10 │ Project Architecture  │ Layout sanity, circulars  │
└────┴───────────────────────┴───────────────────────────┘
```

Automated analysis can miss subtle bugs. TENJIN is designed to catch concrete, evidence-based defects rather than making speculative claims.

### Real Audit Finding Example

Here is a real finding detected by TENJIN during a live audit of `Aadrit555/TENJIN`:

```text
============================================================
FINDING DETAIL: find_b8c93c97_7a06
============================================================
Repository:    Aadrit555/TENJIN
Category:      security / exposed_credentials
Severity:      CRITICAL (Confidence: 0.95)
Status:        OPEN
File/Line:     tenjin/cli/main.py:154
Risk Level:    CRITICAL
Autofix:       No (Requires human authorization)

Title: Exposed potential GITHUB_TOKEN secret in main.py
Summary:
File contains an unredacted credential matching signature GITHUB_TOKEN.

Evidence:
Match pattern GITHUB_TOKEN detected at line 154 in tenjin/cli/main.py.

Suggested Fix:
Remove hardcoded secret immediately and rotate credentials using environment variables.
============================================================
```

---

## 7. Antigravity Repair

When a finding is marked eligible for automated repair, TENJIN dispatches a repair request to Google Antigravity:

1. **Discovery**: TENJIN locates the Antigravity binary (`agy.exe` on Windows) dynamically from your PATH or user profile directory (`~/.gemini/bin/agy.exe`).
2. **Context Packaging**: TENJIN prepares a strict JSON prompt containing only the necessary file contents, specific finding evidence, allowed line ranges, and reproduction instructions.
3. **Subprocess Isolation**: Antigravity is invoked in headless mode with sanitized environment variables (API keys and parent tokens are stripped).
4. **Structured Output**: Antigravity returns a strictly typed JSON structure containing the files modified, git diff summary, and rationale.
5. **Timeout Handling**: Subprocess execution is enforced with a configurable timeout (default 300 seconds).

TENJIN never marks an issue fixed simply because Antigravity exited with code 0.

---

## 8. Verification

TENJIN enforces an independent five-stage verification pipeline before any modification can proceed to Git:

```text
Antigravity Modification
           │
           ▼
[Check 1: Scope Validation]  ──► Did the agent touch files outside its approved list?
           │ (Pass)
           ▼
[Check 2: Diff Inspection]   ──► Did the agent introduce new secrets or delete critical code?
           │ (Pass)
           ▼
[Check 3: Test Execution]    ──► Do unit and integration tests pass on the modified tree?
           │ (Pass)
           ▼
[Check 4: Linter & Types]    ──► Do project linters (Ruff, ESLint, Mypy) pass cleanly?
           │ (Pass)
           ▼
[Check 5: Post-Fix Re-Audit] ──► Did the targeted finding disappear upon fresh audit?
           │ (Pass)
           ▼
     Approved for Git
```

If any check fails, the workspace is reverted to its base commit (`git checkout -f <base_sha>`), the failure is logged to SQLite, and the finding's retry counter is incremented.

---

## 9. Git Workflow

TENJIN follows a strict branching and commit protocol:

1. **Clean Worktree Check**: Prior to performing work, TENJIN confirms `git status --porcelain` is empty.
2. **Isolated Branch Creation**: Mutations are never committed directly to `main` or `master`. TENJIN creates a dedicated branch:
   ```text
   forge/<run_id>
   ```
3. **Conventional Commits**: Commits follow the Conventional Commits specification with a machine-readable run tag:
   ```text
   fix(security): resolve unredacted database token in config.py [tenjin-run: run_1790900501]
   ```
4. **Verified Push**: If the repository's policy allows branch pushes (`autonomy_level >= 4`), TENJIN pushes the branch to GitHub:
   ```powershell
   git push origin forge/run_1790900501
   ```
5. **Pull Request Generation**: If policy allows pull requests (`autonomy_level >= 5`), TENJIN opens a pull request containing:
   * Finding category and severity
   * Root cause and code evidence
   * Changes made by Antigravity
   * Independent verification logs (test passes, linter output, re-audit results)

---

## 10. Safety

TENJIN is built with safety controls to protect your code and credentials:

### Autonomy Levels

| Level | Name | Permitted Actions |
|---|---|---|
| `0` | **Observe** | Read-only discovery. No code audits or file modifications. |
| `1` | **Audit & Report** | Deep 10-layer audit and report generation. **Default mode**. |
| `2` | **Propose** | Generates proposed repairs and tests them in memory without writing to Git. |
| `3` | **Commit** | Applies verified changes and commits to a local `forge/<id>` branch. |
| `4` | **Push** | Pushes the verified `forge/<id>` branch to the remote GitHub repository. |
| `5` | **Pull Request** | Opens a formal GitHub Pull Request for human review. |
| `6` | **Autonomous Merge** | Merges verified pull requests. Strictly opt-in with explicit branch rules. |

### Data Loss Prevention
If an active workspace contains uncommitted human changes, TENJIN aborts immediately with a `DirtyWorkspaceError`. TENJIN never runs destructive Git commands (`git reset --hard`, `git clean -fd`) on user working trees.

### Instruction Hierarchy & Injection Defense
Repository instruction files (`AGENTS.md`, `CLAUDE.md`, `README.md`) are treated as untrusted data:
* They can provide project-specific build or test hints.
* They **cannot** override TENJIN autonomy levels.
* They **cannot** disable security checks or secret redaction.
* All delimiter tags (`<system>`, `[INSTRUCTION]`) are defanged before prompt construction.

### Secret Redaction
All high-entropy tokens, GitHub personal access tokens (`ghp_...`, `github_pat_...`), Bearer tokens, private keys, and database connection strings are masked across all logs, reports, and database records.

### Emergency Stop
Executing `tenjin emergency-stop` immediately halts scheduling, revokes push authorization, and terminates running subprocesses.

---

## 11. Architecture

```text
tenjin/
├── core/                  # Constants, capabilities, config, and lifecycle
│   ├── capabilities.py    # Dynamic environment and scanner discovery
│   ├── config.py          # Environment-free YAML configuration loader
│   ├── constants.py       # 22 Lifecycle states, autonomy levels, severities
│   └── lifecycle.py       # PID file locking and Task Scheduler integration
├── security/              # Security and containment boundaries
│   ├── isolation.py       # Process environment scrubbing and path containment
│   ├── prompt_injection.py# Prompt sanitization and instruction hierarchy
│   └── redaction.py       # Centralized secret and token masking
├── memory/                # Persistent SQLite data layer
│   ├── database.py        # SQLite engine with WAL mode and foreign keys
│   └── models.py          # Typed Pydantic domain models
├── github/                # GitHub integration
│   ├── client.py          # GitHub CLI keyring client and REST API fallback
│   └── discovery.py       # Dynamic repository discovery service
├── repositories/          # Isolated workspaces and project detection
│   ├── instructions.py    # Safe repository instruction extractor
│   ├── project_detection.py# Multi-ecosystem manifest and AST inspection
│   └── workspace.py       # Managed isolated clones under workspaces/
├── audit/                 # Deep 10-layer real engineering audit
│   ├── deduplication.py   # SHA-256 fingerprinting and regression tracking
│   └── engine.py          # 10-layer audit execution engine
├── policies/              # Policy resolution and risk calculation
│   ├── policy.py          # Hierarchical policy resolver
│   └── risk.py            # Bounded risk evaluation engine
├── agents/                # AI repair delegation
│   ├── antigravity.py     # Local Antigravity CLI runner
│   ├── output_parser.py   # JSON schema validation for agent responses
│   └── task_builder.py    # Evidence packaging and prompt construction
├── verification/          # Independent verification
│   └── engine.py          # Scope checks, diff analysis, linters, re-audit
├── git/                   # Git operations
│   └── repository.py      # Branch management, commits, and verified push
├── orchestration/         # State machine, scheduling, and crash recovery
│   ├── coordinator.py     # Coordinates complete autonomous cycle
│   ├── recovery.py        # Reconciles crashes and orphaned worktrees
│   ├── scheduler.py       # Persistent background worker loop
│   ├── selector.py        # Anti-starvation repository selector
│   └── state_machine.py   # 22-state lifecycle state machine
├── reporting/             # Report generators
│   └── report_generator.py# Structured JSON and Markdown reports in reports/
├── notifications/         # Desktop alert subsystem
│   └── desktop.py         # Native PowerShell toast notifications
├── dashboard/             # Operational monitoring console
│   ├── api.py             # FastAPI REST endpoints
│   ├── server.py          # Uvicorn server launcher
│   └── static/index.html  # Restrained high-density operational UI
└── cli/                   # User-facing CLI
    └── main.py            # Complete suite of 20 CLI commands
```

---

## 12. Requirements

* **Operating System**: Windows 10/11 (AMD64 / ARM64), macOS, or Linux.
* **Python**: Python 3.10, 3.11, or 3.12 (Python 3.12 recommended).
* **Git**: Git 2.30+ installed and available on PATH.
* **GitHub Access**: 
  * GitHub CLI (`gh`) authenticated via `gh auth login`, or
  * `GITHUB_TOKEN` environment variable with `repo` scope.
* **Antigravity CLI**: Antigravity binary (`agy.exe` on Windows) for autonomous repair.
* **Storage**: Minimum 2 GB free disk space for isolated workspaces and SQLite database.

---

## 13. Installation

### Automated PowerShell Setup (Windows)

Run the included PowerShell installer from an elevated or user PowerShell prompt:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\install.ps1
```

The script automatically:
1. Detects Python, Git, and GitHub CLI.
2. Creates an isolated `.venv` using `uv` (or standard `venv`).
3. Installs dependencies and the `tenjin` package in editable mode.
4. Initializes default configuration and SQLite database.
5. Verifies environment capabilities.

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/Aadrit555/TENJIN.git
cd TENJIN

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate      # Windows
source .venv/bin/activate    # Linux / macOS

# Install dependencies and tenjin in editable mode
pip install -e ".[dev]"

# Verify installation
tenjin doctor
```

---

## 14. Authentication

TENJIN authenticates with GitHub using standard local credentials:

### Method A: GitHub CLI (Recommended)
Log in with the official GitHub CLI:
```powershell
gh auth login --scopes "repo,read:org"
```
TENJIN detects the active keyring session automatically without storing raw tokens in configuration files.

### Method B: Environment Variable
Set a personal access token with `repo` scope:
```powershell
$env:GITHUB_TOKEN = "your_github_token"
```

---

## 15. Configuration

TENJIN looks for configuration at `config.yaml` in the working directory or `~/.tenjin/config.yaml`. Copy the template to start:

```powershell
Copy-Item config.example.yaml config.yaml
```

### Configuration Schema

```yaml
global:
  # 0: Observe, 1: Audit+Report, 2: Propose, 3: Commit, 4: Push, 5: PR, 6: Merge
  autonomy_level: 1
  audit_interval_seconds: 3600
  max_parallel_jobs: 1
  daily_commit_budget: 15
  daily_pr_budget: 5
  allowed_severities: ["low", "medium", "high", "critical"]
  require_human_approval_for: ["high", "critical"]

storage:
  database_path: "data/tenjin.db"
  workspace_root: "workspaces"
  reports_dir: "reports"

repositories:
  # Per-repository policy overrides
  "Aadrit555/TENJIN":
    autonomy_level: 1
    branch_pattern: "forge/{run_id}"
    auto_push: false
    auto_pr: false

notifications:
  desktop_enabled: true
  min_notification_severity: "high"
```

---

## 16. Running TENJIN

### 1. Run in Foreground
Execute a single autonomous cycle (discover → select → audit → report):
```powershell
tenjin run
```

### 2. Run Single Audit on a Specific Repository
Audit one repository immediately without waiting for the scheduler:
```powershell
tenjin audit --repo Aadrit555/TENJIN
```

### 3. Run Continuous Background Daemon
Start the continuous autonomous loop:
```powershell
tenjin start
```

### 4. Stop the Daemon
Gracefully shut down the running background process:
```powershell
tenjin stop
```

---

## 17. CLI Commands

| Command | Arguments | Description |
|---|---|---|
| `tenjin doctor` | | Inspects host tools, compilers, scanners, and integrations. |
| `tenjin self-test` | | Runs automated self-tests on database, Git, and secret redaction. |
| `tenjin repos` | | Discovers and synchronizes accessible GitHub repositories. |
| `tenjin status` | | Shows daemon state, lock status, active jobs, and finding counts. |
| `tenjin audit` | `--repo <owner/name>` | Runs a 10-layer audit on a specific repository or next selected. |
| `tenjin run` | | Executes a single full autonomous cycle. |
| `tenjin start` | | Launches the persistent autonomous background scheduler. |
| `tenjin stop` | | Gracefully signals the background scheduler to shut down. |
| `tenjin findings` | `--repo <name>` | Lists open, fixed, and recurring findings. |
| `tenjin finding` | `<finding_id>` | Displays full finding evidence, diffs, and verification history. |
| `tenjin approve` | `<finding_id>` | Manually approves a high-risk finding for automated repair. |
| `tenjin reject` | `<finding_id>` | Rejects or ignores a specific finding. |
| `tenjin pause` | | Temporarily pauses scheduling (active jobs complete safely). |
| `tenjin resume` | | Resumes paused scheduling. |
| `tenjin emergency-stop` | | Immediately halts scheduler and revokes branch push permissions. |
| `tenjin dashboard` | `--port 8765` | Launches the local real-time operational web console. |
| `tenjin backup` | `--out <file>` | Creates a timestamped backup of the SQLite database and policies. |
| `tenjin config` | | Prints effective global and repository configuration. |
| `tenjin install` | | Registers automatic background startup via Windows Task Scheduler. |
| `tenjin uninstall` | | Unregisters background startup from Windows Task Scheduler. |

---

## 18. Dashboard

Launch the local operational console:

```powershell
tenjin dashboard --port 8765
```

Open `http://127.0.0.1:8765` in your browser.

```text
┌────────────────────────────────────────────────────────────────────────┐
│ TENJIN OPERATIONAL DASHBOARD                            [DAEMON: IDLE] │
├───────────────────┬───────────────────┬────────────────┬───────────────┤
│ Active Repos: 24  │ Total Runs: 4     │ Open Findings: │ Commits: 0    │
│                   │                   │ 10 (1 Crit)    │               │
├───────────────────┴───────────────────┴────────────────┴───────────────┤
│ DISCOVERED REPOSITORIES                                                │
│ Repository                       Language     Health  Status   Action  │
│ Aadrit555/TENJIN                 PowerShell   100.0%  AUDITED  [Audit] │
│ Aadrit555/tune-em                Python       100.0%  QUEUED   [Audit] │
│ Aadrit555/academic-agent         Python       100.0%  QUEUED   [Audit] │
│ Aadrit555/DidSomethinSLM         Python       100.0%  QUEUED   [Audit] │
├────────────────────────────────────────────────────────────────────────┤
│ RECENT AUDIT FINDINGS                                                  │
│ find_b8c93c97  [CRITICAL]  Exposed GITHUB_TOKEN secret in main.py      │
│ find_4bc33a80  [LOW]       Function exceeds 120 lines in detection.py │
└────────────────────────────────────────────────────────────────────────┘
```

The web console provides:
* Real-time telemetry via REST API endpoints (`/api/v1/system/status`, `/api/v1/findings`, `/api/v1/runs`).
* Complete finding evidence viewer with syntax-highlighted code contexts.
* Finding approval and rejection controls.
* Zero external cloud telemetry; all data is served directly from local SQLite.

---

## 19. Background Operation

TENJIN is designed to start when you log in and run silently in the background:

### Windows Task Scheduler Integration
Register TENJIN as a background Windows Scheduled Task:
```powershell
tenjin install
```
This registers a task named `TENJIN_Daemon` configured to launch on user login. To remove it:
```powershell
tenjin uninstall
```

### Process Locking
TENJIN maintains a PID lockfile at `data/tenjin.pid`. If a second daemon instance attempts to launch, it detects the active process ID and exits cleanly with an explanation.

---

## 20. Testing

TENJIN includes a comprehensive test suite covering unit logic, integration paths, and security boundaries.

Run all tests:
```powershell
pytest -v
```

### Current Test Suite Results

```text
tests/integration/test_git_integration.py::test_real_git_branch_commit_and_diff_hash PASSED [  4%]
tests/security/test_security_boundaries.py::test_dirty_workspace_halts_to_prevent_data_loss PASSED [  8%]
tests/security/test_security_boundaries.py::test_path_containment_prevents_directory_traversal PASSED [ 12%]
tests/security/test_security_boundaries.py::test_prompt_injection_sanitization PASSED [ 16%]
tests/security/test_security_boundaries.py::test_malformed_agent_output_rejected PASSED [ 20%]
tests/unit/test_fingerprint.py::test_fingerprint_stability_across_minor_whitespace PASSED [ 25%]
tests/unit/test_fingerprint.py::test_regression_promotion_fixed_to_recurring PASSED [ 29%]
tests/unit/test_policy.py::test_global_policy_caps_repository_autonomy PASSED [ 33%]
tests/unit/test_policy.py::test_autofix_blocked_for_high_risk PASSED     [ 37%]
tests/unit/test_redaction.py::test_redact_github_tokens PASSED           [ 41%]
tests/unit/test_redaction.py::test_redact_github_fine_grained_pat PASSED [ 45%]
tests/unit/test_redaction.py::test_redact_bearer_token PASSED            [ 50%]
tests/unit/test_redaction.py::test_redact_private_key PASSED             [ 54%]
tests/unit/test_redaction.py::test_redact_database_uri_password PASSED   [ 58%]
tests/unit/test_redaction.py::test_contains_secrets PASSED               [ 62%]
tests/unit/test_redaction.py::test_scan_diff_for_secrets PASSED          [ 66%]
tests/unit/test_reports.py::test_reports_redact_secrets_in_json_and_markdown PASSED [ 70%]
tests/unit/test_risk.py::test_risk_critical_on_credentials_path PASSED   [ 75%]
tests/unit/test_risk.py::test_risk_high_on_auth_directory PASSED         [ 79%]
tests/unit/test_risk.py::test_risk_high_on_large_diff PASSED             [ 83%]
tests/unit/test_risk.py::test_risk_trivial_for_minor_fix PASSED          [ 87%]
tests/unit/test_selection.py::test_selection_prioritizes_never_audited_repository PASSED [ 91%]
tests/unit/test_state_machine.py::test_legal_state_transitions PASSED    [ 95%]
tests/unit/test_state_machine.py::test_illegal_state_transition_raises_error PASSED [100%]

============================= 24 passed in 1.51s ==============================
```

To run linter and type-checker validations:
```powershell
ruff check .
mypy --ignore-missing-imports tenjin
```

---

## 21. Example Run

Executing an autonomous audit against `Aadrit555/TENJIN`:

```powershell
tenjin audit --repo Aadrit555/TENJIN
```

Output:
```text
2026-10-02 05:53:10 [INFO] tenjin.orchestration.state_machine: State transition: SELECTING -> PREPARING
2026-10-02 05:53:10 [INFO] tenjin.repositories.workspace: Reusing workspace at workspaces\Aadrit555_TENJIN
2026-10-02 05:53:11 [INFO] tenjin.orchestration.state_machine: State transition: PREPARING -> INVENTORYING
2026-10-02 05:53:11 [INFO] tenjin.orchestration.state_machine: State transition: INVENTORYING -> AUDITING
2026-10-02 05:53:11 [INFO] tenjin.audit.engine: Starting 10-layer audit for Aadrit555/TENJIN
2026-10-02 05:53:12 [INFO] tenjin.audit.engine: Audit completed: 17 total findings detected
2026-10-02 05:53:12 [INFO] tenjin.orchestration.state_machine: State transition: AUDITING -> PLANNING
2026-10-02 05:53:12 [INFO] tenjin.orchestration.state_machine: State transition: PLANNING -> REPORTING
2026-10-02 05:53:12 [INFO] tenjin.orchestration.state_machine: State transition: REPORTING -> COMPLETED

============================================================
AUDIT COMPLETED: Aadrit555/TENJIN (Run: run_1790900590_dc4db1)
Duration: 2.01s | Status: COMPLETED
Findings: 10 total (0 fixed)
============================================================
[LOW] Function 'detect_project_profile' exceeds 120 lines in project_detection.py
  Category: code_quality / high_complexity | File: tenjin/repositories/project_detection.py
[MEDIUM] Swallowed exception without logging in project_detection.py
  Category: code_quality / swallowed_exception | File: tenjin/repositories/project_detection.py
[CRITICAL] Exposed potential GITHUB_TOKEN secret in main.py
  Category: security / exposed_credentials | File: tenjin/cli/main.py
```

Audit reports are automatically written to:
* `reports/Aadrit555_TENJIN_audit_run_1790900590_dc4db1.json`
* `reports/Aadrit555_TENJIN_audit_run_1790900590_dc4db1.md`

---

## 22. Project Structure

```text
.
├── .gitignore               # Ignores .venv, workspaces, databases, credentials
├── LICENSE                  # MIT License
├── README.md                # Comprehensive documentation
├── config.example.yaml      # Configuration template with safe defaults
├── install.ps1              # Automated Windows setup script
├── uninstall.ps1            # Clean uninstallation script
├── pyproject.toml           # Packaging, build metadata, and dependencies
├── assets/                  # Authentic artwork and visual assets
│   └── tenjin-hero.jpg      # Historical portrait of Tenjin (Sugawara no Michizane)
├── docs/                    # Architectural and operational specifications
│   ├── architecture.md      # Detailed system architecture specification
│   ├── security-model.md    # Security, isolation, and redacting architecture
│   ├── threat-model.md      # Threat model and risk mitigation matrix
│   ├── agent-workflow.md    # Delegation protocols and independent verification
│   ├── recovery.md          # Crash recovery and worktree reconciliation
│   ├── configuration.md     # Hierarchical configuration reference
│   └── operations.md        # Runbooks and operational workflows
├── tenjin/                  # Source package root
│   ├── agents/              # Antigravity runners, task builders, output parsers
│   ├── audit/               # 10-layer audit engine and deduplication
│   ├── cli/                 # CLI entrypoint and commands
│   ├── core/                # Constants, capabilities, config, lifecycle
│   ├── dashboard/           # REST API, server, and web console
│   ├── git/                 # Git operations and branch management
│   ├── github/              # GitHub CLI and REST API integration
│   ├── memory/              # SQLite database and Pydantic models
│   ├── notifications/       # Windows desktop alerts
│   ├── orchestration/       # State machine, scheduler, selector, recovery
│   ├── policies/            # Risk calculation and policy resolution
│   ├── reporting/           # JSON and Markdown report generation
│   ├── repositories/        # Workspaces, project detection, instructions
│   ├── security/            # Redaction, injection defense, isolation
│   └── verification/        # Independent verification engine
└── tests/                   # Test suite
    ├── conftest.py          # Pytest fixtures and mock isolation
    ├── integration/         # Real Git and filesystem integration tests
    ├── security/            # Prompt injection, path traversal, dirty workspace tests
    └── unit/                # State machine, fingerprint, policy, risk, redaction tests
```

---

## 23. Limitations

To maintain engineering integrity, TENJIN documents its concrete limitations:

1. **Automated Audits Do Not Catch Every Bug**: Static analysis, AST parsing, and linter passes catch structural flaws, syntax errors, leaked secrets, and complexity issues. They do not replace comprehensive human architectural reviews or deep domain logic validation.
2. **Dependent on Project Test Suites**: TENJIN's verification engine relies on existing project test commands (`pytest`, `npm test`, `cargo test`). If a repository has no automated tests, TENJIN can verify linters, syntax, and finding elimination, but cannot independently verify behavioral correctness.
3. **Network Connectivity**: GitHub discovery, cloning, branch pushing, and pull request creation require internet access and valid GitHub authentication. If offline, TENJIN can only audit and repair existing local workspaces.
4. **Platform Specifics**: Windows Task Scheduler integration (`tenjin install`) is specific to Windows. On Linux or macOS, background execution is handled via `systemd` or `launchd` service units.

---

## 24. Security Notes

* **Local-First Architecture**: Your code, diffs, database records, and audit reports never leave your local machine except when you explicitly allow pushing a branch to your GitHub origin.
* **Token Redaction**: Tokens and private keys are redacted at the capture boundary. Even if a scanner detects a credential in code, the raw secret is never written to the SQLite database or report files.
* **Subprocess Hygiene**: Environment variables are scrubbed before launching child processes. Credentials such as `GITHUB_TOKEN` are not passed to untrusted repository scripts.

---

## 25. Troubleshooting

### Dirty Workspace Error
```text
tenjin.repositories.workspace.DirtyWorkspaceError: Workspace has uncommitted human changes.
```
* **Cause**: You modified files inside `workspaces/<repo>` directly.
* **Fix**: Either commit your changes or discard them (`git status` inside the workspace directory) so TENJIN can resume without risking your work.

### Missing GitHub Authentication
```text
tenjin.github.client.GitHubAuthenticationError: No GitHub credentials found.
```
* **Cause**: GitHub CLI is not logged in and `GITHUB_TOKEN` is unset.
* **Fix**: Run `gh auth login` or set `$env:GITHUB_TOKEN = "your_token"`.

### Antigravity Binary Not Found
```text
tenjin.agents.antigravity.AgentExecutionError: Antigravity executable not found.
```
* **Cause**: `agy.exe` is not installed on PATH or standard directory.
* **Fix**: Run `tenjin doctor` to see the expected locations, or install the Antigravity CLI to `~/.gemini/bin/agy.exe`.

### Daemon Already Running
```text
tenjin.core.lifecycle.ProcessLockError: TENJIN daemon is already running (PID: 12345).
```
* **Cause**: Another daemon instance holds the lockfile `data/tenjin.pid`.
* **Fix**: Run `tenjin status` to inspect the running daemon, or run `tenjin stop` to shut it down.

---

## 26. Contributing

Contributions are welcome. Please ensure all modifications meet the project's quality standards:

1. Maintain zero environment-specific hardcoding.
2. Ensure every feature is backed by real implementation.
3. Format and lint code with `ruff check .`.
4. Validate types with `mypy --ignore-missing-imports tenjin`.
5. Run the full test suite with `pytest -v` (all tests must pass).

---

## 27. License

TENJIN is licensed under the [MIT License](LICENSE).

---

## 28. Final Project Summary

TENJIN is built on a simple foundation: automate the repetitive burden of repository maintenance without compromising safety, honesty, or code quality. By coupling dynamic local discovery with deep multi-layer auditing, bounded AI delegation, and uncompromising independent verification, TENJIN ensures your repositories remain clean, secure, and deployable.
