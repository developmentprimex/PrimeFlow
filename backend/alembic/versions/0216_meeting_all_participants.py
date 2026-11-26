"""Record the ALL selection on internal meetings."""

import sqlalchemy as sa
from alembic import op

revision = "0216_meeting_all_participants"
down_revision = "0215_task_pause_until"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meetings", sa.Column("all_participants", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("meetings", "all_participants")
