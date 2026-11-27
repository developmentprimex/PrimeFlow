import asyncio
from datetime import date
from io import BytesIO
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from PIL import Image

from app.services.after_break_report import (
    normalize_after_break_report_sections,
    render_html,
    render_plain_text,
)
from app.services.meeting_point_manual_sync import merge_common_view_manual_sections, section_group_label
from app.services.meetings_report import section_report_attachments


TITLE = "A KA RIORGANIZIM?"
PLAN = "SI BËHET RIORGANIZIMI?"
CAUSE = "SHKAKTARI I MUNGESËS OSE VONESËS"


def test_reorganization_is_a_built_in_final_manual_section_with_all_fields():
    section = normalize_after_break_report_sections([])[-1]
    assert section == {
        "section_key": TITLE,
        "title": TITLE,
        "body": f"BZ M1: JO\nKOMENT:\nNËNNGARKESË: JO\nMBINGARKESË: JO\n{PLAN}:\n{CAUSE}:",
    }
    assert section_group_label("after_break", TITLE, TITLE) == "MANUAL QUESTIONS"


def test_regeneration_migrates_legacy_answer_and_prevents_common_view_duplicate():
    legacy = {"section_key": "manual:custom:3:legacy", "title": f"3. {TITLE}", "body": "Existing M2 answer"}
    with patch("app.services.meeting_point_manual_sync.load_common_view_extra_titles",
               AsyncMock(return_value=[TITLE, f"2. {TITLE}"])):
        regenerated = asyncio.run(merge_common_view_manual_sections(
            None, normalize_after_break_report_sections([]), "after_break", [legacy], [legacy],
        ))

    sections = [section for section in regenerated if TITLE in section["title"]]
    assert len(sections) == 1
    assert sections[0] == regenerated[-1]
    assert "KOMENT: Existing M2 answer" in sections[0]["body"]
    assert "Existing M2 answer" not in normalize_after_break_report_sections([])[-1]["body"]


def test_saved_follow_ups_appear_in_m2_text_html_and_word_and_render_to_png():
    body = f"{PLAN}: Move the afternoon task\n{CAUSE}: Staff delay"
    sections = normalize_after_break_report_sections([{"section_key": TITLE, "title": TITLE, "body": body}])[-1:]
    day = date(2026, 11, 27)

    attachments = section_report_attachments("M2", "M2", day, sections)
    with ZipFile(BytesIO(attachments[0][1])) as document:
        word = document.read("word/document.xml").decode()
    assert attachments[0][0].endswith(".docx")
    with Image.open(BytesIO(attachments[1][1])) as image:
        assert image.format == "PNG"
    for output in (render_html("M2", day, sections), render_plain_text("M2", day, sections), word):
        assert TITLE in output
        assert "Move the afternoon task" in output
        assert "Staff delay" in output
