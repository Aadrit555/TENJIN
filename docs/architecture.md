# TENJIN Architecture

TENJIN is designed as a persistent, local-first, autonomous engineering system. It operates continuously on your developer workstation, proactively inspecting accessible repositories, diagnosing issues across 10 deterministic and contextual analysis layers, and orchestrating verified repairs through an external AI coding agent (Antigravity).

---

## High-Level System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TENJIN RUNTIME DAEMON                           │
│                                                                        │
│   ┌────────────────────┐                 ┌─────────────────────────┐   │
│   │ Capability Engine  │                 │    SQLite Data Layer    │   │
│   │ (Dynamic Discovery)│                 │ (WAL Mode, Relational)  │   │
│   └─────────┬──────────┘                 └────────────▲────────────┘   │
│             │                                         │                │
│             ▼                                         │                │
│   ┌───────────────────────────────────────────────────┴────────────┐   │
│   │                     Autonomous Scheduler                       │   │
│   │  - Anti-Starvation Multi-Factor Selector                       │   │
│   │  - Mutation Concurrency Lock (1 per repo)                      │   │
│   │  - Persistent Pause / Resume & Emergency Stop                  │   │
│   └─────────────────────────┬──────────────────────────────────────┘   │
│                             │                                          │
│                             ▼                                          │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │                     22-State Run Coordinator                   │   │
│   │                                                                │   │
│   │  [Prepare Workspace] ──► Isolated Clone under workspaces/      │   │
│   │  [Project Profiler]  ──► Dynamic Commands & Language Detection │   │
│   │  [10-Layer Audit]    ──► Evidence & AST Analysis               │   │
│   │  [Deduplication]     ──► SHA-256 Fingerprinting & Recurrence   │   │
│   │  [Policy Engine]     ──► Autonomy Levels (0 to 6) & Risk Eval  │   │
│   │  [Agent Runner]      ──► Antigravity CLI / Subagent Protocol   │   │
│   │  [Independent Verif] ──► Test Suite, Diff Scope, Linters, Re-audit │
│   │  [Git Operator]      ──► Isolated Branch, Conventional Commit  │   │
│   │  [Reporter]          ──► JSON & Markdown Reports               │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Capability Discovery (`tenjin.core.capabilities`)
Discovers hardware resources, version control binaries, active GitHub credentials, and all available language linters and analyzers dynamically at runtime. It enforces **Rule 1**: zero hardcoded machine paths, usernames, or assumptions.

### 2. Relational Memory (`tenjin.memory.database`)
SQLite with Write-Ahead Logging (WAL) and foreign-key constraints stores:
- Discovered repositories and metadata
- All autonomous runs, durations, and base/head SHAs
- State transitions across the 22-state lifecycle
- Audit findings and historical occurrences
- Verified Git actions (branches, commits, pushes, pull requests)
- Repository health metric history
- Pre-mutation journals for crash reconciliation

### 3. Managed Workspace Isolation (`tenjin.repositories.workspace`)
TENJIN maintains dedicated clones inside `workspaces/<owner>_<repo>`. Destructive commands such as `git reset --hard` or `git clean -fd` are strictly prohibited against user directories. Workspaces are inspected for uncommitted human modifications before any operation begins.

### 4. 10-Layer Audit Engine (`tenjin.audit.engine`)
Layered analysis ensures that deterministic evidence precedes AI synthesis:
- **Layer 1: Structural Inventory**: Source files, tests, package manifests, CI workflows.
- **Layer 2: Real Deterministic Scanners**: Runs installed language toolchains (`ruff`, `pytest`, `eslint`, `tsc`, `clippy`, etc.).
- **Layer 3: Security & Secrets**: Regex token scanning and AST inspection for command injection (`shell=True`), unsafe deserialization (`pickle`), and dynamic execution (`eval`).
- **Layer 4: Dependency Analysis**: Unpinned dependencies and vulnerability records in manifests.
- **Layer 5: Testing Assessment**: Evaluates presence of tests, edge case coverage, and test failure patterns.
- **Layer 6: Code Quality**: AST complexity analysis, oversized routines (>120 lines), and swallowed exceptions (`except: pass`).
- **Layer 7: Architecture**: Module hierarchy, circular imports, root-level pollution.
- **Layer 8: Documentation**: README accuracy against actual setup manifests.
- **Layer 9: CI/CD Workflows**: Dangerous `pull_request_target` triggers and overly permissive `permissions: write-all`.
- **Layer 10: Synthesis**: Contextual evidence grouping and risk assignment.

### 5. Independent Verification Engine (`tenjin.verification.engine`)
A central tenet of TENJIN is that **Antigravity cannot be its own verifier**. After code changes are produced:
1. Diff scope is checked against allowed file limits.
2. Modified lines are scanned for newly introduced secrets.
3. Relevant linters and type checkers are executed.
4. Project test suites are executed in the isolated workspace.
5. The 10-layer audit is re-run to confirm that the original finding was resolved and that no regressions were introduced.

### 6. Git Operator (`tenjin.git.repository`)
Creates safe branches (`forge/<id>`), validates clean unified diffs, calculates SHA-256 diff digests, produces conventional commits, and opens evidence-backed pull requests without ever force-pushing or bypassing branch protections.
