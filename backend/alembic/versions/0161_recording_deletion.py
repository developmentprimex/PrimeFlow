"""Management-only removal of recordings from the library."""
from alembic import op
import sqlalchemy as sa

revision = '0161_recording_deletion'
down_revision = '0160_mira_host_px_notes'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('meeting_recordings', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('meeting_recordings', sa.Column('files_purged_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_deleted_at', 'meeting_recordings', ['deleted_at'])


def downgrade():
    op.drop_index('ix_deleted_at', table_name='meeting_recordings')
    op.drop_column('meeting_recordings', 'deleted_at')
    op.drop_column('meeting_recordings', 'files_purged_at')
