"""TENJIN Persistent SQLite Database Engine.

Implements robust relational storage for all repositories, runs, findings,
state transitions, agent executions, Git operations, and mutation journals.
Configures WAL mode, strict typing, foreign keys, and indexed queries.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from tenjin.core.constants import FindingSeverity, FindingSource, FindingStatus, RiskLevel, State
from tenjin.memory.models import (
    AgentExecutionRecord,
    FindingHistoryRecord,
    FindingRecord,
    GitActionRecord,
    HealthRecord,
    MutationJournalRecord,
    RepositoryRecord,
    RunRecord,
    SelectionDecisionRecord,
    StateTransitionRecord,
    VerificationRunRecord,
)

SCHEMA_VERSION = 1

INIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    full_name TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    clone_url TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    is_private INTEGER NOT NULL DEFAULT 0,
    is_fork INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    language TEXT,
    topics_json TEXT NOT NULL DEFAULT '[]',
    permissions_json TEXT NOT NULL DEFAULT '{}',
    last_audit_at TEXT,
    health_score REAL NOT NULL DEFAULT 100.0,
    status TEXT NOT NULL DEFAULT 'active',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    base_sha TEXT,
    head_sha TEXT,
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds REAL,
    autonomy_level INTEGER NOT NULL,
    selection_rationale TEXT,
    findings_count INTEGER NOT NULL DEFAULT 0,
    fixed_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (repository) REFERENCES repositories(full_name) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS state_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    repository TEXT NOT NULL,
    run_id TEXT NOT NULL,
    category TEXT NOT NULL,
    subcategory TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence TEXT NOT NULL,
    file TEXT,
    line_start INTEGER,
    line_end INTEGER,
    affected_component TEXT,
    risk TEXT NOT NULL,
    suggested_fix TEXT,
    required_tests_json TEXT NOT NULL DEFAULT '[]',
    autofix_eligibility INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS finding_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    repository TEXT NOT NULL,
    run_id TEXT NOT NULL,
    action TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS selection_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    score REAL NOT NULL,
    stale_audit_score REAL NOT NULL,
    activity_score REAL NOT NULL,
    unresolved_findings_score REAL NOT NULL,
    exploration_score REAL NOT NULL,
    factors_json TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    agent_interface TEXT NOT NULL,
    model_name TEXT,
    prompt TEXT NOT NULL,
    raw_output TEXT NOT NULL,
    parsed_output_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    passed INTEGER NOT NULL,
    diff_valid INTEGER NOT NULL,
    secrets_detected INTEGER NOT NULL,
    tests_passed INTEGER NOT NULL,
    lint_passed INTEGER NOT NULL,
    types_passed INTEGER NOT NULL,
    security_passed INTEGER NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS git_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    action_type TEXT NOT NULL,
    branch_name TEXT,
    base_sha TEXT,
    commit_sha TEXT,
    diff_hash TEXT,
    pr_url TEXT,
    pr_number INTEGER,
    status TEXT NOT NULL DEFAULT 'success',
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS health_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository TEXT NOT NULL,
    health_score REAL NOT NULL,
    open_critical INTEGER NOT NULL,
    open_high INTEGER NOT NULL,
    open_medium INTEGER NOT NULL,
    open_low INTEGER NOT NULL,
    freshness_hours REAL NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mutation_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    repository TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    intended_branch TEXT NOT NULL,
    intended_files_json TEXT NOT NULL,
    actual_files_changed_json TEXT NOT NULL DEFAULT '[]',
    final_diff_hash TEXT,
    commit_sha TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_findings_fingerprint ON findings(fingerprint);
CREATE INDEX IF NOT EXISTS idx_findings_repo ON findings(repository);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status);
CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs(repository);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state);
CREATE INDEX IF NOT EXISTS idx_state_transitions_run ON state_transitions(run_id);
CREATE INDEX IF NOT EXISTS idx_health_repo ON health_records(repository);
"""


class Database:
    """Thread-safe SQLite database manager for TENJIN."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing a transactional database connection."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Apply base schema and track migrations."""
        with self.connection() as conn:
            conn.executescript(INIT_SCHEMA_SQL)
            cur = conn.execute("SELECT version FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,))
            if not cur.fetchone():
                import datetime
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.datetime.now(datetime.timezone.utc).isoformat()),
                )

    # Repository operations
    def upsert_repository(self, repo: RepositoryRecord) -> None:
        """Insert or update a repository record."""
        sql = """
        INSERT INTO repositories (
            full_name, owner, name, url, clone_url, default_branch, is_private,
            is_fork, is_archived, language, topics_json, permissions_json,
            last_audit_at, health_score, status, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(full_name) DO UPDATE SET
            owner = excluded.owner,
            name = excluded.name,
            url = excluded.url,
            clone_url = excluded.clone_url,
            default_branch = excluded.default_branch,
            is_private = excluded.is_private,
            is_fork = excluded.is_fork,
            is_archived = excluded.is_archived,
            language = excluded.language,
            topics_json = excluded.topics_json,
            permissions_json = excluded.permissions_json,
            last_audit_at = coalesce(excluded.last_audit_at, repositories.last_audit_at),
            health_score = excluded.health_score,
            status = excluded.status,
            updated_at = excluded.updated_at
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    repo.full_name,
                    repo.owner,
                    repo.name,
                    repo.url,
                    repo.clone_url,
                    repo.default_branch,
                    1 if repo.is_private else 0,
                    1 if repo.is_fork else 0,
                    1 if repo.is_archived else 0,
                    repo.language,
                    json.dumps(repo.topics),
                    json.dumps(repo.permissions),
                    repo.last_audit_at,
                    repo.health_score,
                    repo.status,
                    repo.updated_at,
                ),
            )

    def get_repository(self, full_name: str) -> Optional[RepositoryRecord]:
        """Fetch a single repository by full_name."""
        sql = "SELECT * FROM repositories WHERE full_name = ?"
        with self.connection() as conn:
            row = conn.execute(sql, (full_name,)).fetchone()
            if not row:
                return None
            return self._row_to_repo(row)

    def list_repositories(self) -> List[RepositoryRecord]:
        """List all discovered repositories."""
        sql = "SELECT * FROM repositories ORDER BY health_score ASC, full_name ASC"
        with self.connection() as conn:
            rows = conn.execute(sql).fetchall()
            return [self._row_to_repo(r) for r in rows]

    def _row_to_repo(self, row: sqlite3.Row) -> RepositoryRecord:
        return RepositoryRecord(
            full_name=row["full_name"],
            owner=row["owner"],
            name=row["name"],
            url=row["url"],
            clone_url=row["clone_url"],
            default_branch=row["default_branch"],
            is_private=bool(row["is_private"]),
            is_fork=bool(row["is_fork"]),
            is_archived=bool(row["is_archived"]),
            language=row["language"],
            topics=json.loads(row["topics_json"] or "[]"),
            permissions=json.loads(row["permissions_json"] or "{}"),
            last_audit_at=row["last_audit_at"],
            health_score=row["health_score"],
            status=row["status"],
            updated_at=row["updated_at"],
        )

    # Run operations
    def create_run(self, run: RunRecord) -> None:
        """Create a new run record."""
        sql = """
        INSERT INTO runs (
            run_id, repository, base_sha, head_sha, state, started_at,
            ended_at, duration_seconds, autonomy_level, selection_rationale,
            findings_count, fixed_count, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    run.run_id,
                    run.repository,
                    run.base_sha,
                    run.head_sha,
                    run.state.value if hasattr(run.state, "value") else str(run.state),
                    run.started_at,
                    run.ended_at,
                    run.duration_seconds,
                    int(run.autonomy_level),
                    run.selection_rationale,
                    run.findings_count,
                    run.fixed_count,
                    run.error_message,
                ),
            )

    def update_run(self, run: RunRecord) -> None:
        """Update an existing run record."""
        sql = """
        UPDATE runs SET
            head_sha = ?,
            state = ?,
            ended_at = ?,
            duration_seconds = ?,
            findings_count = ?,
            fixed_count = ?,
            error_message = ?
        WHERE run_id = ?
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    run.head_sha,
                    run.state.value if hasattr(run.state, "value") else str(run.state),
                    run.ended_at,
                    run.duration_seconds,
                    run.findings_count,
                    run.fixed_count,
                    run.error_message,
                    run.run_id,
                ),
            )

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        """Fetch a run by ID."""
        sql = "SELECT * FROM runs WHERE run_id = ?"
        with self.connection() as conn:
            row = conn.execute(sql, (run_id,)).fetchone()
            if not row:
                return None
            return RunRecord(
                run_id=row["run_id"],
                repository=row["repository"],
                base_sha=row["base_sha"],
                head_sha=row["head_sha"],
                state=State(row["state"]),
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                duration_seconds=row["duration_seconds"],
                autonomy_level=row["autonomy_level"],
                selection_rationale=row["selection_rationale"],
                findings_count=row["findings_count"],
                fixed_count=row["fixed_count"],
                error_message=row["error_message"],
            )

    def list_runs(self, limit: int = 50) -> List[RunRecord]:
        """List recent runs."""
        sql = "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?"
        with self.connection() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
            return [
                RunRecord(
                    run_id=r["run_id"],
                    repository=r["repository"],
                    base_sha=r["base_sha"],
                    head_sha=r["head_sha"],
                    state=State(r["state"]),
                    started_at=r["started_at"],
                    ended_at=r["ended_at"],
                    duration_seconds=r["duration_seconds"],
                    autonomy_level=r["autonomy_level"],
                    selection_rationale=r["selection_rationale"],
                    findings_count=r["findings_count"],
                    fixed_count=r["fixed_count"],
                    error_message=r["error_message"],
                )
                for r in rows
            ]

    # State transitions
    def record_state_transition(self, tr: StateTransitionRecord) -> None:
        """Persist a state transition event."""
        sql = """
        INSERT INTO state_transitions (
            run_id, repository, from_state, to_state, reason, timestamp, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    tr.run_id,
                    tr.repository,
                    tr.from_state.value if hasattr(tr.from_state, "value") else str(tr.from_state),
                    tr.to_state.value if hasattr(tr.to_state, "value") else str(tr.to_state),
                    tr.reason,
                    tr.timestamp,
                    json.dumps(tr.metadata),
                ),
            )

    def get_state_transitions(self, run_id: str) -> List[StateTransitionRecord]:
        """Fetch all state transitions for a run in chronological order."""
        sql = "SELECT * FROM state_transitions WHERE run_id = ? ORDER BY id ASC"
        with self.connection() as conn:
            rows = conn.execute(sql, (run_id,)).fetchall()
            return [
                StateTransitionRecord(
                    id=r["id"],
                    run_id=r["run_id"],
                    repository=r["repository"],
                    from_state=State(r["from_state"]),
                    to_state=State(r["to_state"]),
                    reason=r["reason"],
                    timestamp=r["timestamp"],
                    metadata=json.loads(r["metadata_json"] or "{}"),
                )
                for r in rows
            ]

    # Findings
    def upsert_finding(self, f: FindingRecord) -> None:
        """Insert or update a finding record."""
        sql = """
        INSERT INTO findings (
            id, repository, run_id, category, subcategory, severity,
            confidence, title, summary, evidence, file, line_start,
            line_end, affected_component, risk, suggested_fix,
            required_tests_json, autofix_eligibility, source,
            fingerprint, detected_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            evidence = excluded.evidence,
            suggested_fix = excluded.suggested_fix
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    f.id,
                    f.repository,
                    f.run_id,
                    f.category,
                    f.subcategory,
                    f.severity.value,
                    f.confidence,
                    f.title,
                    f.summary,
                    f.evidence,
                    f.file,
                    f.line_start,
                    f.line_end,
                    f.affected_component,
                    f.risk.value,
                    f.suggested_fix,
                    json.dumps(f.required_tests),
                    1 if f.autofix_eligibility else 0,
                    f.source.value,
                    f.fingerprint,
                    f.detected_at,
                    f.status.value,
                ),
            )

    def get_finding(self, finding_id: str) -> Optional[FindingRecord]:
        """Fetch finding by ID."""
        sql = "SELECT * FROM findings WHERE id = ?"
        with self.connection() as conn:
            row = conn.execute(sql, (finding_id,)).fetchone()
            if not row:
                return None
            return self._row_to_finding(row)

    def get_finding_by_fingerprint(self, fingerprint: str) -> Optional[FindingRecord]:
        """Fetch finding by fingerprint."""
        sql = "SELECT * FROM findings WHERE fingerprint = ? ORDER BY detected_at DESC LIMIT 1"
        with self.connection() as conn:
            row = conn.execute(sql, (fingerprint,)).fetchone()
            if not row:
                return None
            return self._row_to_finding(row)

    def list_findings(
        self,
        repository: Optional[str] = None,
        status: Optional[FindingStatus] = None,
        limit: int = 100,
    ) -> List[FindingRecord]:
        """List findings filtered by repository and/or status."""
        query = "SELECT * FROM findings WHERE 1=1"
        params: List[Any] = []
        if repository:
            query += " AND repository = ?"
            params.append(repository)
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY detected_at DESC LIMIT ?"
        params.append(limit)

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_finding(r) for r in rows]

    def _row_to_finding(self, row: sqlite3.Row) -> FindingRecord:
        return FindingRecord(
            id=row["id"],
            repository=row["repository"],
            run_id=row["run_id"],
            category=row["category"],
            subcategory=row["subcategory"],
            severity=FindingSeverity(row["severity"]),
            confidence=row["confidence"],
            title=row["title"],
            summary=row["summary"],
            evidence=row["evidence"],
            file=row["file"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            affected_component=row["affected_component"],
            risk=RiskLevel(row["risk"]),
            suggested_fix=row["suggested_fix"],
            required_tests=json.loads(row["required_tests_json"] or "[]"),
            autofix_eligibility=bool(row["autofix_eligibility"]),
            source=FindingSource(row["source"]),
            fingerprint=row["fingerprint"],
            detected_at=row["detected_at"],
            status=FindingStatus(row["status"]),
        )

    # Finding History
    def record_finding_history(self, fh: FindingHistoryRecord) -> None:
        """Record an event in finding history."""
        sql = """
        INSERT INTO finding_history (
            fingerprint, repository, run_id, action, timestamp, details_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    fh.fingerprint,
                    fh.repository,
                    fh.run_id,
                    fh.action,
                    fh.timestamp,
                    json.dumps(fh.details),
                ),
            )

    # Agent Executions
    def record_agent_execution(self, ae: AgentExecutionRecord) -> None:
        """Persist an agent execution record."""
        sql = """
        INSERT INTO agent_executions (
            run_id, finding_id, agent_interface, model_name, prompt,
            raw_output, parsed_output_json, status, duration_seconds, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    ae.run_id,
                    ae.finding_id,
                    ae.agent_interface,
                    ae.model_name,
                    ae.prompt,
                    ae.raw_output,
                    json.dumps(ae.parsed_output),
                    ae.status,
                    ae.duration_seconds,
                    ae.timestamp,
                ),
            )

    # Verification Runs
    def record_verification_run(self, vr: VerificationRunRecord) -> None:
        """Persist verification run details."""
        sql = """
        INSERT INTO verification_runs (
            run_id, finding_id, passed, diff_valid, secrets_detected,
            tests_passed, lint_passed, types_passed, security_passed,
            details_json, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    vr.run_id,
                    vr.finding_id,
                    1 if vr.passed else 0,
                    1 if vr.diff_valid else 0,
                    1 if vr.secrets_detected else 0,
                    1 if vr.tests_passed else 0,
                    1 if vr.lint_passed else 0,
                    1 if vr.types_passed else 0,
                    1 if vr.security_passed else 0,
                    json.dumps(vr.details),
                    vr.timestamp,
                ),
            )

    # Git Actions
    def record_git_action(self, ga: GitActionRecord) -> None:
        """Persist a branch, commit, push, or PR action."""
        sql = """
        INSERT INTO git_actions (
            run_id, repository, action_type, branch_name, base_sha,
            commit_sha, diff_hash, pr_url, pr_number, status, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    ga.run_id,
                    ga.repository,
                    ga.action_type,
                    ga.branch_name,
                    ga.base_sha,
                    ga.commit_sha,
                    ga.diff_hash,
                    ga.pr_url,
                    ga.pr_number,
                    ga.status,
                    ga.timestamp,
                ),
            )

    # Selection Decisions
    def record_selection_decision(self, sd: SelectionDecisionRecord) -> None:
        """Persist a repository selection score and rationale."""
        sql = """
        INSERT INTO selection_decisions (
            run_id, repository, score, stale_audit_score, activity_score,
            unresolved_findings_score, exploration_score, factors_json, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    sd.run_id,
                    sd.repository,
                    sd.score,
                    sd.stale_audit_score,
                    sd.activity_score,
                    sd.unresolved_findings_score,
                    sd.exploration_score,
                    json.dumps(sd.factors),
                    sd.timestamp,
                ),
            )

    # Mutation Journal
    def record_mutation_journal(self, mj: MutationJournalRecord) -> int:
        """Record an entry in the mutation journal before modifying files."""
        sql = """
        INSERT INTO mutation_journal (
            run_id, repository, base_sha, intended_branch, intended_files_json,
            actual_files_changed_json, final_diff_hash, commit_sha, verified, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            cur = conn.execute(
                sql,
                (
                    mj.run_id,
                    mj.repository,
                    mj.base_sha,
                    mj.intended_branch,
                    json.dumps(mj.intended_files),
                    json.dumps(mj.actual_files_changed),
                    mj.final_diff_hash,
                    mj.commit_sha,
                    1 if mj.verified else 0,
                    mj.timestamp,
                ),
            )
            return cur.lastrowid or 0

    def update_mutation_journal(
        self,
        journal_id: int,
        actual_files: List[str],
        final_diff_hash: str,
        commit_sha: Optional[str],
        verified: bool,
    ) -> None:
        """Update mutation journal record after verification and commit."""
        sql = """
        UPDATE mutation_journal SET
            actual_files_changed_json = ?,
            final_diff_hash = ?,
            commit_sha = ?,
            verified = ?
        WHERE id = ?
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    json.dumps(actual_files),
                    final_diff_hash,
                    commit_sha,
                    1 if verified else 0,
                    journal_id,
                ),
            )

    # Health Records
    def record_health(self, hr: HealthRecord) -> None:
        """Persist a repository health snapshot."""
        sql = """
        INSERT INTO health_records (
            repository, health_score, open_critical, open_high,
            open_medium, open_low, freshness_hours, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.connection() as conn:
            conn.execute(
                sql,
                (
                    hr.repository,
                    hr.health_score,
                    hr.open_critical,
                    hr.open_high,
                    hr.open_medium,
                    hr.open_low,
                    hr.freshness_hours,
                    hr.timestamp,
                ),
            )

    # Aggregated System Stats
    def get_system_stats(self) -> Dict[str, Any]:
        """Calculate live system statistics for dashboard and CLI."""
        with self.connection() as conn:
            repo_count = conn.execute("SELECT count(*) as c FROM repositories").fetchone()["c"]
            run_count = conn.execute("SELECT count(*) as c FROM runs").fetchone()["c"]
            open_findings = conn.execute(
                "SELECT count(*) as c FROM findings WHERE status = 'open'"
            ).fetchone()["c"]
            critical_count = conn.execute(
                "SELECT count(*) as c FROM findings WHERE status = 'open' AND severity = 'critical'"
            ).fetchone()["c"]
            high_count = conn.execute(
                "SELECT count(*) as c FROM findings WHERE status = 'open' AND severity = 'high'"
            ).fetchone()["c"]
            medium_count = conn.execute(
                "SELECT count(*) as c FROM findings WHERE status = 'open' AND severity = 'medium'"
            ).fetchone()["c"]
            low_count = conn.execute(
                "SELECT count(*) as c FROM findings WHERE status = 'open' AND severity IN ('low', 'informational')"
            ).fetchone()["c"]
            fixed_count = conn.execute(
                "SELECT count(*) as c FROM findings WHERE status = 'fixed' OR status = 'verified'"
            ).fetchone()["c"]
            commit_count = conn.execute(
                "SELECT count(*) as c FROM git_actions WHERE action_type = 'commit' AND status = 'success'"
            ).fetchone()["c"]
            push_count = conn.execute(
                "SELECT count(*) as c FROM git_actions WHERE action_type = 'push' AND status = 'success'"
            ).fetchone()["c"]
            pr_count = conn.execute(
                "SELECT count(*) as c FROM git_actions WHERE action_type = 'pull_request' AND status = 'success'"
            ).fetchone()["c"]

            return {
                "repositories_count": repo_count,
                "total_runs": run_count,
                "open_findings": open_findings,
                "critical_findings": critical_count,
                "high_findings": high_count,
                "medium_findings": medium_count,
                "low_findings": low_count,
                "fixed_findings": fixed_count,
                "commits_created": commit_count,
                "pushes_completed": push_count,
                "prs_opened": pr_count,
            }
