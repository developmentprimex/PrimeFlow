"""Separate read-only Microsoft mailbox connection."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0187_mailbox_connection"
down_revision = "0186_meeting_clients"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mailbox_connections",
        sa.Column("mailbox_email", sa.String(320), primary_key=True),
        sa.Column("mailbox_type", sa.String(32), nullable=False),
        sa.Column("connected_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("mailbox_connections")
