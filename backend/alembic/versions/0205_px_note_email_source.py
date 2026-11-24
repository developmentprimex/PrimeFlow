"""Preserve the source email for PX Notes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "0205_px_note_email_source"
down_revision = "0204_merge_pause_symbol_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ga_notes", sa.Column("email_metadata", JSONB(), nullable=True))
    op.add_column("ga_notes", sa.Column("email_body", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ga_notes", "email_body")
    op.drop_column("ga_notes", "email_metadata")
