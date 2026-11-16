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


def _resize_columns(old_size, new_size):
    # PostgreSQL refuses ALTER TYPE while this UPDATE OF trigger depends on
    # one_h_marker. Recreate the same trigger within Alembic's transaction;
    # the function and existing history rows remain intact.
    op.execute("DROP TRIGGER IF EXISTS trg_sync_task_one_h_marker_history ON tasks")
    for table, column in COLUMNS:
        op.alter_column(table, column, existing_type=sa.String(old_size), type_=sa.String(new_size))
    op.execute("""
        CREATE TRIGGER trg_sync_task_one_h_marker_history
        AFTER INSERT OR UPDATE OF one_h_marker, one_h_marker_date,
            one_h_marker_by_ga, one_h_marker_comment ON tasks
        FOR EACH ROW EXECUTE FUNCTION sync_task_one_h_marker_history()
    """)


def upgrade():
    _resize_columns(16, 32)


def downgrade():
    connection = op.get_bind()
    for table, column in COLUMNS:
        if connection.scalar(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table}" WHERE length("{column}") > 16)')):
            raise RuntimeError("Remove combined task symbols before downgrading to 16-character storage")
    _resize_columns(32, 16)
