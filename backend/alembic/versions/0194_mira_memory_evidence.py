"""Store structured evidence and follow-up on existing memory events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0194_mira_memory_evidence"
down_revision = "0193_merge_mira_quick_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mira_memory_events", sa.Column("details", JSONB(), nullable=True))
    op.create_index("ix_mira_memory_events_meeting_id", "mira_memory_events", ["meeting_id"])


def downgrade() -> None:
    op.drop_index("ix_mira_memory_events_meeting_id", table_name="mira_memory_events")
    op.drop_column("mira_memory_events", "details")
