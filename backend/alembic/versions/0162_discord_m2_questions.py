"""Durable Discord M2 questions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0162_discord_m2_questions"
down_revision = "0161_recording_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("discord_m2_questions",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column("link_id", UUID(), sa.ForeignKey("discord_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", UUID(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("context_key", sa.String(64), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("message_id", sa.String(32)),
        sa.Column("reason_code", sa.String(40)),
        sa.Column("comment", sa.Text()),
        sa.Column("choice", sa.String(2)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("link_id", "day", "task_id", "kind", "context_key", name="uq_discord_m2_question"),
    )
    for column in ("link_id", "task_id", "day"):
        op.create_index(f"ix_discord_m2_questions_{column}", "discord_m2_questions", [column])


def downgrade():
    op.drop_table("discord_m2_questions")
