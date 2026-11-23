"""Store the completion status of imported iPhone reminders."""

from alembic import op
import sqlalchemy as sa


revision = "0198_ga_reminder_completion"
down_revision = "0197_ga_discord_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ga_time_slot_entries",
        sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("ga_time_slot_entries", "is_completed")
