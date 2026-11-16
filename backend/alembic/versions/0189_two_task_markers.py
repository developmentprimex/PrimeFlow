"""Allow two task symbols while preserving existing single-symbol values."""
from alembic import op
import sqlalchemy as sa

revision = "0189_two_task_markers"
down_revision = "0188_meeting_note_manual_status"
branch_labels = None
depends_on = None

COLUMNS = (
    ("tasks", "one_h_marker"),
    ("ga_notes", "one_h_marker"),
    ("plan_notes", "one_h_marker"),
    ("task_one_h_marker_history", "one_h_marker"),
    ("task_marker_comment_inbox", "marker"),
)


def upgrade():
    for table, column in COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(16), type_=sa.String(32))


def downgrade():
    connection = op.get_bind()
    for table, column in COLUMNS:
        if connection.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" WHERE length("{column}") > 16)')):
            raise RuntimeError("Remove combined task symbols before downgrading to 16-character storage")
    for table, column in COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(32), type_=sa.String(16))
