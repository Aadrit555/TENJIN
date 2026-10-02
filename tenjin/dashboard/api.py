"""TENJIN Operational Dashboard FastAPI Endpoints.

Provides strictly real, non-simulated API endpoints backed by the SQLite database,
system capabilities inventory, and scheduler state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from tenjin.core.capabilities import CapabilityInventory, discover_capabilities
from tenjin.core.config import TenjinConfig, load_config
from tenjin.core.constants import FindingStatus
from tenjin.core.lifecycle import ProcessLock
from tenjin.memory.database import Database
from tenjin.memory.models import FindingRecord, RepositoryRecord, RunRecord
from tenjin.orchestration.scheduler import SchedulerState


def get_db() -> Database:
    cfg = load_config()
    return Database(cfg.database_path)


def get_config() -> TenjinConfig:
    return load_config()


router = APIRouter(prefix="/api")


@router.get("/stats")
def get_stats(db: Database = Depends(get_db)) -> Dict[str, Any]:
    """Return aggregated live system statistics."""
    return db.get_system_stats()


@router.get("/repositories")
def list_repositories(db: Database = Depends(get_db)) -> List[Dict[str, Any]]:
    """List all tracked repositories with real health and audit metadata."""
    repos = db.list_repositories()
    return [r.model_dump() for r in repos]


@router.get("/repositories/{owner}/{name}")
def get_repository_detail(
    owner: str,
    name: str,
    db: Database = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve full detail for a single repository including open findings and recent runs."""
    full_name = f"{owner}/{name}"
    repo = db.get_repository(full_name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    findings = db.list_findings(repository=full_name)
    runs = [r for r in db.list_runs(limit=20) if r.repository == full_name]

    return {
        "repository": repo.model_dump(),
        "open_findings": [f.model_dump() for f in findings if f.status == FindingStatus.OPEN],
        "all_findings": [f.model_dump() for f in findings],
        "recent_runs": [r.model_dump() for r in runs],
    }


@router.get("/findings")
def list_findings(
    repo: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100),
    db: Database = Depends(get_db),
) -> List[Dict[str, Any]]:
    """List findings with optional filters."""
    stat_enum = FindingStatus(status) if status else None
    findings = db.list_findings(repository=repo, status=stat_enum, limit=limit)
    return [f.model_dump() for f in findings]


@router.get("/findings/{finding_id}")
def get_finding_detail(
    finding_id: str,
    db: Database = Depends(get_db),
) -> Dict[str, Any]:
    """Fetch finding details and historical occurrences."""
    finding = db.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Fetch history
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT * FROM finding_history WHERE fingerprint = ? ORDER BY timestamp DESC",
            (finding.fingerprint,),
        ).fetchall()
        history = [dict(r) for r in rows]

    return {
        "finding": finding.model_dump(),
        "history": history,
    }


@router.post("/findings/{finding_id}/approve")
def approve_finding(
    finding_id: str,
    db: Database = Depends(get_db),
) -> Dict[str, str]:
    """Approve a finding for autonomous repair."""
    finding = db.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    finding.status = FindingStatus.ACCEPTED
    finding.autofix_eligibility = True
    db.upsert_finding(finding)
    return {"status": "approved", "finding_id": finding_id}


@router.post("/findings/{finding_id}/reject")
def reject_finding(
    finding_id: str,
    db: Database = Depends(get_db),
) -> Dict[str, str]:
    """Mark a finding as ignored."""
    finding = db.get_finding(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    finding.status = FindingStatus.IGNORED
    db.upsert_finding(finding)
    return {"status": "ignored", "finding_id": finding_id}


@router.get("/runs")
def list_runs(limit: int = Query(50), db: Database = Depends(get_db)) -> List[Dict[str, Any]]:
    """List recent runs."""
    runs = db.list_runs(limit=limit)
    return [r.model_dump() for r in runs]


@router.get("/runs/{run_id}")
def get_run_detail(
    run_id: str,
    db: Database = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve full audit run details, state transitions, and Git actions."""
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    transitions = db.get_state_transitions(run_id)
    findings = [f.model_dump() for f in db.list_findings() if f.run_id == run_id]

    with db.connection() as conn:
        actions = [dict(r) for r in conn.execute("SELECT * FROM git_actions WHERE run_id = ?", (run_id,)).fetchall()]
        verifications = [dict(r) for r in conn.execute("SELECT * FROM verification_runs WHERE run_id = ?", (run_id,)).fetchall()]
        decisions = [dict(r) for r in conn.execute("SELECT * FROM selection_decisions WHERE run_id = ?", (run_id,)).fetchall()]

    return {
        "run": run.model_dump(),
        "state_transitions": [t.model_dump() for t in transitions],
        "findings": findings,
        "git_actions": actions,
        "verification_runs": verifications,
        "selection_decision": decisions[0] if decisions else None,
    }


@router.get("/system")
def get_system_status(cfg: TenjinConfig = Depends(get_config)) -> Dict[str, Any]:
    """Return real system environment capabilities and daemon status."""
    caps = discover_capabilities()
    base_dir = Path(cfg.database_path).parent
    state_ctrl = SchedulerState(base_dir)
    lock = ProcessLock(base_dir / "worker.pid")

    return {
        "daemon_running": lock.is_running(),
        "paused": state_ctrl.is_paused,
        "emergency_stop": state_ctrl.is_emergency_stopped,
        "hardware": caps.hardware.__dict__,
        "os": f"{caps.os_name} {caps.os_release} ({caps.architecture})",
        "python": caps.python_version,
        "git": caps.git_version,
        "github_authenticated": caps.github_auth.authenticated,
        "github_account": caps.github_auth.active_account,
        "antigravity_available": caps.antigravity.available,
        "antigravity_version": caps.antigravity.cli_version,
        "tools_inventory": {k: v.status.value for k, v in caps.tools.items()},
    }


@router.get("/config")
def get_sanitized_config(cfg: TenjinConfig = Depends(get_config)) -> Dict[str, Any]:
    """Return effective system configuration with all secrets redacted."""
    return cfg.sanitized_dict()


@router.post("/scheduler/pause")
def pause_scheduler(cfg: TenjinConfig = Depends(get_config)) -> Dict[str, str]:
    state_ctrl = SchedulerState(Path(cfg.database_path).parent)
    state_ctrl.pause()
    return {"status": "paused"}


@router.post("/scheduler/resume")
def resume_scheduler(cfg: TenjinConfig = Depends(get_config)) -> Dict[str, str]:
    state_ctrl = SchedulerState(Path(cfg.database_path).parent)
    state_ctrl.resume()
    return {"status": "resumed"}


@router.post("/scheduler/emergency-stop")
def emergency_stop(cfg: TenjinConfig = Depends(get_config)) -> Dict[str, str]:
    state_ctrl = SchedulerState(Path(cfg.database_path).parent)
    state_ctrl.emergency_stop()
    return {"status": "emergency_stopped"}
