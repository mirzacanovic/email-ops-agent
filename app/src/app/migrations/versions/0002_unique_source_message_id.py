"""One row per source message: unique email_messages.source_message_id.

The poller dedups on this column (see ingestion/inbox_poller.py); the
constraint is the database-level backstop. Fails if duplicate rows already
exist -- e.g. from the overlapping-poll race the poll lock now prevents --
so those have to be cleaned up by hand first.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import context, op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

CONSTRAINT = "uq_email_messages_source_message_id"


def upgrade() -> None:
    # The check needs a live connection, so it is skipped for `--sql` output.
    dupes = (
        []
        if context.is_offline_mode()
        else op.get_bind()
        .execute(
            sa.text(
                "SELECT source_message_id FROM email_messages "
                "GROUP BY source_message_id HAVING count(*) > 1"
            )
        )
        .all()
    )
    if dupes:
        ids = ", ".join(str(row[0]) for row in dupes)
        raise RuntimeError(
            f"Cannot add {CONSTRAINT}: duplicate source_message_id rows exist ({ids}). "
            "Delete the duplicates (and their dependent audit rows) and re-run."
        )
    with op.batch_alter_table("email_messages") as batch:
        batch.create_unique_constraint(CONSTRAINT, ["source_message_id"])


def downgrade() -> None:
    with op.batch_alter_table("email_messages") as batch:
        batch.drop_constraint(CONSTRAINT, type_="unique")
