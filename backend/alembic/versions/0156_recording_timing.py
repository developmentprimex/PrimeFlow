"""On-demand citation timing, independent from transcription."""
from alembic import op

revision = '0156_recording_timing'
down_revision = '0155_recording_analysis_quality'
branch_labels = None
depends_on = None


def upgrade():
    # A shared database may receive the additive incident repair before deployment.
    op.execute('ALTER TABLE recording_analyses ADD COLUMN IF NOT EXISTS timing JSONB NULL')


def downgrade():
    op.drop_column('recording_analyses', 'timing')
