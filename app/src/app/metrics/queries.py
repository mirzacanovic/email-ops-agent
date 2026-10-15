"""Numbers for the metrics page, computed from the audit trail alone -- no
separate counters to drift out of sync with what actually happened.
"""

from dataclasses import dataclass, field
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import (
    ApprovalDecision,
    EmailMessage,
    ExecutionResult,
    ExtractionResult,
    ProposedAction,
)

# (label, inclusive lower bound, exclusive upper bound) over a 0..1 confidence
CONFIDENCE_BUCKETS = [
    ("0–50%", 0.0, 0.5),
    ("50–80%", 0.5, 0.8),
    ("80–100%", 0.8, 1.01),
]


@dataclass
class Metrics:
    emails_processed: int = 0
    proposals: int = 0
    pending: int = 0
    decided: int = 0
    approved: int = 0
    rejected: int = 0
    # share of decided proposals that were approved; None until one is decided
    approval_rate: float | None = None
    executed: int = 0
    execution_failures: int = 0
    median_seconds_to_decision: float | None = None
    by_action_type: dict[str, int] = field(default_factory=dict)
    by_intent: dict[str, int] = field(default_factory=dict)
    confidence_distribution: dict[str, int] = field(default_factory=dict)


def compute_metrics(db: Session) -> Metrics:
    m = Metrics()
    m.emails_processed = db.scalar(select(func.count()).select_from(EmailMessage)) or 0
    m.proposals = db.scalar(select(func.count()).select_from(ProposedAction)) or 0

    m.by_action_type = {
        action_type: count
        for action_type, count in db.execute(
            select(ProposedAction.action_type, func.count()).group_by(ProposedAction.action_type)
        )
    }
    m.by_intent = {
        intent: count
        for intent, count in db.execute(
            select(ExtractionResult.intent, func.count()).group_by(ExtractionResult.intent)
        )
    }

    confidences = db.scalars(select(ProposedAction.confidence)).all()
    m.confidence_distribution = {
        label: sum(1 for c in confidences if low <= c < high)
        for label, low, high in CONFIDENCE_BUCKETS
    }

    decisions = db.execute(
        select(ApprovalDecision.decision, ApprovalDecision.decided_at, ProposedAction.created_at)
        .join(ProposedAction, ApprovalDecision.proposed_action_id == ProposedAction.id)
    ).all()
    m.decided = len(decisions)
    m.pending = m.proposals - m.decided
    m.approved = sum(1 for d in decisions if d.decision in ("approved", "edited"))
    m.rejected = sum(1 for d in decisions if d.decision == "rejected")
    if m.decided:
        m.approval_rate = m.approved / m.decided
        # Time a human took to act on a proposal (proposal created -> decision).
        m.median_seconds_to_decision = median(
            (d.decided_at - d.created_at).total_seconds() for d in decisions
        )

    outcomes = db.scalars(select(ExecutionResult.success)).all()
    m.executed = sum(1 for ok in outcomes if ok)
    m.execution_failures = sum(1 for ok in outcomes if not ok)
    return m
