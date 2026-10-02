# TENJIN Crash Recovery & State Reconciliation

TENJIN is designed to be restart-safe and power-loss resilient. If the workstation reboots or the process crashes during an active run, TENJIN reconciles persisted state against actual Git state upon startup.

---

## Authoritative State Hierarchy

1. **Git State is Authoritative**: The actual git commit history, branch references, and working tree cleanliness take precedence over database records.
2. **SQLite Database is Informational**: The database reflects the intended state and historical logs. If a database write fails after a Git commit succeeds, TENJIN updates the database to reflect the actual Git SHA rather than creating duplicate commits.

---

## Crash Recovery Behavior

During startup (via `tenjin start` or `tenjin run`), the `CrashRecoveryEngine` scans the SQLite database for runs that were interrupted before reaching a terminal state (`COMPLETED`, `FAILED`, `SKIPPED`, `BLOCKED`, `QUARANTINED`):

### 1. Interrupted during Audit or Discovery
- **Action**: Safely marked as `FAILED` with diagnostic message.
- **Result**: The repository returns to the queued selection pool for normal re-evaluation.

### 2. Interrupted during Active Mutation (`AGENT_RUNNING`, `REPAIRING`, `VERIFYING`)
- **Inspection**: The isolated workspace worktree is inspected for uncommitted changes (`git status --porcelain`).
- **Action**: If uncommitted or unverified changes are detected, the run is transitioned to `QUARANTINED`.
- **Safety Guarantee**: Unverified code is never committed or pushed to remote repositories. The branch is preserved for developer inspection.

### 3. Interrupted during Commit (`COMMITTING`)
- **Inspection**: The head commit SHA of the isolated branch is compared against the base SHA.
- **Action**: If a commit was created matching the finding, the database is updated with the real commit SHA and transitions to `REPORTING`. If no commit was created, it is safely marked as failed.

---

## Manual Recovery Commands

```bash
# Check status of all recent runs
tenjin status

# View detailed transitions and error messages of an interrupted run
tenjin run

# Re-run a fresh audit on a recovered repository
tenjin audit --repo owner/repository
```
