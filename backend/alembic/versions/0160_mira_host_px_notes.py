"""Mira Host: link the PX Notes Mira saves during a 1H, so PX Notes marks them as hers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = '0160_mira_host_px_notes'
down_revision = '0159_mira_host_join_attempts'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('mira_1h_events', sa.Column('note_id', UUID(as_uuid=True),
                  sa.ForeignKey('ga_notes.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_mira_1h_events_note_id', 'mira_1h_events', ['note_id'])


def downgrade():
    op.drop_index('ix_mira_1h_events_note_id', table_name='mira_1h_events')
    op.drop_column('mira_1h_events', 'note_id')
