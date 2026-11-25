"""Link replies sent through PrimeFlow to the originating GA mentions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0208_ga_discord_reply_context"
down_revision = "0207_ga_discord_channel_archive"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ga_discord_channel_messages",
                  sa.Column("reply_context_ids", postgresql.JSONB(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("ga_discord_channel_messages", "reply_context_ids")
