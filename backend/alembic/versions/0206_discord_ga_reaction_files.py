"""Restore the deployed attachment count for Discord GA reactions."""

import sqlalchemy as sa
from alembic import op


revision = "0206_discord_ga_reaction_files"
down_revision = "0205_px_note_email_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discord_ga_reactions", sa.Column("attachment_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("discord_ga_reactions", "attachment_count")
