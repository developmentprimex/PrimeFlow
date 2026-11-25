"""Record GA acknowledgements of GA Devices work tasks."""
import sqlalchemy as sa

from alembic import op

revision = "0211_ga_device_reactions"
down_revision = "0210_ga_discord_reaction_order"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ga_device_reactions",
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("reacted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reacted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("ga_device_reactions")
