"""TENJIN Targeted Agent Task and Evidence Package Builder.

Assembles bounded evidence packages containing repository metadata, finding evidence,
targeted code snippets, allowed file scopes, and verification instructions.
Strictly avoids dumping entire repositories into model contexts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from tenjin.memory.models import FindingRecord, RepositoryRecord
from tenjin.policies.policy import EffectivePolicy
from tenjin.security.prompt_injection import build_isolated_context_wrapper


def build_evidence_package(
    repository: RepositoryRecord,
    base_sha: str,
    finding: FindingRecord,
    workspace_path: Path,
    policy: EffectivePolicy,
    repo_instructions_text: str = "",
    prior_attempts: Optional[List[str]] = None,
) -> str:
    """Construct an isolated, bounded task prompt for Antigravity repair."""
    # Read affected file content snippet if available
    file_snippet = ""
    if finding.file:
        target_file = workspace_path / finding.file
        if target_file.is_file():
            try:
                lines = target_file.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(0, (finding.line_start or 1) - 15)
                end = min(len(lines), (finding.line_end or finding.line_start or 1) + 15)
                snippet_lines = [f"{i+1}: {lines[i]}" for i in range(start, end)]
                file_snippet = "\n".join(snippet_lines)
            except Exception:
                file_snippet = "[Unable to read target file snippet]"

    allowed_scope_str = finding.file if finding.file else "Files directly relevant to the finding."
    protected_paths_str = ", ".join(policy.protected_paths)

    instructions_block = ""
    if repo_instructions_text:
        instructions_block = build_isolated_context_wrapper(
            repo_instructions_text[:3000],
            "Repository Guidelines (Untrusted Reference)",
        )

    prior_attempts_block = ""
    if prior_attempts:
        prior_attempts_block = "\n### Prior Attempt History\n" + "\n".join(
            f"- {att}" for att in prior_attempts
        )

    scope_details = (
        f"- Allowed Scope: {allowed_scope_str}\n"
        f"- Prohibited Scope (Never touch): {protected_paths_str}\n"
        f"- Max Files Allowed: {policy.max_files}\n"
        f"- Max Net Lines: {policy.max_lines}\n"
    )
    if policy.allow_major_revamps:
        scope_details += "- Substantial engineering changes and multi-file refactoring are fully authorized and encouraged where beneficial.\n"

    prompt = f"""You are Antigravity, performing a bounded engineering maintenance mission for TENJIN based on an external audit.

### Repository Context
- Repository: {repository.full_name}
- Base Commit SHA: {base_sha}
- Working Directory: {workspace_path}

### Finding Details
- Finding ID: {finding.id}
- Category: {finding.category} / {finding.subcategory}
- Severity: {finding.severity.value}
- Title: {finding.title}
- Summary: {finding.summary}
- Concrete Evidence:
{finding.evidence}
- Target File: {finding.file or 'N/A'} (Lines {finding.line_start}-{finding.line_end})

### Relevant Code Snippet
```
{file_snippet}
```

{instructions_block}
{prior_attempts_block}

### Allowed Scope and Constraints
{scope_details}

### Engineering Mandates
0. STRICT DELETION GUARD: Under NO circumstances may you delete any existing tracked files in the repository. Deleting existing files is strictly forbidden and will trigger immediate failure, automatic baseline restoration, and mission rejection. You may modify existing files, add new files, or replace code within existing files, but existing tracked files must remain present.
1. Validate the finding independently. If the finding is a false positive, do not fabricate changes. Explain why in your notes.
2. If valid, implement a clean, robust, and permanent engineering solution.
3. Do not modify unrelated code or create unnecessary churn.
4. Do not weaken tests or delete security controls to make checks pass.
5. Do not disable linters, type checks, or security scanners.
6. Do not suppress exceptions without justification.
7. Include or update a regression test verifying the repair where practical.
8. Return structured output matching the required JSON schema.
"""
    return prompt.strip()


def build_mission_task_prompt(
    repository: RepositoryRecord,
    base_sha: str,
    work_item: Any,
    workspace_path: Path,
    policy: EffectivePolicy,
    repo_instructions_text: str = "",
    prior_attempts: Optional[List[str]] = None,
) -> str:
    """Construct a comprehensive task prompt for a grouped maintenance work item."""
    affected_files = getattr(work_item, "affected_files", [])
    allowed_scope_str = ", ".join(affected_files) if affected_files else "Files relevant to this work item."
    protected_paths_str = ", ".join(policy.protected_paths)

    instructions_block = ""
    if repo_instructions_text:
        instructions_block = build_isolated_context_wrapper(
            repo_instructions_text[:3000],
            "Repository Guidelines (Untrusted Reference)",
        )

    prior_attempts_block = ""
    if prior_attempts:
        prior_attempts_block = "\n### Prior Attempt History\n" + "\n".join(
            f"- {att}" for att in prior_attempts
        )

    scope_details = (
        f"- Allowed Scope: {allowed_scope_str}\n"
        f"- Prohibited Scope (Never touch): {protected_paths_str}\n"
        f"- Max Files Allowed: {policy.max_files}\n"
        f"- Max Net Lines: {policy.max_lines}\n"
    )
    if policy.allow_major_revamps:
        scope_details += "- Substantial engineering changes and multi-file refactoring are fully authorized and encouraged where beneficial.\n"

    title = getattr(work_item, "title", "Maintenance Task")
    finding_ids = getattr(work_item, "finding_ids", [])
    evidence = getattr(work_item, "evidence", "")
    proposed_fix = getattr(work_item, "proposed_fix", "")

    prompt = f"""You are Antigravity, executing an autonomous daily maintenance mission for TENJIN.

### Repository Context
- Repository: {repository.full_name}
- Base Commit SHA: {base_sha}
- Working Directory: {workspace_path}

### Work Item Details
- Title: {title}
- Target Findings: {', '.join(finding_ids)}
- Affected Files: {', '.join(affected_files) if affected_files else 'Repository-wide'}
- Concrete Evidence / Problem Description:
{evidence}
- Proposed Architecture / Fix:
{proposed_fix or 'Determine the optimal engineering approach.'}

{instructions_block}
{prior_attempts_block}

### Allowed Scope and Constraints
{scope_details}

### Engineering Mandates
0. STRICT DELETION GUARD: Under NO circumstances may you delete any existing tracked files in the repository. Deleting existing files is strictly forbidden and will trigger immediate failure, automatic baseline restoration, and mission rejection. You may modify existing files, add new files, or replace code within existing files, but existing tracked files must remain present.
1. Analyze the issue thoroughly across all affected files.
2. Implement robust, high-quality, idiomatic code changes resolving the target issues.
3. When refactoring or revamping, preserve backward compatibility and ensure comprehensive unit tests pass.
4. Do not weaken tests or delete security controls to make checks pass.
5. Do not disable linters, type checks, or security scanners.
6. Do not suppress exceptions without justification.
7. Include or update tests verifying the improvements where practical.
8. Return structured output matching the required JSON schema.
"""
    return prompt.strip()
