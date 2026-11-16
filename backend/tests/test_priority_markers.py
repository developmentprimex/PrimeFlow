import pytest
from pydantic import ValidationError

from app.schemas.ga_note import GaNoteCreate, GaNoteUpdate, GaNoteTaskBundleUpdate
from app.schemas.plan_note import PlanNoteCreate, PlanNoteUpdate, PlanNoteTaskBundleUpdate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task_marker import one_h_marker_label
from app.services.primeflow_report import one_h_marker_symbol, ONE_H_MARKER_LEGEND
from app.services.tomorrow_print_report import _task_marker_label, _task_marker_legend_html, _task_marker_legend_text


@pytest.mark.parametrize('model,payload', [
    (GaNoteCreate, {'content': 'Weekly goal'}),
    (GaNoteUpdate, {}),
    (GaNoteTaskBundleUpdate, {}),
    (PlanNoteCreate, {'content': 'Weekly goal'}),
    (PlanNoteUpdate, {}),
    (PlanNoteTaskBundleUpdate, {}),
    (TaskCreate, {'title': 'Weekly goal'}),
    (TaskUpdate, {}),
])
@pytest.mark.parametrize('marker,symbol', [
    ('EXCLAMATION', '!'), ('DOUBLE_EXCLAM', '!!'), ('CLIENT_URGENT', '!!!'),
    ('CLIENT_URGENT,M3', '!!! + M3'), ('M3,CLIENT_URGENT', 'M3 + !!!'),
    ('DOUBLE_EXCLAM,CLIENT_URGENT', '!! + !!!'),
])
def test_priority_markers_survive_validation_and_report_rendering(model, payload, marker, symbol):
    saved = model(**payload, one_h_marker=marker).model_dump()['one_h_marker']
    assert saved == marker
    assert len(saved) <= 32  # Note, Task, history and inbox database columns.
    assert one_h_marker_label(saved) == symbol
    assert one_h_marker_label(saved, True) == f'({symbol})'
    assert one_h_marker_symbol(saved) == symbol
    assert _task_marker_label({'one_h_marker': saved}) == symbol


@pytest.mark.parametrize('model', [GaNoteUpdate, GaNoteTaskBundleUpdate, PlanNoteUpdate, PlanNoteTaskBundleUpdate, TaskUpdate])
@pytest.mark.parametrize('marker', ['QUESTION,KA,M3', 'KA,KA', 'UNKNOWN', 'KA,', ',KA', 'KA, UNKNOWN', ''])
def test_invalid_or_more_than_two_symbols_are_rejected(model, marker):
    with pytest.raises(ValidationError):
        model(one_h_marker=marker)


def test_priority_legends_explain_the_three_levels_in_generated_reports():
    legend = dict(ONE_H_MARKER_LEGEND)
    assert list(legend)[:4] == ['!', '!!', '!!!', '?']
    for rendered in (_task_marker_legend_text(), _task_marker_legend_html()):
        positions = [rendered.index(legend[symbol]) for symbol in ('!', '!!', '!!!', '?')]
        assert positions == sorted(positions)
    assert 'MBINGARKESËN' in legend['!']
    assert 'TË PREMTEN' in legend['!']
    assert 'PA PASOJA TË RËNDËSISHME' in legend['!!']
    assert 'QËLLIM I JAVËS' in legend['!!!']
    for symbol in ('!', '!!', '!!!'):
        assert legend[symbol] in _task_marker_legend_text()
        assert legend[symbol] in _task_marker_legend_html()
