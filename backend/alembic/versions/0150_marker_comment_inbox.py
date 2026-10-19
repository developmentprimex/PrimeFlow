"""Persistent per-person inbox for task symbol comments.

Revision ID: 0150_marker_comment_inbox
Revises: 0149_discord_agent_runs
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0150_marker_comment_inbox"
down_revision = "0149_discord_agent_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_marker_comment_inbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_key", sa.String(80), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_ids", postgresql.JSONB(), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revision", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marker", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_key", "user_id", name="uq_marker_comment_source_user"),
    )
    op.create_index("ix_task_marker_comment_inbox_user_id", "task_marker_comment_inbox", ["user_id"])
    op.create_index("ix_task_marker_comment_inbox_task_id", "task_marker_comment_inbox", ["task_id"])
    # Existing comments enter the persistent inbox without sending old notifications.
    # Never invent an author: earlier symbol comments did not record one.
    op.execute("""
        WITH source_tasks AS (
            SELECT t.*, CASE
                WHEN plan_note_origin_id IS NOT NULL THEN 'plan:' || plan_note_origin_id
                WHEN ga_note_origin_id IS NOT NULL THEN 'ga:' || ga_note_origin_id
                WHEN fast_task_group_id IS NOT NULL THEN 'group:' || fast_task_group_id
                ELSE 'task:' || id END AS source_key
            FROM tasks t
            WHERE is_active AND one_h_marker IS NOT NULL AND btrim(coalesce(one_h_marker_comment, '')) <> ''
        ), recipients AS (
            SELECT id AS task_id, assigned_to AS user_id FROM source_tasks WHERE assigned_to IS NOT NULL
            UNION SELECT id, created_by FROM source_tasks WHERE created_by IS NOT NULL
            UNION SELECT a.task_id, a.user_id FROM task_assignees a JOIN source_tasks t ON t.id = a.task_id
        ), latest AS (
            SELECT DISTINCT ON (t.source_key, r.user_id) t.*, r.user_id
            FROM source_tasks t JOIN recipients r ON r.task_id = t.id
            JOIN users u ON u.id = r.user_id AND u.is_active
            ORDER BY t.source_key, r.user_id, (t.assigned_to = r.user_id) DESC NULLS LAST, t.updated_at DESC, t.id
        )
        INSERT INTO task_marker_comment_inbox
            (id, source_key, user_id, task_id, task_ids, revision, marker, comment, updated_at)
        SELECT gen_random_uuid(), l.source_key, l.user_id, l.id,
            (SELECT jsonb_agg(t.id::text) FROM source_tasks t WHERE t.source_key = l.source_key),
            gen_random_uuid(), l.one_h_marker, btrim(l.one_h_marker_comment), l.updated_at
        FROM latest l
    """)


def downgrade():
    op.drop_table("task_marker_comment_inbox")
