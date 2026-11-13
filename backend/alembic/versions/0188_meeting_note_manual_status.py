"""Store meeting-note status independently of linked tasks.

Existing notes start at TODO; task statuses are deliberately not imported.
"""
from alembic import op
import sqlalchemy as sa

revision = "0188_meeting_note_manual_status"
down_revision = "0187_mailbox_connection"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("meeting_notes", sa.Column("manual_status", sa.String(32), nullable=False, server_default="TODO"))
    op.create_check_constraint("meeting_note_manual_status", "meeting_notes", "manual_status IN ('TODO','IN_PROGRESS','WAITING_CLIENT','WAITING_CONFIRMATION','DONE')")


def downgrade():
    op.drop_constraint("meeting_note_manual_status", "meeting_notes", type_="check")
    op.drop_column("meeting_notes", "manual_status")
