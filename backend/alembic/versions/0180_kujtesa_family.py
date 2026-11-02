"""Private durable delivery queue for family agendas and presence announcements."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0180_kujtesa_family"
down_revision = "0179_recording_protocols"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("discord_notices",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("space_id", pg.UUID(as_uuid=True), sa.ForeignKey("ga_personal.spaces.id"), nullable=False),
        sa.Column("notice_key", sa.String(64), nullable=False),
        sa.Column("local_date", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lease", sa.String(64), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel_id", sa.String(24)), sa.Column("message_id", sa.String(24)),
        sa.Column("details", pg.JSONB(), nullable=False),
        sa.UniqueConstraint("space_id", "notice_key"), schema="ga_personal")
    op.create_index("ix_ga_personal_discord_notices_space_id", "discord_notices", ["space_id"], schema="ga_personal")


def downgrade():
    op.drop_table("discord_notices", schema="ga_personal")
