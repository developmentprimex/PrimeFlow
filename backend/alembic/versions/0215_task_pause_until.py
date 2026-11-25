"""Store the task pause independently of status."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0215_task_pause_until"
down_revision = "0214_merge_rlz_iphone_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("pause_periods", JSONB(), nullable=True))
    # Recover the status from the latest transition into PAUSED where available.
    op.execute("""
        WITH restored AS (
            SELECT t.id, COALESCE(
                (
                    SELECT a.before ->> 'status'
                    FROM audit_logs a
                    WHERE a.entity_type = 'task' AND a.entity_id = t.id
                      AND a.after ->> 'status' = 'PAUSED'
                      AND a.before ->> 'status' IN
                          ('TODO', 'IN_PROGRESS', 'WAITING_CLIENT', 'WAITING_CONFIRMATION')
                    ORDER BY a.created_at DESC, a.id DESC
                    LIMIT 1
                ),
                CASE WHEN t.progress_percentage > 0 THEN 'IN_PROGRESS' ELSE 'TODO' END
            ) AS prior_status
            FROM tasks t WHERE t.status = 'PAUSED'
        )
        UPDATE tasks t
        SET status = r.prior_status,
            resumed_from_pause = (r.prior_status = 'IN_PROGRESS'),
            pause_periods = CASE WHEN t.is_active AND t.question_origin_id IS NULL
                THEN jsonb_build_array(jsonb_build_object(
                    'from', (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Tirane')::date,
                    'until', (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Tirane')::date
                )) END
        FROM restored r WHERE r.id = t.id
    """)
    # Old daily PAUSED rows otherwise carry the stopped status into future
    # planner days. Keep the recorded dates and restore the daily work status.
    op.execute("""
        WITH history AS (
            SELECT task_id, jsonb_agg(
                jsonb_build_object('from', day_date, 'until', day_date) ORDER BY day_date
            ) AS periods
            FROM task_daily_progress
            WHERE daily_status = 'PAUSED'
              AND day_date < (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Tirane')::date
            GROUP BY task_id
        )
        UPDATE tasks t
        SET pause_periods = h.periods || COALESCE(t.pause_periods, '[]'::jsonb)
        FROM history h WHERE h.task_id = t.id
    """)
    op.execute("""
        UPDATE task_daily_progress p
        SET daily_status = COALESCE(
            (
                SELECT previous.daily_status
                FROM task_daily_progress previous
                WHERE previous.task_id = p.task_id AND previous.day_date < p.day_date
                  AND previous.daily_status IN
                      ('TODO', 'IN_PROGRESS', 'WAITING_CLIENT', 'WAITING_CONFIRMATION')
                ORDER BY previous.day_date DESC
                LIMIT 1
            ),
            CASE WHEN t.status IN ('TODO', 'IN_PROGRESS', 'WAITING_CLIENT', 'WAITING_CONFIRMATION')
                 THEN t.status WHEN p.completed_value > 0 THEN 'IN_PROGRESS' ELSE 'TODO' END
        )
        FROM tasks t
        WHERE t.id = p.task_id AND p.daily_status = 'PAUSED'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE task_daily_progress p SET daily_status = 'PAUSED'
        FROM tasks t
        WHERE t.id = p.task_id AND p.daily_status <> 'DONE' AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(t.pause_periods) pause
            WHERE p.day_date BETWEEN (pause ->> 'from')::date AND (pause ->> 'until')::date
        )
    """)
    op.execute("""
        UPDATE tasks t SET status = 'PAUSED', resumed_from_pause = false
        WHERE status <> 'DONE' AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(t.pause_periods) p
            WHERE (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Tirane')::date
                BETWEEN (p ->> 'from')::date AND (p ->> 'until')::date
        )
    """)
    op.drop_column("tasks", "pause_periods")
