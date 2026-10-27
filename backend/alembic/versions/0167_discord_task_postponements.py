"""Allow approved Discord postponements from any owned task card."""
from alembic import op
import sqlalchemy as sa

revision = '0167_discord_task_postponements'
down_revision = '0166_merge_mira_repetitive'
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column('discord_m2_postponements', 'question_id', existing_type=sa.UUID(), nullable=True)

def downgrade():
    # Do not delete approval history to force a downgrade.
    op.execute("DO $$ BEGIN IF EXISTS (SELECT 1 FROM discord_m2_postponements WHERE question_id IS NULL) THEN RAISE EXCEPTION 'General Discord postponement history exists; cannot restore NOT NULL'; END IF; END $$")
    op.alter_column('discord_m2_postponements', 'question_id', existing_type=sa.UUID(), nullable=False)
