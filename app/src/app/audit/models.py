"""Append-only audit trail. Every row is written once and never mutated;
corrections happen by inserting a new row, so the full history of a
decision is always reconstructable from `email_message_id` alone.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmailMessage(Base):
    """Raw input, exactly as received from the email simulator (or, later,
    a real inbox)."""

    __tablename__ = "email_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    source_message_id: Mapped[str] = mapped_column(String)  # id from the simulator/inbox
    sender: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExtractionResult(Base):
    """Output of classify + extract for one email."""

    __tablename__ = "extraction_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email_message_id: Mapped[str] = mapped_column(ForeignKey("email_messages.id"))
    intent: Mapped[str] = mapped_column(String)
    intent_confidence: Mapped[float] = mapped_column()
    extracted_fields: Mapped[dict] = mapped_column(JSON)
    model_raw_response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProposedAction(Base):
    """A candidate action the pipeline decided on, not yet executed."""

    __tablename__ = "proposed_actions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email_message_id: Mapped[str] = mapped_column(ForeignKey("email_messages.id"))
    action_type: Mapped[str] = mapped_column(String)  # create_record | update_record
    target_system: Mapped[str] = mapped_column(String)  # espocrm | plane
    entity_type: Mapped[str] = mapped_column(String)
    record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    fields: Mapped[dict] = mapped_column(JSON)
    candidate_matches: Mapped[list] = mapped_column(JSON)  # all matches considered
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApprovalDecision(Base):
    """A human's decision on a ProposedAction."""

    __tablename__ = "approval_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    proposed_action_id: Mapped[str] = mapped_column(ForeignKey("proposed_actions.id"))
    decision: Mapped[str] = mapped_column(String)  # approved | edited | rejected
    edited_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approver: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ExecutionResult(Base):
    """Outcome of actually calling the target system's API."""

    __tablename__ = "execution_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    approval_decision_id: Mapped[str] = mapped_column(ForeignKey("approval_decisions.id"))
    success: Mapped[bool] = mapped_column()
    response_payload: Mapped[dict] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
