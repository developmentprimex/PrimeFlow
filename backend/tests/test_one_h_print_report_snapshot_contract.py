from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _route_function(source: str, name: str, next_name: str) -> str:
    return source[source.index(f"async def {name}("):source.index(f"async def {next_name}(")]


def test_today_and_tomorrow_pages_persist_manual_generation():
    for router_name, kind in (
        ("today_print_report.py", "TODAY"),
        ("tomorrow_print_report.py", "TOMORROW"),
    ):
        source = (ROOT / "backend/app/api/routers" / router_name).read_text(encoding="utf-8")
        assert '@router.get("/snapshot")' in source
        assert '@router.post("/generate")' in source
        assert f'report_kind="{kind}"' in source
        assert "save_one_h_print_snapshot" in source


def test_today_email_uses_cutoff_report_and_tomorrow_remains_live():
    today = (ROOT / "backend/app/api/routers/today_print_report.py").read_text(encoding="utf-8")
    tomorrow = (ROOT / "backend/app/api/routers/tomorrow_print_report.py").read_text(encoding="utf-8")
    today_send = _route_function(today, "send", "history")
    tomorrow_send = _route_function(tomorrow, "send", "history")

    assert "_report(db, delivery_date, include_attachment=True)" in today_send
    assert "build_tomorrow_print_report(delivery_date, include_attachment=True, db=db)" in tomorrow_send
    assert "get_one_h_print_snapshot" not in today_send
    assert "get_one_h_print_snapshot" not in tomorrow_send

    today_scheduler = (ROOT / "backend/app/services/today_print_report_scheduler.py").read_text(encoding="utf-8")
    tomorrow_scheduler = (ROOT / "backend/app/services/tomorrow_print_report_scheduler.py").read_text(encoding="utf-8")
    assert "today_report(db, delivery_date, include_attachment=True)" in today_scheduler
    assert "build_tomorrow_print_report" in tomorrow_scheduler
    assert "get_one_h_print_snapshot" not in today_scheduler
    assert "get_one_h_print_snapshot" not in tomorrow_scheduler


def test_symbol_comment_modal_uses_host_viewport_and_marker_change_is_guarded():
    source = (ROOT / "frontend/src/app/(app)/tomorrow-print-report/page.tsx").read_text(encoding="utf-8")
    modal = source[source.index("const openMarkerCommentModal"):source.index("document.querySelectorAll<HTMLElement>")]
    change_handler = source[source.index('select.addEventListener("change"'):source.index("const periodBadge")]

    assert "const hostDocument = window.document" in modal
    assert "hostDocument.body.appendChild(overlay)" in modal
    assert 'max-height:calc(100vh - 40px)' in modal
    assert 'if (select.disabled) return' in change_handler
    assert change_handler.index("select.disabled = true") < change_handler.index("await openMarkerCommentModal")


def test_saved_report_uses_compact_symbol_comment_control_in_the_preview():
    source = (ROOT / "frontend/src/app/(app)/tomorrow-print-report/page.tsx").read_text(encoding="utf-8")

    assert 'commentButton.dataset.taskMarkerCommentControl = "true"' in source
    assert 'commentButton.textContent = "\\u{1F4AC}"' in source
    assert 'if (commentBlock) commentBlock.style.display = "none"' in source
    assert 'commentButton.addEventListener("click"' in source
    assert 'markerControl.append(select, commentButton)' in source
