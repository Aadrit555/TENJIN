"""TENJIN Change Risk Evaluation Engine.

Analyzes modified file paths, diff volume, and sensitive component touchpoints
to categorize execution risk into TRIVIAL, LOW, MEDIUM, HIGH, or CRITICAL.
"""

from __future__ import annotations

from typing import List, Optional
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
) -> RiskLevel:
    """Calculate overall risk of a proposed code modification.

    Combines the finding's baseline risk, modified file paths, and total diff volume.
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
    added_or_removed = [l for l in lines if (l.startswith("+") or l.startswith("-")) and not l.startswith(("+++", "---"))]
    total_delta = len(added_or_removed)

    if total_delta > max_lines_threshold * 2:
        return RiskLevel.HIGH
    elif total_delta > max_lines_threshold:
        if highest_risk in [RiskLevel.TRIVIAL, RiskLevel.LOW]:
            highest_risk = RiskLevel.MEDIUM

    return highest_risk
