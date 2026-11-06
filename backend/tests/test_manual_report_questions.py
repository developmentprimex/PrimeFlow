import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.meeting_point_manual_sync import (
    merge_common_view_manual_sections,
    reconcile_custom_manual_questions,
    removes_custom_manual_section,
)
from app.services.after_break_report import normalize_after_break_report_sections
from app.services.meetings_report import normalize_meetings_report_sections
from app.services.morning_report import normalize_morning_report_sections


@pytest.mark.parametrize("kind", ["morning", "after_break", "meetings"])
def test_custom_manual_question_survives_regeneration(kind):
    saved = {
        "section_key": "manual:custom:123",
        "title": "Pyetje e shtuar manualisht",
        "body": "PËRGJIGJA e ruajtur",
    }
    generated = [{"title": "Generated section", "body": "Fresh content"}]
    with patch(
        "app.services.meeting_point_manual_sync.load_common_view_extra_titles",
        new_callable=AsyncMock,
        return_value=[],
    ):
        merged = asyncio.run(merge_common_view_manual_sections(None, generated, kind, [saved]))

    assert merged == [saved, *generated]
    normalize = {
        "morning": normalize_morning_report_sections,
        "after_break": normalize_after_break_report_sections,
        "meetings": normalize_meetings_report_sections,
    }[kind]
    assert saved in normalize(merged)


def test_only_removing_a_custom_question_needs_admin():
    existing = [
        {"section_key": "manual:custom:123", "title": "Pyetje manuale"},
        {"section_key": "manual:COMMON", "title": "Pyetje nga Common View"},
    ]
    assert not removes_custom_manual_section(existing, existing)
    assert removes_custom_manual_section(existing, existing[1:])
    assert not removes_custom_manual_section(existing, existing[:1])


@pytest.mark.parametrize("kind", ["morning", "after_break", "meetings"])
def test_persisted_question_appears_on_new_day_without_yesterdays_answer(kind):
    question = {"section_key": "manual:custom:1:123", "title": "Pika e djeshme"}
    with patch(
        "app.services.meeting_point_manual_sync.load_common_view_extra_titles",
        new_callable=AsyncMock,
        return_value=[],
    ):
        sections = asyncio.run(merge_common_view_manual_sections(
            None,
            [{"title": "Generated section", "body": "Fresh content"}],
            kind,
            None,
            [question],
        ))
    assert sections[0] == {**question, "body": "(Ploteso manualisht)"}


@pytest.mark.parametrize("kind", ["morning", "after_break", "meetings"])
def test_saved_answer_wins_over_persisted_question_template(kind):
    question = {"section_key": "manual:custom:1:123", "title": "Pika e djeshme"}
    saved = {**question, "body": "PËRGJIGJA e sotme"}
    with patch(
        "app.services.meeting_point_manual_sync.load_common_view_extra_titles",
        new_callable=AsyncMock,
        return_value=[],
    ):
        sections = asyncio.run(merge_common_view_manual_sections(
            None, [], kind, [saved], [question]
        ))
    assert sections == [saved]


def test_editing_an_older_draft_does_not_erase_other_persisted_questions():
    older = {"section_key": "manual:custom:1:old", "title": "Old"}
    newer = {"section_key": "manual:custom:2:new", "title": "New"}
    changed = {**older, "title": "Updated"}
    assert reconcile_custom_manual_questions([older, newer], [older], [changed]) == [changed, newer]


def test_deleting_a_question_removes_only_that_persistent_question():
    first = {"section_key": "manual:custom:1:first", "title": "First"}
    second = {"section_key": "manual:custom:2:second", "title": "Second"}
    assert reconcile_custom_manual_questions([first, second], [first, second], [second]) == [second]


@pytest.mark.parametrize("kind", ["morning", "after_break", "meetings"])
def test_numbered_manual_question_keeps_requested_position(kind):
    normalize = {
        "morning": normalize_morning_report_sections,
        "after_break": normalize_after_break_report_sections,
        "meetings": normalize_meetings_report_sections,
    }[kind]
    numbered = {
        "section_key": "manual:custom:2:123",
        "title": "Pika e re",
        "body": "(Ploteso manualisht)",
    }
    sections = normalize([numbered])
    assert sections[1] == numbered
    assert normalize(sections)[1] == numbered

    with patch(
        "app.services.meeting_point_manual_sync.load_common_view_extra_titles",
        new_callable=AsyncMock,
        return_value=[],
    ):
        regenerated = asyncio.run(merge_common_view_manual_sections(None, normalize([]), kind, [numbered]))
    assert regenerated[1] == numbered
