"""Keep timestamped task symbol comments for M1."""

from alembic import op
import sqlalchemy as sa


revision = "0203_task_symbol_comment_events"
down_revision = "0202_merge_mail_comment_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_symbol_comment_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marker", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_symbol_comment_events_created_at", "task_symbol_comment_events", ["created_at"])
    op.create_index("ix_task_symbol_comment_events_task_id", "task_symbol_comment_events", ["task_id"])
    op.execute("""
        INSERT INTO task_symbol_comment_events (task_id, marker, comment, created_at)
        SELECT DISTINCT task_id, marker, comment, comment_created_at
        FROM task_marker_comment_inbox
        WHERE comment_created_at = updated_at AND btrim(marker) <> '' AND btrim(comment) <> ''
    """)
    op.execute("""
        CREATE FUNCTION record_task_symbol_comment_event() RETURNS trigger AS $$
        DECLARE
            new_comment text := btrim(coalesce(NEW.one_h_marker_comment, ''));
        BEGIN
            IF btrim(coalesce(NEW.one_h_marker, '')) = '' OR new_comment = '' THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF new_comment = btrim(coalesce(OLD.one_h_marker_comment, '')) THEN
                    RETURN NEW;
                END IF;
            END IF;
            INSERT INTO task_symbol_comment_events (task_id, marker, comment, created_at)
            VALUES (NEW.id, NEW.one_h_marker, new_comment, statement_timestamp());
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_record_task_symbol_comment_event
        AFTER INSERT OR UPDATE OF one_h_marker, one_h_marker_comment ON tasks
        FOR EACH ROW EXECUTE FUNCTION record_task_symbol_comment_event()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_record_task_symbol_comment_event ON tasks")
    op.execute("DROP FUNCTION record_task_symbol_comment_event()")
    op.drop_table("task_symbol_comment_events")
