"""TENJIN Core Constants and Enumerations.

Defines all formal state machines, severity levels, risk classifications,
and autonomy levels used across the system.
"""

from enum import Enum, IntEnum


class AutonomyLevel(IntEnum):
    """Autonomy levels controlling autonomous mutations.

    Level 0: Observe only (discovery and metadata collection)
    Level 1: Audit + Report (read-only 10-layer audit and reporting, DEFAULT)
    Level 2: Audit + Propose repairs (plans repairs without branch/code changes)
    Level 3: Audit + Repair in isolated branch + Verify + Commit
    Level 4: Audit + Repair + Verify + Commit + Push branch
    Level 5: Audit + Repair + Verify + Commit + Push branch + Pull Request
    Level 6: Automatic merge (strictly opt-in with explicit branch protection policy)
    """
    LEVEL_0_OBSERVE = 0
    LEVEL_1_AUDIT_REPORT = 1
    LEVEL_2_PROPOSE_REPAIRS = 2
    LEVEL_3_COMMIT_BRANCH = 3
    LEVEL_4_PUSH_BRANCH = 4
    LEVEL_5_PULL_REQUEST = 5
    LEVEL_6_AUTO_MERGE = 6


class State(str, Enum):
    """The 22 explicit persistent states of the TENJIN repository lifecycle."""
    DISCOVERING = "DISCOVERING"
    QUEUED = "QUEUED"
    SELECTING = "SELECTING"
    PREPARING = "PREPARING"
    SYNCING = "SYNCING"
    INVENTORYING = "INVENTORYING"
    AUDITING = "AUDITING"
    PLANNING = "PLANNING"
    WAITING_FOR_AGENT = "WAITING_FOR_AGENT"
    AGENT_RUNNING = "AGENT_RUNNING"
    VERIFYING = "VERIFYING"
    REPAIRING = "REPAIRING"
    REVERIFYING = "REVERIFYING"
    READY_TO_COMMIT = "READY_TO_COMMIT"
    COMMITTING = "COMMITTING"
    PUSHING = "PUSHING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class FindingSeverity(str, Enum):
    """Severity ratings for audit findings."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class FindingStatus(str, Enum):
    """Lifecycle status of an individual finding."""
    OPEN = "open"
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    VERIFIED = "verified"
    FAILED = "failed"
    DEFERRED = "deferred"
    RECURRING = "recurring"


class FindingSource(str, Enum):
    """Origin of the audit finding."""
    DETERMINISTIC = "deterministic"
    GITHUB = "github"
    SECURITY_SCANNER = "security_scanner"
    STATIC_ANALYSIS = "static_analysis"
    AI = "ai"
    COMBINED = "combined"


class RiskLevel(str, Enum):
    """Risk classification for code modifications and repairs."""
    TRIVIAL = "trivial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolStatus(str, Enum):
    """Status of discovered external tools in the environment."""
    AVAILABLE = "AVAILABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
