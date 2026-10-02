"""TENJIN Structured Report Generator.

Compiles complete, evidence-based Markdown and JSON audit and mutation reports
for every executed run. Ensures all secret credentials are redacted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from tenjin.memory.models import FindingRecord, GitActionRecord, RunRecord, VerificationRunRecord
from tenjin.security.redaction import redact_secrets


def generate_json_report(
    run: RunRecord,
    findings: List[FindingRecord],
    git_actions: List[GitActionRecord],
    verification_runs: List[VerificationRunRecord],
    output_dir: Path,
) -> Path:
    """Generate a structured, machine-readable JSON report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{run.run_id}.json"

    data = {
        "run_id": run.run_id,
        "repository": run.repository,
        "base_sha": run.base_sha,
        "head_sha": run.head_sha,
        "state": run.state.value,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "duration_seconds": run.duration_seconds,
        "autonomy_level": int(run.autonomy_level),
        "selection_rationale": run.selection_rationale,
        "findings_summary": {
            "total": len(findings),
            "critical": sum(1 for f in findings if f.severity.value == "critical"),
            "high": sum(1 for f in findings if f.severity.value == "high"),
            "medium": sum(1 for f in findings if f.severity.value == "medium"),
            "low": sum(1 for f in findings if f.severity.value == "low"),
            "informational": sum(1 for f in findings if f.severity.value == "informational"),
        },
        "findings": [f.model_dump() for f in findings],
        "git_actions": [g.model_dump() for g in git_actions],
        "verification_runs": [v.model_dump() for v in verification_runs],
        "error_message": run.error_message,
    }

    # Redact entire JSON string before writing
    clean_json = redact_secrets(json.dumps(data, indent=2))
    report_path.write_text(clean_json, encoding="utf-8")
    return report_path


def generate_markdown_report(
    run: RunRecord,
    findings: List[FindingRecord],
    git_actions: List[GitActionRecord],
    verification_runs: List[VerificationRunRecord],
    output_dir: Path,
) -> Path:
    """Generate a clean, professional engineering Markdown audit report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{run.run_id}.md"

    crit = sum(1 for f in findings if f.severity.value == "critical")
    high = sum(1 for f in findings if f.severity.value == "high")
    med = sum(1 for f in findings if f.severity.value == "medium")
    low = sum(1 for f in findings if f.severity.value == "low")

    commits = [g for g in git_actions if g.action_type == "commit"]
    prs = [g for g in git_actions if g.action_type == "pull_request"]

    md_lines = [
        f"# TENJIN Audit Report: `{run.repository}`",
        f"**Run ID**: `{run.run_id}` | **Status**: `{run.state.value}` | **Duration**: `{run.duration_seconds or 0.0}s`",
        "",
        "## Executive Summary",
        f"- **Base SHA**: `{run.base_sha or 'N/A'}`",
        f"- **Autonomy Level**: `Level {int(run.autonomy_level)}`",
        f"- **Selection Rationale**: {run.selection_rationale or 'Autonomous prioritization'}",
        f"- **Findings Detected**: {len(findings)} (Critical: {crit}, High: {high}, Medium: {med}, Low: {low})",
        f"- **Commits Created**: {len(commits)}",
        f"- **Pull Requests Opened**: {len(prs)}",
        "",
        "---",
        "## Audit Findings Breakdown",
    ]

    if not findings:
        md_lines.append("*No open findings detected across all 10 audit layers.*")
    else:
        for idx, f in enumerate(findings, start=1):
            md_lines.extend([
                f"### {idx}. [{f.severity.value.upper()}] {f.title}",
                f"- **Category**: `{f.category}` / `{f.subcategory}`",
                f"- **Fingerprint**: `{f.fingerprint}` | **Status**: `{f.status.value}`",
                f"- **File**: `{f.file or 'N/A'}` (Lines: {f.line_start or 'N/A'}-{f.line_end or 'N/A'})",
                f"- **Risk**: `{f.risk.value}` | **Autofix Eligible**: `{'Yes' if f.autofix_eligibility else 'No'}`",
                "",
                "**Summary**:",
                f"{f.summary}",
                "",
                "**Evidence**:",
                "```",
                f"{f.evidence}",
                "```",
                "",
                f"**Suggested Remediation**: {f.suggested_fix or 'N/A'}",
                "",
            ])

    if git_actions:
        md_lines.extend([
            "---",
            "## Git Version Control Actions",
        ])
        for g in git_actions:
            md_lines.append(f"- **{g.action_type.upper()}**: `{g.branch_name or g.commit_sha or g.pr_url}` ({g.status})")

    if run.error_message:
        md_lines.extend([
            "---",
            "## Errors & Diagnostics",
            f"```\n{run.error_message}\n```",
        ])

    clean_md = redact_secrets("\n".join(md_lines))
    report_path.write_text(clean_md, encoding="utf-8")
    return report_path
