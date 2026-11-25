"""Keep iPhone reminder completion requests across Shortcut imports."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0213_iphone_reminder_completion"
down_revision = "0212_ga_reaction_source"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ga_time_slot_entries", sa.Column("reminder_source", JSONB()))
    op.add_column("ga_time_slot_entries", sa.Column("completion_requested_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("ga_time_slot_entries", "completion_requested_at")
    op.drop_column("ga_time_slot_entries", "reminder_source")
