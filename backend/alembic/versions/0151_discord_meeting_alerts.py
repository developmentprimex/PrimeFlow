"""Discord meeting reminders and start alerts, one per person and occurrence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0151_discord_meeting_alerts"
down_revision = "0150_marker_comment_inbox"
branch_labels = None
depends_on = None


def upgrade():
    # The table may already exist if its SQL was run by hand in pgAdmin.
    if sa.inspect(op.get_bind()).has_table("discord_meeting_alerts"):
        return
    op.create_table("discord_meeting_alerts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("link_id", pg.UUID(as_uuid=True), sa.ForeignKey("discord_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meeting_id", pg.UUID(as_uuid=True), sa.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurrence_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("message_id", sa.String(32)),
        sa.UniqueConstraint("link_id", "meeting_id", "occurrence_starts_at", "kind", name="uq_discord_meeting_alert"))
    op.create_index("ix_discord_meeting_alerts_meeting_id", "discord_meeting_alerts", ["meeting_id"])


def downgrade():
    op.drop_table("discord_meeting_alerts")
