"""Placeholder for a migration applied to production but never committed.

The production database is stamped 0150_marker_comment_inbox and its schema
changes are already applied there. This file only lets Alembic recognise the
revision so deploys can continue. When the original marker comment inbox
migration is committed, it must REPLACE this file (same revision id) instead
of being added next to it.
"""

revision = "0150_marker_comment_inbox"
down_revision = "0149_discord_agent_runs"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
