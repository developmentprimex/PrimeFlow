from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_daily_report_api_returns_the_saved_task_marker():
    source = (ROOT / "backend/app/api/routers/reports.py").read_text(encoding="utf-8")
    assert "one_h_marker=active_one_h_marker(t, marker_report_date)" in source


def test_every_department_my_view_renders_the_same_task_marker():
    for department in (
        "development",
        "graphic-design",
        "project-content-manager",
        "finance",
    ):
        source = (
            ROOT
            / f"frontend/src/app/(app)/departments/{department}/department-kanban.tsx"
        ).read_text(encoding="utf-8")
        assert "TaskOneHMarkerEditor" in source, department
        assert "task.one_h_marker" in source, department


def test_department_task_marker_dropdowns_align_to_the_end_of_title_cells():
    for department in (
        "development",
        "graphic-design",
        "project-content-manager",
        "finance",
    ):
        source = (
            ROOT
            / f"frontend/src/app/(app)/departments/{department}/department-kanban.tsx"
        ).read_text(encoding="utf-8")
        assert 'className="order-last ml-auto shrink-0"' in source, department


def test_symbol_filters_include_all_marked_tasks_in_1h_and_px_notes():
    one_h = (ROOT / "frontend/src/app/(app)/tomorrow-print-report/page.tsx").read_text(encoding="utf-8")
    px_notes = (ROOT / "frontend/src/components/px-notes-workspace.tsx").read_text(encoding="utf-8")
    for source in (one_h, px_notes):
        assert 'value="with"' in source
        assert "All with symbols" in source
        assert '"with" ? Boolean(marker)' in source or 'oneHMarkerFilter === "with"' in source


def test_m2_m3_symbols_are_available_in_shared_editors_and_legends():
    paths = (
        "frontend/src/components/task-one-h-marker-editor.tsx",
        "frontend/src/app/(app)/common/page.tsx",
        "frontend/src/components/px-notes-workspace.tsx",
        "frontend/src/app/(app)/tomorrow-print-report/page.tsx",
        "backend/app/services/primeflow_report.py",
        "backend/app/services/tomorrow_print_report.py",
    )
    for relative_path in paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "M2" in source, relative_path
        assert "M3" in source, relative_path
        assert "M2/3" in source, relative_path
    legend_paths = (
        "frontend/src/components/task-one-h-marker-legend.tsx",
        "frontend/src/app/(app)/common/page.tsx",
        "frontend/src/components/px-notes-workspace.tsx",
        "backend/app/services/primeflow_report.py",
        "backend/app/services/tomorrow_print_report.py",
    )
    for relative_path in legend_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "DOREZIM EDHE NE M2 EDHE M3" in source, relative_path


def test_monitor_close_and_symbol_comments_are_available_everywhere():
    paths = (
        "frontend/src/components/task-one-h-marker-editor.tsx",
        "frontend/src/app/(app)/common/page.tsx",
        "frontend/src/components/px-notes-workspace.tsx",
        "frontend/src/app/(app)/tomorrow-print-report/page.tsx",
        "backend/app/services/tomorrow_print_report.py",
    )
    for relative_path in paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "MONITOR" in source or "👁" in source, relative_path
        assert "CLOSE" in source or "MBYLL DETYREN" in source, relative_path
        assert "comment" in source.lower(), relative_path
    legend = (ROOT / "frontend/src/components/task-one-h-marker-legend.tsx").read_text(encoding="utf-8")
    assert "👁" in legend
    assert "MBYLL DETYREN" in legend


def test_client_urgent_symbol_is_available_in_editors_legends_and_reports():
    paths = (
        "frontend/src/components/task-one-h-marker-editor.tsx",
        "frontend/src/components/task-one-h-marker-legend.tsx",
        "frontend/src/app/(app)/common/page.tsx",
        "frontend/src/components/px-notes-workspace.tsx",
        "frontend/src/app/(app)/tomorrow-print-report/page.tsx",
        "backend/app/services/primeflow_report.py",
        "backend/app/services/tomorrow_print_report.py",
    )
    for relative_path in paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "CLIENT_URGENT" in source or "KLIENT/URGJENT" in source, relative_path
        assert "!!!" in source, relative_path


def test_f_bz1n1_and_ga_symbols_are_available_everywhere():
    paths = (
        "frontend/src/components/task-one-h-marker-editor.tsx",
        "frontend/src/components/task-one-h-marker-legend.tsx",
        "frontend/src/app/(app)/common/page.tsx",
        "frontend/src/components/px-notes-workspace.tsx",
        "frontend/src/app/(app)/tomorrow-print-report/page.tsx",
        "backend/app/services/primeflow_report.py",
        "backend/app/services/tomorrow_print_report.py",
    )
    for relative_path in paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "BZ1N1" in source, relative_path
        assert "DET FIZIKISHT" in source or 'label: "F"' in source, relative_path
        assert "⚑" not in source, relative_path
        assert "GA" in source, relative_path


def test_marker_dropdowns_and_legends_use_the_requested_order():
    ordered_tokens = ("QUESTION", "EXCLAMATION", "M2", "M3", "M2_M3", "GENT", "KA", "FLAG", "F", "BZ1N1")
    dropdown_paths = (
        "frontend/src/components/task-one-h-marker-editor.tsx",
        "frontend/src/app/(app)/common/page.tsx",
        "frontend/src/components/px-notes-workspace.tsx",
        "frontend/src/app/(app)/tomorrow-print-report/page.tsx",
    )
    for relative_path in dropdown_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        positions = [source.index(f'value: "{token}"') for token in ordered_tokens]
        assert positions == sorted(positions), relative_path

    legend = (ROOT / "frontend/src/components/task-one-h-marker-legend.tsx").read_text(encoding="utf-8")
    legend_tokens = ('["?"', '["!"', '["M2"', '["M3"', '["M2/3"', '["GENT"', '["KA"', '["GA"', '["F"', '["BZ1N1"')
    positions = [legend.index(token) for token in legend_tokens]
    assert positions == sorted(positions)


def test_department_my_view_daily_reports_show_the_symbol_legend():
    for department in ("development", "graphic-design", "project-content-manager"):
        source = (
            ROOT
            / f"frontend/src/app/(app)/departments/{department}/department-kanban.tsx"
        ).read_text(encoding="utf-8")
        assert "TaskOneHMarkerLegend" in source, department


def test_report_generation_buttons_show_progress():
    report_pages = (
        "frontend/src/app/(app)/tomorrow-print-report/page.tsx",
        "frontend/src/app/(app)/morning-report/page.tsx",
        "frontend/src/app/(app)/after-break-report/page.tsx",
        "frontend/src/app/(app)/meetings-report/page.tsx",
        "frontend/src/app/(app)/end-week-bz-report/page.tsx",
        "frontend/src/app/(app)/reports/weekly-planning-audit/page.tsx",
    )
    for relative_path in report_pages:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "Generating..." in source, relative_path
        assert "animate-spin" in source, relative_path


def test_primary_task_lists_and_details_render_the_same_task_marker():
    paths = (
        "frontend/src/app/(app)/open-tasks/page.tsx",
        "frontend/src/app/(app)/monthly-planner/page.tsx",
        "frontend/src/app/(app)/weekly-planner/page.tsx",
        "frontend/src/app/(app)/waiting-confirmation-ga/page.tsx",
        "frontend/src/app/(app)/tasks/[id]/page.tsx",
        "frontend/src/app/(app)/projects/[id]/page.tsx",
        "frontend/src/app/(app)/admin-tasks/page.tsx",
        "frontend/src/components/command-palette.tsx",
    )
    for relative_path in paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "TaskOneHMarker" in source, relative_path
        assert "one_h_marker" in source, relative_path


def test_task_search_returns_the_saved_marker():
    schema = (ROOT / "backend/app/schemas/search.py").read_text(encoding="utf-8")
    router = (ROOT / "backend/app/api/routers/search.py").read_text(encoding="utf-8")
    assert "one_h_marker: str | None = None" in schema
    assert "one_h_marker=active_one_h_marker(t)" in router


def test_m1_m2_m3_task_tables_render_the_saved_marker():
    source = (ROOT / "backend/app/services/meetings_report.py").read_text(encoding="utf-8")
    assert "one_h_marker_symbol(active_one_h_marker(task))" in source


def test_common_view_personal_owner_priority_is_genti_then_ka_then_ga():
    source = (ROOT / "frontend/src/app/(app)/common/page.tsx").read_text(encoding="utf-8")
    function = source[source.index("const getPersonalTaskGroup"):source.index("const getPersonalRowGroup")]
    assert function.index('["GENT", "GENTI", "GT"]') < function.index('participants.includes("KA")')
    assert function.index('participants.includes("KA")') < function.index('participants.includes("GA")')


def test_symbol_views_refresh_when_the_user_returns_to_them():
    paths = (
        "frontend/src/app/(app)/common/page.tsx",
        "frontend/src/components/px-notes-workspace.tsx",
        "frontend/src/app/(app)/departments/development/department-kanban.tsx",
        "frontend/src/app/(app)/departments/graphic-design/department-kanban.tsx",
        "frontend/src/app/(app)/departments/project-content-manager/department-kanban.tsx",
        "frontend/src/app/(app)/departments/finance/department-kanban.tsx",
    )
    for relative_path in paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "useVisibleRefresh" in source, relative_path

    saved_report = (ROOT / "frontend/src/app/(app)/tomorrow-print-report/page.tsx").read_text(encoding="utf-8")
    assert "useVisibleRefresh" not in saved_report
    assert "`${API}/snapshot`" in saved_report
    assert "`${API}/generate`" in saved_report


def test_weekly_planner_uses_saved_daily_symbols_in_live_snapshot_and_print_views():
    live = (ROOT / "frontend/src/app/(app)/weekly-planner/page.tsx").read_text(encoding="utf-8")
    snapshots = (ROOT / "frontend/src/components/weekly-planner-snapshots-view.tsx").read_text(encoding="utf-8")
    for source in (live, snapshots):
        assert source.count("<TaskOneHMarker") >= 3
        assert "buildPrintTaskMarker" in source
        assert "one_h_marker_by_ga" in source

    planner = (ROOT / "backend/app/api/routers/planners.py").read_text(encoding="utf-8")
    migration = (ROOT / "backend/alembic/versions/0123_persistent_task_symbols.py").read_text(encoding="utf-8")
    assert "TaskOneHMarkerHistory.marker_date" in planner
    assert "historical_marker_for_day" in planner
    assert '("ga_note", task.ga_note_origin_id)' in planner
    assert '("plan_note", task.plan_note_origin_id)' in planner
    assert '("fast_group", task.fast_task_group_id)' in planner
    assert "ON CONFLICT (task_id, marker_date) DO UPDATE" in migration
    assert "trg_sync_task_one_h_marker_history" in migration
    assert "one_h_marker IS NULL" in migration
