import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.realization_calculator import MANDATORY_MANUAL_QUESTION_KEYS, build_live_questions
from app.services.realization_checklist import apply_checklist_answers
from app.services.realization_weekly_summary import rollup_daily_answers, suggest_weekly_level
from app.services.realization_weekly_metrics import build_weekly_task_metrics
from app.services.realization_manager_review import upsert_manager_review
from app.api.routers.realization import _weekly_answer_target, _attach_weekly_daily_evidence, _manager_review_context
from app.api.routers.realization import save_person_question_answer
from app.models.enums import UserRole
from app.schemas.realization import RealizationManagerReviewUpsert
from app.schemas.realization import RealizationQuestionAnswerCreate


def day(day_number, **answers):
    return {"date": f"2026-09-{day_number:02}", "daily_progress_percent": 100,
            "manual_answers": {key: {"value": value, "comment": f"Dita {day_number}"} for key, value in answers.items()}}


def test_positive_daily_event_survives_later_no_and_weekly_override_preserves_history():
    facts = {"questions": build_live_questions({}), "daily_timeline": [day(14, helped_colleague=True), day(15, helped_colleague=False)]}
    apply_checklist_answers(facts, direct_answers={})
    assert facts["manual_answers"]["helped_colleague"]["value"] is True
    assert "2026-09-14" in facts["manual_answers"]["helped_colleague"]["comment"]
    apply_checklist_answers(facts, direct_answers={"helped_colleague": {"value": False, "comment": "Korrigjim"}})
    question = next(q for q in facts["questions"] if q["key"] == "helped_colleague")
    assert question["final_value"] is False
    assert len(question["daily_history"]) == 2
    # Clearing an override restores the daily rollup.
    apply_checklist_answers(facts, direct_answers={})
    assert facts["manual_answers"]["helped_colleague"]["value"] is True


def test_missing_day_is_not_a_no_and_meeting_compliance_needs_complete_days():
    days = [day(14, helped_colleague=False, respected_meetings=True), day(15)]
    assert rollup_daily_answers(days) == {}
    days[0]["manual_answers"]["respected_meetings"]["value"] = False
    assert rollup_daily_answers(days)["respected_meetings"]["value"] is False
    days[1]["on_leave"] = True
    assert rollup_daily_answers(days)["helped_colleague"]["value"] is False


def test_cleared_weekly_answer_without_daily_evidence_becomes_unanswered():
    facts = {"questions": build_live_questions({})}
    apply_checklist_answers(facts, direct_answers={"helped_colleague": {"value": True, "comment": "Old"}})
    apply_checklist_answers(facts, direct_answers={})
    question = next(q for q in facts["questions"] if q["key"] == "helped_colleague")
    assert question["final_value"] is None
    assert question["source_status"] == "MANUAL_UNANSWERED"


def test_daily_percentage_and_counts_survive_weekly_task_deduplication():
    timeline = [{"date": "2026-09-14", "planned_count": 4, "completed_count": 3,
                 "daily_progress_percent": 68.8, "tasks": [{"task_id": "one", "attribution": "planned_today", "status": "DONE"}]}]
    build_weekly_task_metrics([], timeline)
    assert (timeline[0]["daily_progress_percent"], timeline[0]["planned_count"], timeline[0]["completed_count"]) == (68.8, 4, 3)


def base_facts(**updates):
    facts = {"weekly_planned_count": 5, "weekly_completed_count": 5,
             "daily_timeline": [day(14)],
             "manual_answers": {key: {"value": key == "respected_meetings"} for key in MANDATORY_MANUAL_QUESTION_KEYS}}
    facts.update(updates)
    return facts


@pytest.mark.parametrize("extras,expected", [([], "B"), (["helped_colleague"], "A"), (["helped_colleague", "gave_proposal"], "A+")])
def test_suggestions_reward_distinct_extra_categories(extras, expected):
    facts = base_facts()
    for key in extras:
        facts["manual_answers"][key] = {"value": True}
    assert suggest_weekly_level(facts)["level"] == expected


@pytest.mark.parametrize("key", sorted(MANDATORY_MANUAL_QUESTION_KEYS))
def test_no_letter_until_every_required_question_has_a_saved_boolean(key):
    facts = base_facts()
    del facts["manual_answers"][key]
    decision = suggest_weekly_level(facts)
    assert decision["level"] is None
    assert decision["answers_complete"] is False
    assert key in decision["missing"]
    facts["manual_answers"][key] = {"value": None}
    assert suggest_weekly_level(facts)["level"] is None
    facts["manual_answers"][key] = {"value": False}
    assert suggest_weekly_level(facts)["level"] is not None
    assert suggest_weekly_level(facts)["answers_complete"] is True


def test_full_week_annual_leave_proposes_b_without_manual_answers_or_reports():
    result = suggest_weekly_level(base_facts(availability_status="PV", manual_answers={}, daily_timeline=[], weekly_planned_count=0))
    assert result["level"] == "B"
    assert result["answers_complete"] is True
    assert result["missing"] == []
    assert result["provisional"] is False


def test_partial_annual_leave_still_requires_manual_answers():
    facts = base_facts(manual_answers={})
    facts["daily_timeline"] = [{"date": "2026-10-08", "on_leave": True}, {"date": "2026-10-09", "daily_progress_percent": 100}]
    assert suggest_weekly_level(facts)["level"] is None


@pytest.mark.parametrize("key", ["affected_other_plan", "week_problems", "repeated_after_clarification"])
def test_recorded_problem_caps_complete_plan_at_c(key):
    facts = base_facts(weekly_additional_completed_count=3)
    facts["manual_answers"][key] = {"value": True}
    assert suggest_weekly_level(facts)["level"] == "C"


def test_incomplete_plan_and_missing_evidence_are_distinguished():
    assert suggest_weekly_level(base_facts(weekly_completed_count=3))["level"] == "D"
    assert suggest_weekly_level(base_facts(weekly_completed_count=0))["level"] == "E"
    assert suggest_weekly_level(base_facts(daily_timeline=[{"date": "2026-09-14"}]))["level"] is None
    assert suggest_weekly_level(base_facts(manual_answers={}))["provisional"] is True
    assert suggest_weekly_level(base_facts(availability_status="PV"))["level"] == "B"


def test_free_text_is_preserved_without_automatically_accusing_employee():
    facts = base_facts()
    facts["daily_timeline"][0]["person_comment"] = {"comment": "Nuk ka bërë gabim"}
    assert suggest_weekly_level(facts)["level"] == "B"


def test_absence_requires_explicit_classification():
    facts = base_facts()
    facts["daily_timeline"][0]["attendance"] = [{"type": "MUNGESE"}]
    assert suggest_weekly_level(facts)["level"] == "B"
    assert "absence_classification" in suggest_weekly_level(facts)["missing"]
    facts["observations"] = [{"category": "ABSENCE", "verified": True, "evidence_json": {"date": "2026-09-14", "classification": "APPROVED_PERSONAL"}}]
    assert suggest_weekly_level(facts)["level"] == "M"
    facts["observations"][0]["evidence_json"]["classification"] = "UNEXCUSED"
    assert suggest_weekly_level(facts)["level"] == "C"
    facts["observations"].append({"category": "ABSENCE", "verified": True, "evidence_json": {"date": "2026-09-15", "classification": "UNEXCUSED"}})
    assert suggest_weekly_level(facts)["level"] == "E"


def test_one_confirmed_postponement_does_not_approve_all_postponed_tasks():
    facts = base_facts(weekly_completed_count=3, weekly_postponed_task_count=2)
    facts["manual_answers"]["approved_postponement"] = {"value": True}
    facts["questions"] = [{"key": "approved_postponement", "auto_value": {"approved": 1}}]
    assert suggest_weekly_level(facts)["level"] == "D"
    facts["questions"][0]["auto_value"]["approved"] = 2
    assert suggest_weekly_level(facts)["level"] == "B"


def test_live_weekly_approvals_replace_stale_snapshot_totals():
    facts = base_facts(weekly_completed_count=3, weekly_postponed_task_count=2)
    facts["manual_answers"]["approved_postponement"] = {"value": True}
    facts["questions"] = [{"key": "approved_postponement", "auto_value": {"approved": 0}}]
    facts["weekly_approved_postponed_task_count"] = 2
    assert suggest_weekly_level(facts)["level"] == "B"
    facts["weekly_approved_postponed_task_count"] = 1
    facts["questions"][0]["auto_value"]["approved"] = 10
    assert suggest_weekly_level(facts)["level"] == "D"


def test_daily_answers_cannot_edit_locked_parent_week():
    weekly = SimpleNamespace(id=uuid.uuid4(), status="LOCKED")
    with patch("app.api.routers.realization.ensure_weekly_scope_period", new=AsyncMock(return_value=weekly)):
        with pytest.raises(ValueError, match="Locked"):
            asyncio.run(_weekly_answer_target(SimpleNamespace(), period=SimpleNamespace(period_type="DAILY"), result=None, actor_id=uuid.uuid4()))


def test_manager_letter_rejects_locked_week():
    department, subject_id = uuid.uuid4(), uuid.uuid4()
    weekly = SimpleNamespace(id=uuid.uuid4(), status="LOCKED", period_type="WEEKLY", department_id=department)
    subject = SimpleNamespace(id=subject_id, department_id=department)
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: subject)))
    actor = SimpleNamespace(id=uuid.uuid4(), role=UserRole.MANAGER)
    with patch("app.api.routers.realization._period", new=AsyncMock(return_value=weekly)), patch("app.api.routers.realization.ensure_weekly_scope_period", new=AsyncMock(return_value=weekly)):
        with pytest.raises(Exception) as error:
            asyncio.run(_manager_review_context(db, period_id=weekly.id, subject_user_id=subject_id, actor=actor, editing=True))
    assert error.value.status_code == 409


def test_letter_override_survives_comment_edit_and_can_be_cleared_with_audit_history():
    rows = []
    db = SimpleNamespace(add=rows.append, flush=AsyncMock())
    args = dict(period_id=uuid.uuid4(), user_id=uuid.uuid4(), department_id=uuid.uuid4(), dimension="REALIZATION", marker="POSITIVE", comment="Arsyetim", actor_id=uuid.uuid4())
    with patch("app.services.realization_manager_review.manager_review_rows", new=AsyncMock(side_effect=lambda *a, **kw: list(rows))):
        first = asyncio.run(upsert_manager_review(db, **args, level="C", update_level=True))
        first.id = uuid.uuid4()
        second = asyncio.run(upsert_manager_review(db, **args))
        second.id = uuid.uuid4()
        assert second.evidence_json["review_level"] == "C"
        assert first.voided_at is not None
        assert second.evidence_json["supersedes_observation_id"] == str(first.id)
        third = asyncio.run(upsert_manager_review(db, **args, level=None, update_level=True))
        assert third.evidence_json["review_level"] is None
        assert second.voided_at is not None
    with pytest.raises(ValueError):
        RealizationManagerReviewUpsert(marker="POSITIVE", level="Z")


def test_weekly_comments_are_dated_and_scoped_and_authors_are_included():
    uid, actor_id, department = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    week = SimpleNamespace(department_id=department, start_date=date(2026, 9, 14), end_date=date(2026, 9, 18))
    daily = SimpleNamespace(id=uuid.uuid4(), start_date=date(2026, 9, 15))
    result = SimpleNamespace(id=uuid.uuid4(), user_id=uid)
    comment = SimpleNamespace(user_id=uid, comment="Gabimi u korrigjua", updated_by=actor_id, updated_at=now)
    def response(rows):
        return SimpleNamespace(all=lambda: rows, scalars=lambda: SimpleNamespace(all=lambda: rows))
    db = SimpleNamespace(execute=AsyncMock(side_effect=[response([(result, daily)]), response([(comment, daily)]), response([SimpleNamespace(id=actor_id, full_name="Përgjegjësi")])]))
    timelines = {uid: [{"date": "2026-09-15", "daily_progress_percent": 75, "has_live_metrics": True}]}
    with patch("app.api.routers.realization._latest_question_answers", new=AsyncMock(return_value={})): 
        asyncio.run(_attach_weekly_daily_evidence(db, period=week, daily_by_user=timelines, user_ids=[uid]))
    assert timelines[uid][0]["person_comment"] == {"comment": "Gabimi u korrigjua", "author": "Përgjegjësi", "updated_at": now.isoformat()}
    assert timelines[uid][0]["daily_progress_percent"] == 75
    params = db.execute.call_args_list[1].args[0].compile().params
    assert department in params.values()
    assert week.start_date in params.values() and week.end_date in params.values()
    assert [uid] in params.values()


def test_user_question_route_creates_weekly_result_before_final_calculation():
    uid, department = uuid.uuid4(), uuid.uuid4()
    period = SimpleNamespace(id=uuid.uuid4(), period_type="WEEKLY", department_id=department, status="OPEN")
    subject = SimpleNamespace(id=uid, department_id=department)
    added = []
    db = SimpleNamespace(execute=AsyncMock(side_effect=[SimpleNamespace(scalar_one_or_none=lambda: subject), SimpleNamespace(scalar_one_or_none=lambda: None)]), add=added.append, flush=AsyncMock())
    async def assign_id():
        added[0].id = uuid.uuid4()
    db.flush.side_effect = assign_id
    writer = AsyncMock(return_value="saved")
    with patch("app.api.routers.realization._period", new=AsyncMock(return_value=period)), patch("app.api.routers.realization.save_question_answer", new=writer):
        result = asyncio.run(save_person_question_answer(period_id=period.id, subject_user_id=uid, question_key="helped_colleague", payload=RealizationQuestionAnswerCreate(value=True, comment="Ndihmoi kolegun"), db=db, user=SimpleNamespace(role=UserRole.MANAGER)))
    assert result == "saved"
    assert added[0].period_id == period.id and added[0].user_id == uid
    assert writer.call_args.kwargs["result_id"] == added[0].id


def test_user_question_route_rejects_staff_without_creating_results():
    period = SimpleNamespace(id=uuid.uuid4(), department_id=uuid.uuid4(), status="OPEN")
    db = SimpleNamespace(add=lambda row: pytest.fail("must not create a result"))
    with patch("app.api.routers.realization._period", new=AsyncMock(return_value=period)):
        with pytest.raises(Exception) as error:
            asyncio.run(save_person_question_answer(period_id=period.id, subject_user_id=uuid.uuid4(), question_key="helped_colleague", payload=RealizationQuestionAnswerCreate(value=False), db=db, user=SimpleNamespace(role=UserRole.STAFF)))
    assert error.value.status_code == 403


@pytest.mark.parametrize("value", [False])
@pytest.mark.parametrize("comment", [None, "", "   "])
def test_no_answer_can_be_saved_without_comment(value, comment):
    from app.api.routers.realization import save_question_answer

    period = SimpleNamespace(id=uuid.uuid4(), period_type="WEEKLY", department_id=uuid.uuid4(), status="OPEN")
    result = SimpleNamespace(id=uuid.uuid4())
    added = []
    async def assign_id():
        added[0].id = uuid.uuid4()
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[SimpleNamespace(scalar_one_or_none=lambda: result), SimpleNamespace(scalar_one_or_none=lambda: None)]),
        add=added.append, flush=AsyncMock(side_effect=assign_id), commit=AsyncMock(),
    )
    actor = SimpleNamespace(id=uuid.uuid4(), role=UserRole.MANAGER, full_name="Manager")
    with patch("app.api.routers.realization._period", new=AsyncMock(return_value=period)), patch("app.api.routers.realization._weekly_answer_target", new=AsyncMock(return_value=(period, result))), patch("app.api.routers.realization.mark_analysis_stale"), patch("app.api.routers.realization.add_audit_log"):
        saved = asyncio.run(save_question_answer(period_id=period.id, result_id=result.id, question_key="helped_colleague", payload=RealizationQuestionAnswerCreate(value=value, comment=comment), db=db, user=actor))
    assert added[0].value_json == {"value": value}
    assert saved.comment is None
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("comment", [None, "", "   ", "\n\t"])
def test_yes_answer_requires_nonblank_comment(comment):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Komenti është i detyrueshëm"):
        RealizationQuestionAnswerCreate(value=True, comment=comment)


def test_yes_answer_accepts_comment_and_clear_does_not_require_comment():
    answer = RealizationQuestionAnswerCreate(value=True, comment="Ndihmoi kolegun")
    assert answer.value is True
    assert answer.comment == "Ndihmoi kolegun"
    cleared = RealizationQuestionAnswerCreate(value=True, clear=True)
    assert cleared.clear is True
