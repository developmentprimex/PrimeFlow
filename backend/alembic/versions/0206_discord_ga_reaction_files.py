"""Retain source message details for GA reaction attachments."""

import sqlalchemy as sa
from alembic import op


revision = "0206_discord_ga_reaction_files"
down_revision = "0205_px_note_email_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discord_ga_reactions", sa.Column("message_channel_id", sa.String(32)))
    op.add_column("discord_ga_reactions", sa.Column("message_author_id", sa.String(32)))
    op.add_column("discord_ga_reactions", sa.Column("attachment_count", sa.Integer()))


def downgrade() -> None:
    op.drop_column("discord_ga_reactions", "attachment_count")
    op.drop_column("discord_ga_reactions", "message_author_id")
    op.drop_column("discord_ga_reactions", "message_channel_id")
