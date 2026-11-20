from sqlalchemy import select

from app.models.discord_assistant import DiscordLink
from app.models.discord_m3_question import DiscordM3Question
from app.models.task_plan_feedback import TaskPlanFeedback


def finance_feedback_user(user):
    return (user.full_name or "").strip().casefold() == "haxhere spahiu"


async def load_task_plan_feedback(db, target_date, task_ids):
    if not task_ids:
        return {}
    question = DiscordM3Question
    answers = (await db.execute(
        select(question.task_id, DiscordLink.user_id, question.answer, question.comment, question.answered_at)
        .join(DiscordLink, DiscordLink.id == question.link_id)
        .where(question.kind == "tomorrow_task", question.target_date == target_date,
               question.day < target_date, question.task_id.in_(task_ids))
        .order_by(question.day.desc(), question.id.desc())
    )).all()
    feedback = {}
    timestamps = {}
    for task_id, user_id, answer, comment, answered_at in answers:
        action = (answer or {}).get("action", "")
        if action or comment:
            key = (task_id, user_id)
            if key not in timestamps:
                feedback.setdefault(task_id, {})[user_id] = (
                    "JO" if action == "postpone" else action if action in {"PO", "JO"} else "",
                    comment or "",
                )
                timestamps[key] = answered_at

    web = (await db.execute(
        select(TaskPlanFeedback).where(TaskPlanFeedback.target_date == target_date,
                                       TaskPlanFeedback.task_id.in_(task_ids))
    )).scalars().all()
    for row in web:
        timestamp = timestamps.get((row.task_id, row.user_id))
        if timestamp is not None and timestamp > row.updated_at:
            continue
        by_user = feedback.setdefault(row.task_id, {})
        action, comment = by_user.get(row.user_id, ("", ""))
        by_user[row.user_id] = (
            action if row.continuation is None else row.continuation,
            comment if row.comment is None else row.comment,
        )
    return feedback
