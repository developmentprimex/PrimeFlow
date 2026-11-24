from types import SimpleNamespace

from app.api.routers.ga_notes import _ga_note_task_title, _title_for_note_task
from app.api.routers.plan_notes import _plan_note_task_title


def test_ga_note_task_title_keeps_the_complete_note() -> None:
    assert _ga_note_task_title("  First line\n\nsecond   line  ") == "First line\n\nsecond   line"


def test_ga_note_task_title_falls_back_when_note_is_empty() -> None:
    assert _ga_note_task_title(" \n\t ") == "GA/KA note task"


def test_manual_email_note_task_gets_the_standard_title_without_its_body():
    content = "EM GA: 09:50 STD-STAUD\nPërmbledhja.\n1) Kontrollo dokumentet."
    note = SimpleNamespace(knowledge_type=None, content=content)
    assert _title_for_note_task(note, content) == "EM GA: 08:00 STD-STAUD"


def test_ga_note_task_title_does_not_truncate_long_content() -> None:
    source = "a" * 300

    assert _ga_note_task_title(source) == source


def test_plan_note_task_title_keeps_the_complete_note() -> None:
    source = "  Titulli kryesor\n1. Hapi i parë\n2. Hapi i dytë"

    assert _plan_note_task_title(source) == source.strip()
