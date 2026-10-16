"""Durable delegated task research and drafting runs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "0149_discord_agent_runs"
down_revision = "0148_discord_assistant"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("discord_agent_runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("link_id", pg.UUID(as_uuid=True), sa.ForeignKey("discord_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", pg.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("parent_run_id", pg.UUID(as_uuid=True), sa.ForeignKey("discord_agent_runs.id", ondelete="SET NULL")),
        sa.Column("request_id", sa.String(32), nullable=False, unique=True),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("target", pg.JSONB(), nullable=False),
        sa.Column("context", pg.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("response_id", sa.String(128)),
        sa.Column("result_text", sa.Text()),
        sa.Column("sources", pg.JSONB()),
        sa.Column("usage", pg.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("lease_token", pg.UUID(as_uuid=True)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("delivery_token", pg.UUID(as_uuid=True)),
        sa.Column("delivery_until", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("message_ids", pg.JSONB()),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("acceptance_request_id", sa.String(32)),
        sa.Column("acceptance_status", sa.String(24)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    for column in ("link_id", "task_id", "status"):
        op.create_index(f"ix_discord_agent_runs_{column}", "discord_agent_runs", [column])


def downgrade():
    op.drop_table("discord_agent_runs")

