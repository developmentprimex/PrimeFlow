"""Store the original comment timestamp separately from inbox revisions."""

import sqlalchemy as sa
from alembic import op

revision = "0201_marker_comment_created_at"
down_revision = "0200_discord_ga_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old rows only record the latest revision or the time used at import.
    op.add_column("task_marker_comment_inbox", sa.Column("comment_created_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("task_marker_comment_inbox", "comment_created_at")
