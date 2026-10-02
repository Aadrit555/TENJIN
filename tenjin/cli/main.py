"""TENJIN Operational Command-Line Interface.

Provides real, production CLI commands for status inspection, environment diagnostics (doctor),
end-to-end self-tests, autonomous run triggering, finding approvals, and backup management.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from tenjin.agents.antigravity import AntigravityRunner
from tenjin.audit.engine import AuditEngine
from tenjin.core.capabilities import ToolStatus, discover_capabilities
from tenjin.core.config import load_config
from tenjin.core.constants import FindingStatus
from tenjin.core.lifecycle import (
    ProcessLock,
    check_windows_task_status,
    install_windows_startup_task,
    uninstall_windows_startup_task,
)
from tenjin.dashboard.server import start_dashboard
from tenjin.github.client import GitHubClient
from tenjin.github.discovery import RepositoryDiscoveryService
from tenjin.memory.database import Database
from tenjin.orchestration.coordinator import RunCoordinator
from tenjin.orchestration.recovery import CrashRecoveryEngine
from tenjin.orchestration.scheduler import AutonomousScheduler, SchedulerState
from tenjin.orchestration.selector import RepositorySelector
from tenjin.repositories.workspace import WorkspaceManager
from tenjin.security.redaction import redact_secrets

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tenjin.cli")


def cmd_doctor(args: argparse.Namespace) -> None:
    """Inspect environment, report capabilities, and explain required setup."""
    print("=" * 60)
    print("TENJIN ENVIRONMENT DOCTOR & CAPABILITY AUDIT")
    print("=" * 60)

    caps = discover_capabilities()

    print("\n[HOST PLATFORM]")
    print(f"  OS:             {caps.os_name} {caps.os_release} (Version: {caps.os_version})")
    print(f"  Architecture:   {caps.architecture} (64-bit: {caps.is_64bit})")
    print(f"  Python:         {caps.python_version} ({caps.python_path})")
    print(f"  SQLite:         {caps.sqlite_version}")
    print(f"  Disk Free:      {caps.hardware.disk_free_gb} GB / {caps.hardware.disk_total_gb} GB")
    print(f"  RAM:            {caps.hardware.free_memory_gb} GB free / {caps.hardware.total_memory_gb} GB total")

    print("\n[VERSION CONTROL & GITHUB]")
    if caps.git_path:
        print(f"  Git:            AVAILABLE ({caps.git_version}) -> {caps.git_path}")
        print(f"  Git User:       {caps.git_user_name or 'Not configured'} <{caps.git_user_email or 'Not configured'}>")
    else:
        print("  Git:            NOT AVAILABLE (CRITICAL: Please install Git)")

    if caps.github_cli_path:
        print(f"  GitHub CLI:     AVAILABLE ({caps.github_cli_version}) -> {caps.github_cli_path}")
    else:
        print("  GitHub CLI:     NOT AVAILABLE (Optional: install gh for native CLI discovery)")

    if caps.github_auth.authenticated:
        print(f"  GitHub Auth:    AUTHENTICATED (Account: {caps.github_auth.active_account or 'token'}, Method: {caps.github_auth.auth_method})")
        if caps.github_auth.token_scopes:
            print(f"  Token Scopes:   {', '.join(caps.github_auth.token_scopes)}")
    else:
        print("  GitHub Auth:    NOT AUTHENTICATED (Run 'gh auth login' or export GITHUB_TOKEN)")

    print("\n[ANTIGRAVITY AGENT INTEGRATION]")
    if caps.antigravity.available:
        print(f"  Antigravity CLI: AVAILABLE (Version: {caps.antigravity.cli_version}) -> {caps.antigravity.cli_path}")
        if caps.antigravity.models:
            print(f"  Models:         {', '.join(caps.antigravity.models[:4])}...")
    else:
        print("  Antigravity CLI: NOT AVAILABLE (Install Antigravity or ensure 'agy' is on PATH)")

    print("\n[AUTOMATION & TASK SCHEDULER]")
    sched_ok, sched_msg = check_windows_task_status()
    print(f"  Task Scheduler: {sched_msg}")

    print("\n[CODE QUALITY & SECURITY SCANNERS]")
    for name, info in caps.tools.items():
        status_str = "AVAILABLE" if info.status == ToolStatus.AVAILABLE else "NOT AVAILABLE"
        details = f"({info.version})" if info.version else ""
        print(f"  {name:<15}: {status_str:<14} {details}")

    print("\n" + "=" * 60)


def cmd_self_test(args: argparse.Namespace) -> None:
    """Run non-simulated self diagnostic across all subsystems."""
    print("=" * 60)
    print("TENJIN SYSTEM INTEGRITY SELF-TEST")
    print("=" * 60)

    cfg = load_config()
    db = Database(cfg.database_path)
    caps = discover_capabilities()

    results = []

    # 1. Database SQLite
    try:
        stats = db.get_system_stats()
        results.append(("SQLite Database & Schema", "PASS", f"Connected ({stats['repositories_count']} repos in memory)"))
    except Exception as e:
        results.append(("SQLite Database & Schema", "FAIL", str(e)))

    # 2. Filesystem & Workspaces
    try:
        Path(cfg.workspace_dir).mkdir(parents=True, exist_ok=True)
        test_file = Path(cfg.workspace_dir) / ".selftest_write"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        results.append(("Filesystem Permissions", "PASS", f"Read/write verified in {cfg.workspace_dir}"))
    except Exception as e:
        results.append(("Filesystem Permissions", "FAIL", str(e)))

    # 3. Git Executable
    if caps.git_path:
        results.append(("Git Version Control", "PASS", caps.git_version or caps.git_path))
    else:
        results.append(("Git Version Control", "FAIL", "Git executable not found"))

    # 4. GitHub Connectivity
    gh_client = GitHubClient(cfg.github.token, caps.github_cli_path)
    if gh_client.is_authenticated():
        results.append(("GitHub Connectivity", "PASS", f"Authenticated via {caps.github_auth.auth_method}"))
    else:
        results.append(("GitHub Connectivity", "NOT_CONFIGURED", "No active GitHub token or gh auth session"))

    # 5. Antigravity Agent
    runner = AntigravityRunner(caps.antigravity.cli_path)
    if runner.is_available():
        results.append(("Antigravity Integration", "PASS", f"CLI ready: {caps.antigravity.cli_version}"))
    else:
        results.append(("Antigravity Integration", "UNAVAILABLE", "Antigravity CLI ('agy') not detected"))

    # 6. Secret Redaction
    sample_secret = "ghp_1234567890abcdef1234567890abcdef1234"
    redacted = redact_secrets(f"Token is {sample_secret}")
    if sample_secret not in redacted and "[REDACTED" in redacted:
        results.append(("Secret Redaction Engine", "PASS", "Tokens accurately masked before persistence"))
    else:
        results.append(("Secret Redaction Engine", "FAIL", "Redaction failed to mask test token"))

    # 7. Background Task Scheduler
    sched_ok, sched_msg = check_windows_task_status()
    results.append(("Windows Task Scheduler", "PASS" if sched_ok else "NOT_CONFIGURED", sched_msg))

    print()
    for name, status, details in results:
        status_color = f"[{status}]"
        print(f"  {status_color:<18} {name:<28} : {details}")
    print("\n" + "=" * 60)


def cmd_repos(args: argparse.Namespace) -> None:
    """Discover and list accessible repositories."""
    cfg = load_config()
    db = Database(cfg.database_path)
    caps = discover_capabilities()
    gh_client = GitHubClient(cfg.github.token, caps.github_cli_path)

    svc = RepositoryDiscoveryService(gh_client, db, cfg)
    print("Synchronizing repositories with GitHub...")
    try:
        repos = svc.discover_and_sync()
    except Exception as e:
        logger.warning("Live sync failed (%s). Listing stored repositories from SQLite.", e)
        repos = db.list_repositories()

    print(f"\nDiscovered {len(repos)} Repositories:")
    print(f"{'Repository':<35} {'Lang':<12} {'Health':<8} {'Last Audit':<22} {'Visibility'}")
    print("-" * 88)
    for r in repos:
        last_audit = r.last_audit_at[:19].replace("T", " ") if r.last_audit_at else "Never"
        vis = "Private" if r.is_private else "Public"
        print(f"{r.full_name:<35} {r.language or 'N/A':<12} {r.health_score:<8} {last_audit:<22} {vis}")


def cmd_audit(args: argparse.Namespace) -> None:
    """Trigger a deep 10-layer audit on a specific repository or next selected."""
    cfg = load_config()
    db = Database(cfg.database_path)
    caps = discover_capabilities()
    ws_mgr = WorkspaceManager(cfg.workspace_dir, caps.git_path)
    audit_engine = AuditEngine(caps)
    agent_runner = AntigravityRunner(caps.antigravity.cli_path, cfg.timeouts.agent_timeout_seconds)
    gh_client = GitHubClient(cfg.github.token, caps.github_cli_path)

    coord = RunCoordinator(db, cfg, caps, ws_mgr, audit_engine, agent_runner, gh_client)

    target_repo_name = args.repo
    if target_repo_name:
        repo = db.get_repository(target_repo_name)
        if not repo:
            print(f"Repository '{target_repo_name}' not in local database. Discovering from GitHub...")
            svc = RepositoryDiscoveryService(gh_client, db, cfg)
            svc.discover_and_sync()
            repo = db.get_repository(target_repo_name)

        if not repo:
            print(f"Error: Unable to locate repository '{target_repo_name}'.")
            return
    else:
        # Autonomous selection
        selector = RepositorySelector(db, cfg)
        sel = selector.select_next_repository("cli_audit")
        if not sel:
            print("No repository available for audit or all in cooldown.")
            return
        repo, decision = sel
        print(f"Autonomously selected: {repo.full_name} (Score: {decision.score:.2f})")

    print(f"Executing 10-layer audit for {repo.full_name}...")
    run_rec = coord.execute_repository_run(repo, selection_rationale="Manual CLI invocation")

    findings = db.list_findings(repository=repo.full_name)
    print("\n" + "=" * 60)
    print(f"AUDIT COMPLETED: {repo.full_name} (Run: {run_rec.run_id})")
    print(f"Duration: {run_rec.duration_seconds}s | Status: {run_rec.state.value}")
    print(f"Findings: {len(findings)} total ({run_rec.fixed_count} fixed)")
    print("=" * 60)

    for f in findings:
        print(f"[{f.severity.value.upper()}] {f.title}")
        print(f"  Category: {f.category} / {f.subcategory} | File: {f.file or 'N/A'}")
        print(f"  Evidence: {f.evidence[:140]}...")
        print()


def cmd_run(args: argparse.Namespace) -> None:
    """Execute a single complete autonomous cycle."""
    cfg = load_config()
    db = Database(cfg.database_path)
    caps = discover_capabilities()
    ws_mgr = WorkspaceManager(cfg.workspace_dir, caps.git_path)
    audit_engine = AuditEngine(caps)
    agent_runner = AntigravityRunner(caps.antigravity.cli_path, cfg.timeouts.agent_timeout_seconds)
    gh_client = GitHubClient(cfg.github.token, caps.github_cli_path)

    selector = RepositorySelector(db, cfg)
    coord = RunCoordinator(db, cfg, caps, ws_mgr, audit_engine, agent_runner, gh_client)
    sched = AutonomousScheduler(db, cfg, coord, selector)

    print("Executing single autonomous engineering cycle...")
    run_id = sched.run_single_cycle()
    if run_id:
        print(f"Cycle completed successfully. Run ID: {run_id}")
    else:
        print("Cycle ended with no action taken (paused, cooldown, or empty queue).")


def cmd_findings(args: argparse.Namespace) -> None:
    """List open or all audit findings."""
    cfg = load_config()
    db = Database(cfg.database_path)
    findings = db.list_findings(repository=args.repo)

    print(f"\nTENJIN Findings ({len(findings)} records):")
    print(f"{'ID':<18} {'Severity':<10} {'Repository':<28} {'Status':<10} {'Title'}")
    print("-" * 88)
    for f in findings:
        print(f"{f.id:<18} {f.severity.value:<10} {f.repository:<28} {f.status.value:<10} {f.title[:35]}")


def cmd_finding_detail(args: argparse.Namespace) -> None:
    """Show full detail for a single finding."""
    cfg = load_config()
    db = Database(cfg.database_path)
    finding = db.get_finding(args.id)
    if not finding:
        print(f"Error: Finding '{args.id}' not found.")
        return

    print("=" * 60)
    print(f"FINDING DETAIL: {finding.id}")
    print("=" * 60)
    print(f"Repository:    {finding.repository}")
    print(f"Category:      {finding.category} / {finding.subcategory}")
    print(f"Severity:      {finding.severity.value.upper()} (Confidence: {finding.confidence})")
    print(f"Status:        {finding.status.value.upper()}")
    print(f"File/Line:     {finding.file or 'N/A'}:{finding.line_start or ''}")
    print(f"Risk:          {finding.risk.value.upper()}")
    print(f"Autofix:       {'Yes' if finding.autofix_eligibility else 'No'}")
    print(f"\nTitle: {finding.title}")
    print(f"Summary:\n{finding.summary}")
    print(f"\nEvidence:\n{finding.evidence}")
    print(f"\nSuggested Fix:\n{finding.suggested_fix or 'N/A'}")
    print("=" * 60)


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve a finding for autonomous repair."""
    cfg = load_config()
    db = Database(cfg.database_path)
    finding = db.get_finding(args.id)
    if not finding:
        print(f"Error: Finding '{args.id}' not found.")
        return

    finding.status = FindingStatus.ACCEPTED
    finding.autofix_eligibility = True
    db.upsert_finding(finding)
    print(f"Finding '{args.id}' approved for autonomous repair.")


def cmd_reject(args: argparse.Namespace) -> None:
    """Reject and ignore a finding."""
    cfg = load_config()
    db = Database(cfg.database_path)
    finding = db.get_finding(args.id)
    if not finding:
        print(f"Error: Finding '{args.id}' not found.")
        return

    finding.status = FindingStatus.IGNORED
    db.upsert_finding(finding)
    print(f"Finding '{args.id}' ignored.")


def cmd_status(args: argparse.Namespace) -> None:
    """Display real-time daemon worker status, active locks, and queue."""
    cfg = load_config()
    db = Database(cfg.database_path)
    base_dir = Path(cfg.database_path).parent
    lock = ProcessLock(base_dir / "worker.pid")
    state_ctrl = SchedulerState(base_dir)

    print("=" * 60)
    print("TENJIN SYSTEM STATUS")
    print("=" * 60)
    print(f"Daemon Running:    {'YES' if lock.is_running() else 'NO'}")
    print(f"Scheduler Paused:  {'YES' if state_ctrl.is_paused else 'NO'}")
    print(f"Emergency Stop:    {'ACTIVE' if state_ctrl.is_emergency_stopped else 'INACTIVE'}")

    stats = db.get_system_stats()
    print("\nWork Queue & Statistics:")
    print(f"  Repositories:    {stats['repositories_count']}")
    print(f"  Total Runs:      {stats['total_runs']}")
    print(f"  Open Findings:   {stats['open_findings']} (Critical: {stats['critical_findings']}, High: {stats['high_findings']})")
    print(f"  Fixed Findings:  {stats['fixed_findings']}")
    print(f"  Commits Created: {stats['commits_created']}")
    print(f"  Pushes Done:     {stats['pushes_completed']}")
    print("=" * 60)


def cmd_pause(args: argparse.Namespace) -> None:
    cfg = load_config()
    state_ctrl = SchedulerState(Path(cfg.database_path).parent)
    state_ctrl.pause()
    print("TENJIN paused: new autonomous mutation jobs will be held.")


def cmd_resume(args: argparse.Namespace) -> None:
    cfg = load_config()
    state_ctrl = SchedulerState(Path(cfg.database_path).parent)
    state_ctrl.resume()
    print("TENJIN resumed: autonomous scheduling operational.")


def cmd_emergency_stop(args: argparse.Namespace) -> None:
    cfg = load_config()
    state_ctrl = SchedulerState(Path(cfg.database_path).parent)
    state_ctrl.emergency_stop()
    print("EMERGENCY STOP ENGAGED: All scheduling and branch pushes disabled immediately.")


def cmd_install(args: argparse.Namespace) -> None:
    """Register TENJIN in Windows Task Scheduler for login startup."""
    cfg = load_config()
    ok, msg = install_windows_startup_task(sys.executable, Path(cfg.database_path).parent)
    if ok:
        print(f"Success: {msg}")
    else:
        print(f"Installation failed: {msg}")


def cmd_uninstall(args: argparse.Namespace) -> None:
    """Unregister TENJIN from Windows Task Scheduler."""
    ok, msg = uninstall_windows_startup_task()
    if ok:
        print(f"Success: {msg}")
    else:
        print(f"Uninstallation failed: {msg}")


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Start local web console."""
    cfg = load_config()
    host = args.host or cfg.dashboard.host
    port = args.port or cfg.dashboard.port
    start_dashboard(host, port)


def cmd_backup(args: argparse.Namespace) -> None:
    """Backup database and policies excluding secrets."""
    cfg = load_config()
    dest = Path(args.dest or (Path(cfg.database_path).parent / f"tenjin_backup_{int(time.time())}"))
    dest.mkdir(parents=True, exist_ok=True)

    db_src = Path(cfg.database_path)
    if db_src.is_file():
        shutil.copy2(db_src, dest / "tenjin.db")

    rep_src = Path(cfg.reports_dir)
    if rep_src.is_dir():
        shutil.copytree(rep_src, dest / "reports", dirs_exist_ok=True)

    print(f"Backup created successfully at: {dest.resolve()}")


def cmd_start(args: argparse.Namespace) -> None:
    """Start the background daemon loop."""
    cfg = load_config()
    base_dir = Path(cfg.database_path).parent
    lock = ProcessLock(base_dir / "worker.pid")

    if not lock.acquire():
        print("Error: TENJIN daemon is already running on this workstation.")
        sys.exit(1)

    print(f"Starting TENJIN autonomous engineering daemon (PID: {os.getpid()})...")
    try:
        db = Database(cfg.database_path)
        caps = discover_capabilities()
        ws_mgr = WorkspaceManager(cfg.workspace_dir, caps.git_path)

        # Run crash recovery first
        recovery = CrashRecoveryEngine(db, ws_mgr)
        recovered = recovery.recover_incomplete_runs()
        if recovered:
            logger.info("Recovered %d interrupted runs from previous sessions", len(recovered))

        # Initial discovery
        gh_client = GitHubClient(cfg.github.token, caps.github_cli_path)
        discovery = RepositoryDiscoveryService(gh_client, db, cfg)
        try:
            discovery.discover_and_sync()
        except Exception as e:
            logger.warning("Startup discovery failed: %s", e)

        audit_engine = AuditEngine(caps)
        agent_runner = AntigravityRunner(caps.antigravity.cli_path, cfg.timeouts.agent_timeout_seconds)
        coord = RunCoordinator(db, cfg, caps, ws_mgr, audit_engine, agent_runner, gh_client)
        selector = RepositorySelector(db, cfg)
        sched = AutonomousScheduler(db, cfg, coord, selector)

        sched.run_daemon_loop(poll_interval_seconds=60.0)
    finally:
        lock.release()
        print("TENJIN daemon stopped.")


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop running background daemon."""
    cfg = load_config()
    base_dir = Path(cfg.database_path).parent
    pid_file = base_dir / "worker.pid"
    if not pid_file.is_file():
        print("TENJIN daemon is not running.")
        return

    try:
        pid = int(pid_file.read_text().strip())
        import signal
        os.kill(pid, signal.SIGTERM)
        print(f"Sent termination signal to TENJIN daemon (PID {pid}).")
    except Exception as e:
        print(f"Failed to stop daemon: {e}")


def cmd_config(args: argparse.Namespace) -> None:
    """Display sanitized configuration."""
    cfg = load_config()
    print(json.dumps(cfg.sanitized_dict(), indent=2))


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        prog="tenjin",
        description="TENJIN: Persistent Autonomous Personal Software-Engineering System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Commands
    subparsers.add_parser("doctor", help="Inspect environment and required toolchains")
    subparsers.add_parser("self-test", help="Execute diagnostic integrity checks")
    subparsers.add_parser("repos", help="Discover and display GitHub repositories")

    audit_parser = subparsers.add_parser("audit", help="Run deep 10-layer audit")
    audit_parser.add_argument("--repo", help="Target repository (owner/name)")

    subparsers.add_parser("run", help="Run a single autonomous engineering cycle")
    subparsers.add_parser("status", help="Show worker and scheduling status")
    subparsers.add_parser("start", help="Start background daemon loop")
    subparsers.add_parser("stop", help="Stop background daemon")

    findings_parser = subparsers.add_parser("findings", help="List audit findings")
    findings_parser.add_argument("--repo", help="Filter by repository")

    find_detail_parser = subparsers.add_parser("finding", help="View finding detail")
    find_detail_parser.add_argument("id", help="Finding ID")

    approve_parser = subparsers.add_parser("approve", help="Approve finding for auto-repair")
    approve_parser.add_argument("id", help="Finding ID")

    reject_parser = subparsers.add_parser("reject", help="Reject/ignore finding")
    reject_parser.add_argument("id", help="Finding ID")

    subparsers.add_parser("pause", help="Pause autonomous mutations")
    subparsers.add_parser("resume", help="Resume autonomous mutations")
    subparsers.add_parser("emergency-stop", help="Immediately suspend all operations")
    subparsers.add_parser("install", help="Register Windows Task Scheduler auto-start")
    subparsers.add_parser("uninstall", help="Remove Windows Task Scheduler auto-start")

    dash_parser = subparsers.add_parser("dashboard", help="Start local web console")
    dash_parser.add_argument("--host", default="127.0.0.1")
    dash_parser.add_argument("--port", type=int, default=8765)

    backup_parser = subparsers.add_parser("backup", help="Create database backup")
    backup_parser.add_argument("--dest", help="Backup destination directory")

    subparsers.add_parser("config", help="Display effective configuration")

    args = parser.parse_args()

    handlers = {
        "doctor": cmd_doctor,
        "self-test": cmd_self_test,
        "repos": cmd_repos,
        "audit": cmd_audit,
        "run": cmd_run,
        "status": cmd_status,
        "start": cmd_start,
        "stop": cmd_stop,
        "findings": cmd_findings,
        "finding": cmd_finding_detail,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "pause": cmd_pause,
        "resume": cmd_resume,
        "emergency-stop": cmd_emergency_stop,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "dashboard": cmd_dashboard,
        "backup": cmd_backup,
        "config": cmd_config,
    }

    if args.command in handlers:
        handlers[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
