"""TENJIN Targeted Agent Task and Evidence Package Builder.

Assembles bounded evidence packages containing repository metadata, finding evidence,
targeted code snippets, allowed file scopes, and verification instructions.
Strictly avoids dumping entire repositories into model contexts.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

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

    allowed_scope_str = finding.file if finding.file else "Only files directly relevant to the finding."
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

    prompt = f"""You are Antigravity, performing a bounded engineering repair for TENJIN based on an external audit.

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
- Allowed Scope: {allowed_scope_str}
- Prohibited Scope (Never touch): {protected_paths_str}
- Max Files Allowed: {policy.max_files}
- Max Net Lines: {policy.max_lines}

### Engineering Mandates
1. Validate the finding independently. If the finding is a false positive, do not fabricate changes. Explain why in your notes.
2. If valid, implement the smallest, robust, minimal solution.
3. Do not modify unrelated code or refactor surrounding logic.
4. Do not weaken tests or delete security controls to make checks pass.
5. Do not disable linters, type checks, or security scanners.
6. Do not suppress exceptions without justification.
7. Include or update a regression test verifying the repair where practical.
8. Return structured output matching the required JSON schema.
"""
    return prompt.strip()
