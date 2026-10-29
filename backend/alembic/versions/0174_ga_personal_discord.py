"""Private, persistent reminder outbox for the separate Kujtesa bot."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0174_ga_personal_discord"
down_revision = "0173_merge_mira_ga_personal"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("discord_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurrence_id", sa.Uuid(), nullable=False),
        sa.Column("schedule_key", sa.String(64), nullable=False),
        sa.Column("phase", sa.String(12), nullable=False),
        sa.Column("recipient", sa.String(40), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lease", sa.String(64)),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.Column("channel_id", sa.String(24)),
        sa.Column("message_id", sa.String(24)),
        sa.Column("details", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["occurrence_id"], ["ga_personal.occurrences.id"]),
        sa.UniqueConstraint("occurrence_id", "schedule_key", "phase", "recipient"),
        schema="ga_personal", if_not_exists=True)
    op.create_index("ix_ga_personal_discord_outbox_occurrence_id", "discord_outbox", ["occurrence_id"], schema="ga_personal", if_not_exists=True)


def downgrade():
    # Delivery history is retained; rollback never destroys family audit data.
    pass
