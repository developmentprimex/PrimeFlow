import ast
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

root = Path(__file__).resolve().parents[1]
sample = '2026-10-21T22:00:00+00:00'
for filename, names in (
    ('tomorrow_print_report.py', ['_task_due_day', '_task_start_day']),
    ('primeflow_report.py', ['_task_date']),
):
    tree = ast.parse((root / 'backend/app/services' / filename).read_text(encoding='utf-8'))
    selected = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    scope = {'date': date, 'datetime': datetime, 'Any': Any}
    exec(compile(selected, filename, 'exec'), scope)
    for name in names:
        actual = scope[name]({'start_date': sample, 'due_date': sample})
        expected = datetime.fromisoformat(sample).astimezone(ZoneInfo('Europe/Budapest')).date()
        print(filename, name, 'actual=', actual, 'expected=', expected)
        assert actual == date(2026, 10, 21) and expected == date(2026, 10, 22)
