import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.api.routers.realization import _answer_payload
from app.api.routers.task_reviews import review_overview
from app.models.enums import UserRole
from app.services.realization_proposal_diamonds import (
    load_proposal_diamonds, proposal_diamond_rows, proposal_diamond_score,
)

MONDAY = date(2026, 10, 12)
ACTOR = SimpleNamespace(id=uuid.uuid4(), full_name="Manager", role=UserRole.MANAGER)
PERSON = SimpleNamespace(id=uuid.uuid4(), full_name="Elsa")
DEPARTMENT = uuid.uuid4()


def record(value=True, comment="Propozoi kontroll automatik", *, day=MONDAY, period_type="DAILY", result_id=None, revision=0, clear=False, subject=PERSON, question_key="gave_proposal"):
    stamp = datetime(2026, 10, 13, 10, tzinfo=timezone.utc) + timedelta(minutes=revision)
    answer = SimpleNamespace(id=uuid.uuid4(), result_id=result_id or uuid.uuid4(), question_key=question_key,
                             value_json={"value": value, "cleared": clear}, comment=comment,
                             answered_at=stamp, updated_at=stamp, answered_by=ACTOR.id,
                             evidence_ids_json=[], supersedes_answer_id=None)
    period = SimpleNamespace(id=uuid.uuid4(), start_date=day, period_type=period_type, department_id=DEPARTMENT)
    return answer, period, subject, ACTOR


def rows(records, start=MONDAY, end=MONDAY + timedelta(days=4)):
    return proposal_diamond_rows(records, date_from=start, date_to=end, app_timezone=timezone.utc)


@pytest.mark.parametrize("value,comment,clear,key,expected", [
    (True, "Propozim", False, "gave_proposal", 1),
    (False, "Propozim", False, "gave_proposal", 0),
    (True, None, False, "gave_proposal", 0),
    (True, "  \n\t", False, "gave_proposal", 0),
    (True, "Propozim", True, "gave_proposal", 0),
    (True, "Propozim", False, "helped_colleague", 0),
])
def test_only_yes_proposal_with_nonblank_comment_awards_one_diamond(value, comment, clear, key, expected):
    answer = record(value, comment, clear=clear, question_key=key)[0]
    assert proposal_diamond_score(answer) == expected
    assert _answer_payload(answer)["diamond_score"] == expected


def test_repeated_saves_and_comment_edits_keep_one_diamond_with_latest_description():
    first = record()
    edited = record(comment="Propozimi i korrigjuar", result_id=first[0].result_id, revision=1)
    awards = rows([edited, first, edited])
    assert len(awards) == 1
    assert awards[0].review.diamond_score == 1
    assert awards[0].review.comment == "Propozimi i korrigjuar"
    assert awards[0].review.id == first[0].result_id
    assert awards[0].task_id is None
    assert awards[0].source == "REALIZATION_PROPOSAL"


@pytest.mark.parametrize("value,clear", [(False, False), (None, True)])
def test_no_or_clear_removes_the_award_even_when_older_yes_exists(value, clear):
    first = record()
    correction = record(value, None, result_id=first[0].result_id, revision=1, clear=clear)
    assert rows([first, correction]) == []


def test_weekly_summary_does_not_award_daily_proposals_again():
    daily = record()
    weekly = record(period_type="WEEKLY")
    assert len(rows([weekly, daily])) == 1
    assert rows([weekly, daily])[0].realization_period_id == daily[1].id


def test_different_daily_proposals_count_individually_but_weekly_yes_is_a_summary():
    records = [record(day=MONDAY), record(day=MONDAY + timedelta(days=1)), record(period_type="WEEKLY")]
    assert len(rows(records)) == 2
    assert len(rows(records, MONDAY + timedelta(days=1), MONDAY + timedelta(days=1))) == 1


def test_weekly_yes_without_daily_proposal_awards_one_diamond():
    awards = rows([record(period_type="WEEKLY")])
    assert len(awards) == 1
    assert awards[0].review.reviewer_user_id == ACTOR.id


def test_weekly_awards_do_not_merge_different_people_or_weeks():
    other = SimpleNamespace(id=uuid.uuid4(), full_name="Rinesa")
    records = [record(), record(period_type="WEEKLY", subject=other),
               record(period_type="WEEKLY", day=MONDAY + timedelta(days=7))]
    assert len(rows(records, MONDAY, MONDAY + timedelta(days=11))) == 3


def test_latest_no_restores_weekly_only_award_and_out_of_range_is_excluded():
    daily = record()
    correction = record(False, None, result_id=daily[0].result_id, revision=1)
    weekly = record(period_type="WEEKLY")
    assert rows([daily, correction, weekly])[0].realization_period_id == weekly[1].id
    assert rows([weekly], MONDAY + timedelta(days=1), MONDAY + timedelta(days=4)) == []


def test_query_selects_latest_answer_before_award_filter_and_scopes_user_department():
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    assert asyncio.run(load_proposal_diamonds(db, date_from=MONDAY + timedelta(days=1), date_to=MONDAY + timedelta(days=1),
                                            department_id=DEPARTMENT, reviewee_user_id=PERSON.id, app_timezone=timezone.utc)) == []
    statement = db.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "DISTINCT ON (realization_question_answers.result_id)" in sql
    assert "realization_question_answers.answered_at DESC" in sql
    assert "realization_question_answers.id DESC" in sql
    assert DEPARTMENT in compiled.params.values() and PERSON.id in compiled.params.values()
    assert MONDAY in compiled.params.values()
    assert "value_json" not in sql.split("WHERE")[1]


@pytest.mark.parametrize("review_status,expected", [("all", 1), ("reviewed", 1), ("unreviewed", 0)])
def test_overview_includes_proposal_without_completed_tasks_and_preserves_task_counters(review_status, expected):
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []), all=lambda: [])
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    awards = rows([record()])
    with patch("app.api.routers.task_reviews.load_proposal_diamonds", new=AsyncMock(return_value=awards)) as loader:
        overview = asyncio.run(review_overview(date_from=MONDAY, date_to=MONDAY + timedelta(days=4),
                               department_id=None, reviewee_user_id=None, review_status=review_status,
                               db=db, current_user=ACTOR))
    assert overview.diamonds_total == expected
    assert overview.proposal_count == expected
    assert overview.completed_count == overview.reviewed_count == overview.unreviewed_count == 0
    if expected:
        assert overview.users[0].diamonds_total == 1
        assert overview.users[0].proposal_count == 1
        loader.assert_awaited_once()
    else:
        loader.assert_not_awaited()


def test_proposal_diamond_adds_to_task_diamonds_without_inflating_completed_work():
    stamp = datetime(2026, 10, 13, 10, tzinfo=timezone.utc)
    task = SimpleNamespace(id=uuid.uuid4(), title="Detyra e përfunduar", completed_at=stamp,
                           assigned_to=None, project_id=None, due_date=None, department_id=DEPARTMENT)
    review = SimpleNamespace(id=uuid.uuid4(), task_id=task.id, reviewee_user_id=PERSON.id,
                             reviewee_name_snapshot=PERSON.full_name, reviewer_user_id=ACTOR.id,
                             reviewer_name_snapshot=ACTOR.full_name, diamond_score=1, comment="Punë e mirë",
                             is_sample=False, task_title_snapshot=task.title, project_title_snapshot=None,
                             created_at=stamp, updated_at=stamp)
    scalar_result = lambda items: SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: items))
    db = SimpleNamespace(execute=AsyncMock(side_effect=[scalar_result([task]),
                         SimpleNamespace(all=lambda: [(task.id, PERSON)]), scalar_result([review])]))
    with patch("app.api.routers.task_reviews.load_proposal_diamonds", new=AsyncMock(return_value=rows([record()]))):
        overview = asyncio.run(review_overview(date_from=MONDAY, date_to=MONDAY + timedelta(days=4),
                               department_id=DEPARTMENT, reviewee_user_id=PERSON.id, review_status="all",
                               db=db, current_user=ACTOR))
    assert overview.diamonds_total == 2
    assert overview.completed_count == overview.reviewed_count == 1
    assert overview.unreviewed_count == 0
    assert overview.proposal_count == 1
    assert len(overview.rows) == 2
    assert overview.users[0].diamonds_total == 2
