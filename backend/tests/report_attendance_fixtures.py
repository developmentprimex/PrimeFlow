"""Default present population for existing synthetic report repository tests."""
import pytest


@pytest.fixture(autouse=True)
def present_report_population(monkeypatch):
    from app.services import report_attendance
    from app.services.report_attendance import ReportAttendance
    async def present(*_args, **_kwargs):
        return ReportAttendance()
    monkeypatch.setattr(report_attendance, "load_report_attendance", present)
    import sys
    for module_name, module in list(sys.modules.items()):
        if module_name.startswith(("app.services.", "app.api.routers.")) and hasattr(module, "load_report_attendance"):
            monkeypatch.setattr(module, "load_report_attendance", present)
