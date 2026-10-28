"""Persist the explicit choice to show a Mira note in the main PX Notes table."""
from alembic import op
import sqlalchemy as sa

revision = "0171_mira_notes_px_visibility"
down_revision = "0170_discord_one_h_reports"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ga_notes", sa.Column("mira_shared_to_px", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade():
    op.drop_column("ga_notes", "mira_shared_to_px")
