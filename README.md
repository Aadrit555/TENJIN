# TENJIN (天神)
### Persistent Autonomous Personal Software-Engineering System

TENJIN is a real, persistent, autonomous personal software-engineering system that runs locally on your workstation and manages your GitHub repositories.

The project is inspired by Tenjin, the Japanese kami associated with scholarship, learning, and knowledge. TENJIN is designed with engineering rigor: no simulated agents, no fake metrics, no hardcoded usernames or paths, and strictly independent verification of all proposed code modifications.

---

## Autonomous Engineering Loop

When running, TENJIN executes an continuous autonomous engineering loop:

```
[System Startup / Task Scheduler]
                │
                ▼
  [1. Discover Repositories]  ◄──── Real GitHub CLI / REST API metadata
                │
                ▼
   [2. Autonomous Selection]   ◄──── Multi-factor ranking (audit staleness, activity, findings)
                │
                ▼
  [3. Prepare Real Workspace]  ◄──── Isolated clone & worktree verification (no destructive resets)
                │
                ▼
    [4. Deep 10-Layer Audit]   ◄──── Inventory, linters, security, dependencies, tests, quality, CI
                │
                ▼
  [5. Evidence-Based Plan]     ◄──── Fingerprinted findings, risk engine, policy enforcement
                │
                ▼
  [6. Delegate to Antigravity] ◄──── Real Antigravity CLI/SDK with bounded task context
                │
                ▼
 [7. Independent Verification] ◄──── Scope validation, diff analysis, real tests, linters, re-audit
                │
                ▼
    [8. Autonomous Git Ops]    ◄──── forge/<id> branch, conventional commit, verified push & PR
                │
                ▼
  [9. Update System Memory]    ◄──── SQLite audit history, finding recurrence, health metrics
                │
                ▼
    [Select Next Repository]
```

---

## Key Architectural Principles

1. **Zero Hardcoded Environment Assumptions**: All paths (Git, Python, Antigravity, GitHub CLI, user home, temp directories, toolchains) are discovered dynamically from the runtime environment.
2. **Real Implementation Only**: Every CLI command, audit layer, verification check, and dashboard metric is backed by actual execution and database state.
3. **Independent Verification**: The AI agent (Antigravity) is never its own verifier. TENJIN inspects git diffs, executes test suites, runs linters and security checks, and confirms finding resolution before committing.
4. **Strict Safety & Autonomy Levels**:
   - `Level 0`: Observe only
   - `Level 1`: Audit + Report (Default)
   - `Level 2`: Audit + Propose repairs
   - `Level 3`: Audit + Repair in branch + Verify + Commit
   - `Level 4`: Audit + Repair + Verify + Commit + Push branch
   - `Level 5`: Audit + Repair + Verify + Commit + Push + Pull Request
   - `Level 6`: Automatic merge (strictly opt-in with explicit branch policy)
5. **Instruction Hierarchy & Prompt Injection Defense**: Untrusted repository instructions (`AGENTS.md`, `CLAUDE.md`, `README.md`) can provide build or test context, but can never override TENJIN safety policies or elevate permissions.

---

## System Requirements & Prerequisites

- **Operating System**: Windows 10/11, Linux, or macOS (Windows Task Scheduler support on Windows).
- **Python**: Python 3.10+ (Python 3.12+ recommended).
- **Git**: Installed and accessible in PATH or standard system directories.
- **GitHub Access**: GitHub CLI (`gh`) authenticated with `repo` scope, or `GITHUB_TOKEN` environment variable.
- **Antigravity**: Antigravity CLI (`agy`) or Google Antigravity SDK for autonomous repair stages.

---

## Installation & Quickstart

### Automated Windows Setup
```powershell
# Run the real PowerShell installation script
.\install.ps1
```

### Manual Installation
```bash
# Clone the repository
git clone https://github.com/Aadrit555/TENJIN.git
cd TENJIN

# Create virtual environment and install in editable mode
uv venv .venv --python 3.12
.\.venv\Scripts\activate
uv pip install -e ".[dev]"

# Verify environment capabilities
tenjin doctor

# Run self-diagnostic
tenjin self-test

# Discover accessible repositories
tenjin repos

# Run a read-only audit against a repository
tenjin audit --repo owner/repository

# Start operational dashboard
tenjin dashboard --port 8765
```

---

## Operational CLI Commands

| Command | Description |
|---|---|
| `tenjin doctor` | Inspects environment, checks toolchains, and explains missing capabilities |
| `tenjin self-test` | Runs end-to-end self tests on SQLite, Git, scanners, and integrations |
| `tenjin start` | Starts the persistent autonomous daemon loop |
| `tenjin stop` | Gracefully shuts down the background daemon |
| `tenjin status` | Shows current worker state, active job, queue, and locks |
| `tenjin repos` | Lists discovered GitHub repositories with health & audit status |
| `tenjin audit [--repo <name>]` | Triggers a deep 10-layer audit on a specific repository or next selected |
| `tenjin run` | Executes a single full autonomous cycle (discovery -> select -> audit -> repair -> verify) |
| `tenjin findings` | Lists open, fixed, and recurring audit findings |
| `tenjin finding <id>` | Shows detailed evidence, diff, attempts, and verification notes for a finding |
| `tenjin approve <id>` | Approves a high-risk finding for autonomous repair |
| `tenjin reject <id>` | Rejects or ignores a finding |
| `tenjin pause` | Pauses autonomous mutations (in-flight operations finish safely) |
| `tenjin resume` | Resumes autonomous mutations |
| `tenjin emergency-stop` | Immediately halts scheduling and disables all branch pushes |
| `tenjin dashboard` | Launches the local real-time operational web console |
| `tenjin history` | Displays audit and mutation history across repositories |
| `tenjin logs` | Displays recent structured logs with secrets redacted |
| `tenjin backup` | Creates an encrypted/clean backup of the SQLite database and policies |
| `tenjin install` | Registers background auto-start via Windows Task Scheduler |
| `tenjin uninstall` | Unregisters Windows Task Scheduler background tasks |

---

## Dashboard

Launch the local web console at `http://127.0.0.1:8765`:
```bash
tenjin dashboard
```

The dashboard displays:
- **Overview**: Active runs, real finding severities, verified fixes, Git actions.
- **Repositories**: Discovered repositories, health scores, audit staleness.
- **Repository Detail**: Metadata, audit history, open findings, commits created.
- **Finding Detail**: Code evidence, line ranges, proposed fix, verification results.
- **Run Detail**: Decision score breakdown, state transitions, raw execution logs.
- **System**: Tool availability inventory, background scheduler, lock status.
- **Configuration**: Effective global policies with sensitive credentials redacted.

---

## Security & Privacy Model

- **Local-First**: All metadata, audit databases, and workspace operations remain on the local machine.
- **Secret Redaction**: High-entropy tokens, GitHub credentials, private keys, and passwords are automatically redacted before logging, reporting, or persisting to the database.
- **Isolated Workspaces**: Autonomous operations run in dedicated clones under `workspaces/` and never perform destructive operations (`git reset --hard`, `git clean -fd`) on user working trees.
- **No Direct Master Push**: TENJIN commits to isolated `forge/<id>` branches and creates pull requests when policy permits.
