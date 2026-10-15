"""Initial audit-trail schema (what create_all produced before Alembic).

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_message_id", sa.String(), nullable=False),
        sa.Column("sender", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "extraction_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email_message_id", sa.String(), sa.ForeignKey("email_messages.id"), nullable=False),
        sa.Column("intent", sa.String(), nullable=False),
        sa.Column("intent_confidence", sa.Float(), nullable=False),
        sa.Column("extracted_fields", sa.JSON(), nullable=False),
        sa.Column("model_raw_response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "proposed_actions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email_message_id", sa.String(), sa.ForeignKey("email_messages.id"), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("target_system", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("record_id", sa.String(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("candidate_matches", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("proposed_action_id", sa.String(), sa.ForeignKey("proposed_actions.id"), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("edited_fields", sa.JSON(), nullable=True),
        sa.Column("approver", sa.String(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "execution_results",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("approval_decision_id", sa.String(), sa.ForeignKey("approval_decisions.id"), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "execution_results",
        "approval_decisions",
        "proposed_actions",
        "extraction_results",
        "email_messages",
    ):
        op.drop_table(table)
