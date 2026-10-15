from datetime import date
from io import BytesIO
from zipfile import ZipFile

from app.services.one_h_project_coverage import is_project_coverage_department, project_task_periods
from app.services.tomorrow_print_report import _project_covered_initials, _html_table, _excel_table_attachment, _docx_table_attachment, _core_png_table_attachment


def test_only_pcm_and_design_project_departments_qualify():
    assert is_project_coverage_department("PCM")
    assert is_project_coverage_department("GD")
    assert is_project_coverage_department(None, "Graphic Design")
    assert not is_project_coverage_department("DEV", "Development")


def test_all_day_and_am_pm_project_tasks_cover_both_periods():
    for period in (None, "", "AM/PM", "ALL", "ALL DAY"):
        assert project_task_periods(period) == ("AM", "PM")
    assert project_task_periods("AM") == ("AM",)
    assert project_task_periods("PM") == ("PM",)


def test_print_coverage_is_scoped_to_department_date_and_period():
    payload = {
        "users": [{"id": "pcm", "full_name": "Fjolla Gashi"}, {"id": "dev", "full_name": "Elsa Ferati"}],
        "departments": [{"id": "pcm-dep", "code": "PCM"}, {"id": "dev-dep", "code": "DEV"}],
        "items": {"priority": [
            {"date": "2026-10-15", "department_id": "pcm-dep", "projectTaskAssigneesByPeriod": {"AM": ["pcm"]}},
            {"date": "2026-10-15", "department_id": "dev-dep", "projectTaskAssigneesByPeriod": {"AM": ["dev"], "PM": ["dev"]}},
            {"date": "2026-10-16", "department_id": "pcm-dep", "projectTaskAssigneesByPeriod": {"PM": ["pcm"]}},
        ]},
    }
    covered = _project_covered_initials(payload, date(2026, 10, 15))
    assert covered["10:00"] == ["FG"]
    assert covered["11:50"] == ["FG"]
    assert covered["16:00"] == []
    assert covered["BLL"] == []
    rendered = _html_table([("1H\n10:00", [], False)], missing_one_h_by_slot={"10:00": ["FG", "EF"]}, project_covered_by_slot=covered)
    assert 'data-missing-one-h-with-project-users="true"' in rendered
    assert 'color:#15803D' in rendered
    assert 'data-missing-one-h-users="true"' in rendered


def test_pm_project_coverage_also_justifies_missing_bll():
    rendered = _html_table([("BLL", [], False)], missing_blocked_initials=["FG"], project_covered_by_slot={"BLL": ["FG"]})
    assert 'data-missing-blocked-with-project-users="true"' in rendered
    assert 'data-missing-blocked-users="true"' not in rendered


def test_project_coverage_is_green_in_excel_word_and_png():
    rows = [("1H\n10:00", [], False), ("BLL", [], False)]
    missing = {"10:00": ["AT", "EF"], "BLL": ["AT"]}
    covered = {"10:00": ["AT"], "BLL": ["AT"]}
    _, xlsx, _ = _excel_table_attachment(rows, [], date(2026, 10, 15), missing_one_h_by_slot=missing, project_covered_by_slot=covered)
    with ZipFile(BytesIO(xlsx)) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert '15803D' in sheet and 'DC2626' in sheet
    _, docx, _ = _docx_table_attachment(rows, date(2026, 10, 15), missing_one_h_by_slot=missing, project_covered_by_slot=covered)
    with ZipFile(BytesIO(docx)) as archive:
        document = archive.read("word/document.xml").decode()
    assert '15803D' in document and 'DC2626' in document
    from PIL import Image
    _, png, _ = _core_png_table_attachment(rows, date(2026, 10, 15), missing_one_h_by_slot=missing, project_covered_by_slot=covered)
    colors = Image.open(BytesIO(png)).convert("RGB").getcolors(20_000_000)
    assert any(color == (21, 128, 61) for _, color in colors)
