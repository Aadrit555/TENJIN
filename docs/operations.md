# TENJIN Operations Guide

This guide describes operational workflows, daemon management, finding triage, and emergency procedures for running TENJIN on developer workstations.

---

## 1. Service Management

### Automatic Startup via Windows Task Scheduler
TENJIN can start automatically whenever you log into Windows:
```powershell
# Register the Windows Task Scheduler background task
tenjin install

# Check registration status
tenjin doctor
```

To remove the scheduled task:
```powershell
tenjin uninstall
```

### Manual Daemon Control
You can also run the daemon interactively or in the background:
```bash
# Start background worker daemon
tenjin start

# Check status of worker, active run, and queue
tenjin status

# Gracefully stop background worker daemon
tenjin stop
```

---

## 2. Running Audits & Engineering Cycles

### Ad-Hoc Repository Audit (Read-Only)
Run a complete 10-layer audit on a specific repository without making code changes:
```bash
tenjin audit --repo Aadrit555/TENJIN
```

### Full Autonomous Cycle
Execute a single autonomous cycle (Discovery -> Selection -> Audit -> Repair -> Verify -> Commit):
```bash
tenjin run
```

---

## 3. Finding Triage & Approvals

When findings require human approval (e.g. high risk or protected areas):
```bash
# List all discovered findings
tenjin findings

# Filter findings for a specific repository
tenjin findings --repo owner/repository

# View evidence, code snippets, and suggested fixes for a finding
tenjin finding find_abc12345

# Approve an open finding for autonomous repair
tenjin approve find_abc12345

# Reject or ignore a finding
tenjin reject find_abc12345
```

---

## 4. Emergency Procedures

### Pausing Operations
To temporarily hold new autonomous mutations while allowing active runs to reach a clean stopping point:
```bash
tenjin pause
```
To resume:
```bash
tenjin resume
```

### Emergency Stop
If unexpected behavior occurs, immediately halt all scheduling and disable future branch pushes:
```bash
tenjin emergency-stop
```
This flag is persisted in storage and prevents any further autonomous Git operations until explicitly resumed.

---

## 5. Backups & Disaster Recovery

Create a timestamped backup of the SQLite database and all audit reports:
```bash
tenjin backup --dest ./backups/2026-10-02
```
Backup archives contain zero unredacted credentials.
