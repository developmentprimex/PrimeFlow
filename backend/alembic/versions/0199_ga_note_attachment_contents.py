"""Store PX Notes attachment contents in the shared database."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0199_ga_note_attachment_contents"
down_revision = "0198_ga_reminder_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ga_note_attachment_contents",
        sa.Column("attachment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["ga_note_attachments.id"], ondelete="CASCADE"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("ga_note_attachment_contents")
