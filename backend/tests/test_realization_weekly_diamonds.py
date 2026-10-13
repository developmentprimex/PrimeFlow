import uuid
from datetime import datetime, timezone

from app.schemas.task_review import TaskReviewOut, TaskReviewOverviewRow
from app.services.realization_weekly_diamonds import empty_weekly_diamonds, group_weekly_diamonds


def award(user_id, *, proposal=False, review_id=None, task_id=None):
    stamp = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    task_id = None if proposal else task_id or uuid.uuid4()
    source = "REALIZATION_PROPOSAL" if proposal else "TASK"
    review = TaskReviewOut(id=review_id or uuid.uuid4(), task_id=task_id,
                          reviewee_user_id=user_id, reviewee_name="Elsa", reviewer_user_id=uuid.uuid4(),
                          reviewer_name="Manager", diamond_score=1, comment="Kursen kohë",
                          task_title="Propozim" if proposal else "Detyra", project_title=None,
                          created_at=stamp, updated_at=stamp, source=source)
    return TaskReviewOverviewRow(task_id=task_id, task_title=review.task_title, source=source,
                                 reviewee_user_id=user_id, reviewee_name="Elsa", completed_at=stamp, review=review)


def test_weekly_diamonds_combine_task_and_proposal_awards_per_person():
    first, second = uuid.uuid4(), uuid.uuid4()
    grouped = group_weekly_diamonds([award(first), award(first, proposal=True), award(second, proposal=True)])
    assert grouped[first]["weekly_diamond_count"] == 2
    assert grouped[first]["weekly_task_diamond_count"] == 1
    assert grouped[first]["weekly_proposal_diamond_count"] == 1
    assert grouped[second]["weekly_diamond_count"] == 1
    assert sum(value["weekly_diamond_count"] for value in grouped.values()) == 3


def test_same_award_is_not_counted_twice_but_separate_reviews_of_shared_task_are():
    first, second = uuid.uuid4(), uuid.uuid4()
    task_id = uuid.uuid4()
    first_award = award(first, task_id=task_id)
    second_award = award(second, task_id=task_id)
    grouped = group_weekly_diamonds([first_award, first_award, second_award])
    assert grouped[first]["weekly_diamond_count"] == grouped[second]["weekly_diamond_count"] == 1
    assert len(grouped[first]["weekly_diamonds"]) == 1


def test_details_preserve_source_comment_person_and_serializable_dates():
    person_id = uuid.uuid4()
    proposal = award(person_id, proposal=True)
    details = group_weekly_diamonds([proposal])[person_id]["weekly_diamonds"][0]
    assert details["source"] == "REALIZATION_PROPOSAL"
    assert details["task_id"] is None
    assert details["reviewee_user_id"] == str(person_id)
    assert details["review"]["comment"] == "Kursen kohë"
    assert details["review"]["reviewer_name"] == "Manager"
    assert isinstance(details["completed_at"], str)


def test_unreviewed_tasks_never_award_weekly_diamonds():
    row = award(uuid.uuid4())
    row.review = None
    assert group_weekly_diamonds([row]) == {}


def test_no_awards_returns_zero_with_independent_detail_lists():
    assert group_weekly_diamonds([]) == {}
    first, second = empty_weekly_diamonds(), empty_weekly_diamonds()
    first["weekly_diamonds"].append("test")
    assert second == {"weekly_diamond_count": 0, "weekly_task_diamond_count": 0,
                      "weekly_proposal_diamond_count": 0, "weekly_diamonds": []}
