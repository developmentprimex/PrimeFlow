import asyncio
import io
import uuid
import zipfile
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.primeflow_report import (
    ReportDocument, SLOTS, build_report_document, render_docx, render_html, render_plain_text, render_png,
)
from app.services.primeflow_report_delivery import generate_fresh, strike_interval_start, strike_interval_end
from app.services.task_strike_events import count_struck_points_for_interval, point_key


DAY = date(2026, 10, 23)


def fresh_document(slot="11:00"):
    start, end = strike_interval_start(DAY, slot), strike_interval_end(DAY, slot)
    task_id, empty_id = uuid.uuid4(), uuid.uuid4()
    title = "Hourly task\n[[done]]1. Earlier title[[/done]]\n[[done]]2. Current title[[/done]]"
    description = "[[done]]1. At end[[/done]]\n2. Reopened\n[[done]]3. Later interval[[/done]]"

    def event(text, field, at, action="STRUCK"):
        return SimpleNamespace(id=uuid.uuid4(), field_name=field, point_text=text,
            point_key=point_key(text, field_name=field), occurred_at=at, action=action)

    events = [
        event("1. Earlier title", "TITLE", start),
        event("2. Current title", "TITLE", start + timedelta(minutes=1)),
        event("1. At end", "DESCRIPTION", end),
        event("2. Reopened", "DESCRIPTION", start + timedelta(minutes=2)),
        event("2. Reopened", "DESCRIPTION", start + timedelta(minutes=3), "UNSTRUCK"),
        event("3. Later interval", "DESCRIPTION", end + timedelta(minutes=1)),
    ]
    source_slot = "14:20" if slot == "14:10" else slot
    shared = {"task_id": str(task_id), "date": DAY.isoformat(), "slot": source_slot,
              "title": "Stale Common View title", "description": "Stale description", "status": "TODO"}
    data = {"items": {"oneH": [
        {**shared, "id": "display-alice", "person": "Alice Person"},
        {**shared, "id": "display-bob", "person": "Bob Person"},
        {**shared, "task_id": str(empty_id), "id": "display-empty", "person": "Alice Person", "title": "Open task"},
    ]}}
    rows = [(task_id, "Old task title", description, title, None, strike)
            for strike in events if strike.occurred_at <= end]
    rows.append((empty_id, "Open task", "1. Open", None, None, None))

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def execute(self, _query):
            return SimpleNamespace(all=lambda: rows)

    with patch("app.services.primeflow_report_delivery.SessionLocal", return_value=Session()), \
         patch("app.services.primeflow_report_delivery.load_1h_reminder_questions", new=AsyncMock(return_value=[])), \
         patch("app.services.primeflow_report_delivery.load_undiscussed_notes", new=AsyncMock(return_value=[])):
        document = asyncio.run(generate_fresh(DAY, slot, {"to": ["preview@example.com"]}, data=data))
    expected = sum(count_struck_points_for_interval(text, events,
        interval_start=start, interval_end=end, field_name=field)
        for text, field in ((title, "TITLE"), (description, "DESCRIPTION")))
    return document, task_id, expected


@pytest.mark.parametrize("slot", SLOTS)
def test_every_hour_counts_its_own_interval_and_deduplicates_shared_tasks(slot):
    document, shared_id, expected = fresh_document(slot)
    cards = [task for section in document.sections for employee in section.employees for task in employee.tasks]
    assert expected == 2
    # The morning baseline can repeat a shared task for both owners; other
    # reports already merge those cards before rendering.
    shared_cards = 2 if slot == "10:00" else 1
    assert sorted(task.strike_count for task in cards) == [0] + [2] * shared_cards
    assert sum(task.task_id == str(shared_id) for task in cards) == shared_cards
    assert document.strike_total == expected
    assert document.strike_interval == f"{strike_interval_start(DAY, slot):%H:%M}–{strike_interval_end(DAY, slot):%H:%M}"
    assert ReportDocument.model_validate(document.model_dump(mode="json")).strike_total == expected


def test_counts_are_visible_in_preview_email_text_word_and_png():
    document, _, _ = fresh_document()
    output = render_html(document)
    assert "Total strikes: 2 · 10:00–11:00" in output
    assert output.count('data-report-strike-total="true"') == 1
    assert output.count('data-task-strike-count="true"') == 2
    assert output.count("Strikes: 2 · 10:00–11:00") == 1
    assert "Strikes: 0 · 10:00–11:00" in output
    for rendered in (render_plain_text(document), zipfile.ZipFile(io.BytesIO(render_docx(document))).read("word/document.xml").decode()):
        assert "Total strikes: 2 · 10:00–11:00" in rendered
        assert "Strikes: 2 · 10:00–11:00" in rendered
        assert "Strikes: 0 · 10:00–11:00" in rendered
    from PIL import ImageDraw
    original_text = ImageDraw.ImageDraw.text
    labels = []
    colours = {}

    def draw_text(draw, xy, text, *args, **kwargs):
        labels.append(text)
        colours[text] = kwargs.get("fill")
        return original_text(draw, xy, text, *args, **kwargs)

    with patch.object(ImageDraw.ImageDraw, "text", new=draw_text):
        assert render_png(document).startswith(b"\x89PNG")
    assert "Total strikes: 2 · 10:00–11:00" in labels
    assert labels.count("Strikes: 2 · 10:00–11:00") == 1
    assert colours["1. At end"] == "#2563eb"
    assert colours["2. Reopened"] == "#64748b"


def test_bll_table_also_displays_its_strike_count():
    document, _, _ = fresh_document("14:10")
    section = document.sections[-1]
    section.employees = document.sections[0].employees
    output = render_html(document).split('data-bll-task-table="true"', 1)[1]
    assert 'data-task-strike-count="true"' in output
    assert "Strikes: 2 · 11:50–14:20" in output


def test_old_saved_reports_keep_unknown_counts_hidden():
    document, _, _ = fresh_document()
    saved = document.model_dump(mode="json")
    saved.pop("strike_interval")
    for section in saved["sections"]:
        for employee in section["employees"]:
            for task in employee["tasks"]:
                task.pop("task_id")
                task.pop("strike_count")
    restored = ReportDocument.model_validate(saved)
    assert restored.strike_total is None
    assert "data-report-strike-total" not in render_html(restored)
    assert "data-task-strike-count" not in render_html(restored)


def test_empty_new_report_displays_zero_total():
    document = build_report_document({"items": {}}, DAY, "11:00",
        completion_window_start=strike_interval_start(DAY, "11:00"),
        completion_window_end=strike_interval_end(DAY, "11:00"))
    assert document.strike_total == 0
    assert "Total strikes: 0 · 10:00–11:00" in render_html(document)


def test_preview_provides_filterable_cards_without_embedded_controls():
    from app.api.routers import primeflow_1h_reports as router
    document, _, _ = fresh_document()
    email_html = render_html(document)
    with patch.object(router, "_recipient_map", new=AsyncMock(return_value=document.recipients)), \
         patch.object(router, "load_common_view", new=AsyncMock(return_value={})), \
         patch.object(router, "generate_fresh", new=AsyncMock(return_value=document)), \
         patch.object(router, "render_ga_recipient_email_html", new=AsyncMock(return_value=email_html)):
        result = asyncio.run(router.preview(router.PreviewRequest(report_date=DAY, report_slot="11:00"), None, None))
        export = asyncio.run(router.preview(router.PreviewRequest(report_date=DAY, report_slot="11:00", format="html"), None, None))
    assert 'id="one-h-strikes-filter"' not in result["html"]
    assert 'id="one-h-strikes-filter"' not in export.body.decode()
    assert 'id="one-h-strikes-filter"' not in render_html(document)
    assert result["task_count"] == document.task_count
    assert 'data-strike-count="2"' in result["html"]
    assert 'data-strike-count="0"' in result["html"]
    assert 'font:700 14px/1.5 Arial,sans-serif' in result["html"]
