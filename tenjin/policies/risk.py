"""TENJIN Change Risk Evaluation Engine.

Analyzes modified file paths, diff volume, and sensitive component touchpoints
to categorize execution risk into TRIVIAL, LOW, MEDIUM, HIGH, or CRITICAL.
"""

from __future__ import annotations

from typing import List

from tenjin.core.constants import RiskLevel

SENSITIVE_DIRECTORY_KEYWORDS = [
    "auth",
    "security",
    "migration",
    "database",
    "credentials",
    "secrets",
    "workflows",
    "infra",
    "terraform",
    "deploy",
]


def evaluate_change_risk(
    files_changed: List[str],
    diff_text: str,
    baseline_risk: RiskLevel = RiskLevel.LOW,
    max_lines_threshold: int = 150,
    allow_major_revamps: bool = False,
) -> RiskLevel:
    """Calculate overall risk of a proposed code modification.

    Combines the finding's baseline risk, modified file paths, and total diff volume.
    When allow_major_revamps is True, large code diffs are not automatically marked HIGH
    risk, allowing comprehensive multi-file refactoring and engineering revamps while
    preserving strict CRITICAL/HIGH risk gates for credentials and security paths.
    """
    highest_risk = baseline_risk

    # Check for sensitive directories in modified files
    for file_path in files_changed:
        normalized = file_path.lower().replace("\\", "/")

        # Critical files
        if any(keyword in normalized for keyword in ["credentials", "secrets", ".pem", ".key"]):
            return RiskLevel.CRITICAL

        # High risk files
        if any(keyword in normalized for keyword in SENSITIVE_DIRECTORY_KEYWORDS):
            if highest_risk in [RiskLevel.TRIVIAL, RiskLevel.LOW, RiskLevel.MEDIUM]:
                highest_risk = RiskLevel.HIGH

    # Diff volume risk
    lines = diff_text.splitlines() if diff_text else []
    added_or_removed = [
        line_item
        for line_item in lines
        if (line_item.startswith("+") or line_item.startswith("-")) and not line_item.startswith(("+++", "---"))
    ]
    total_delta = len(added_or_removed)

    if allow_major_revamps:
        if total_delta > max_lines_threshold and highest_risk in [RiskLevel.TRIVIAL, RiskLevel.LOW]:
            highest_risk = RiskLevel.MEDIUM
    else:
        if total_delta > max_lines_threshold * 2:
            return RiskLevel.HIGH
        elif total_delta > max_lines_threshold:
            if highest_risk in [RiskLevel.TRIVIAL, RiskLevel.LOW]:
                highest_risk = RiskLevel.MEDIUM

    return highest_risk
