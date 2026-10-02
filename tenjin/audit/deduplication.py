"""TENJIN Audit Finding Fingerprinting and Deduplication Engine.

Computes deterministic cryptographic fingerprints for audit findings to prevent
duplicate records across iterative runs, and accurately detects recurring regressions.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import List

from tenjin.core.constants import FindingStatus
from tenjin.memory.database import Database
from tenjin.memory.models import FindingHistoryRecord, FindingRecord


def compute_finding_fingerprint(
    repository: str,
    category: str,
    subcategory: str,
    file_path: str | None,
    evidence: str,
) -> str:
    """Generate a stable 16-character SHA-256 fingerprint for a finding.

    Normalizes whitespace and dynamic line numbers from evidence so minor edits
    in unrelated parts of the file do not alter the finding identity.
    """
    normalized_path = (file_path or "global").replace("\\", "/").lower()
    # Strip line numbers and timestamps from evidence before hashing
    normalized_evidence = re.sub(r"\bline\s+\d+\b", "line_N", evidence.lower())
    normalized_evidence = re.sub(r"\s+", " ", normalized_evidence).strip()

    raw_key = f"{repository.lower()}|{category.lower()}|{subcategory.lower()}|{normalized_path}|{normalized_evidence}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


def deduplicate_and_reconcile_findings(
    db: Database,
    run_id: str,
    raw_findings: List[FindingRecord],
) -> List[FindingRecord]:
    """Reconcile fresh findings against existing findings in database.

    - Reuses stable finding IDs for existing issues.
    - Promotes previously FIXED issues to RECURRING.
    - Preserves IGNORED status.
    - Creates new finding records and tracks history.
    """
    reconciled: List[FindingRecord] = []

    for f in raw_findings:
        existing = db.get_finding_by_fingerprint(f.fingerprint)

        if existing:
            # Preserve original ID
            f.id = existing.id
            f.detected_at = existing.detected_at

            if existing.status in (FindingStatus.FIXED, FindingStatus.VERIFIED):
                # Regression detected!
                f.status = FindingStatus.RECURRING
                db.record_finding_history(
                    FindingHistoryRecord(
                        fingerprint=f.fingerprint,
                        repository=f.repository,
                        run_id=run_id,
                        action="regression_detected",
                        details={
                            "previous_status": existing.status.value,
                            "new_status": FindingStatus.RECURRING.value,
                            "evidence": f.evidence[:200],
                        },
                    )
                )
            elif existing.status == FindingStatus.IGNORED:
                f.status = FindingStatus.IGNORED
            else:
                f.status = existing.status

            db.upsert_finding(f)
            reconciled.append(f)
        else:
            # Genuinely new finding
            f.id = f"find_{f.fingerprint[:8]}_{uuid.uuid4().hex[:4]}"
            f.status = FindingStatus.OPEN
            db.upsert_finding(f)
            db.record_finding_history(
                FindingHistoryRecord(
                    fingerprint=f.fingerprint,
                    repository=f.repository,
                    run_id=run_id,
                    action="first_detected",
                    details={
                        "category": f.category,
                        "severity": f.severity.value,
                        "title": f.title,
                    },
                )
            )
            reconciled.append(f)

    return reconciled
