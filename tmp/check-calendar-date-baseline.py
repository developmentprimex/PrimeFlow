import runpy
import subprocess
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))
source = subprocess.check_output(['git', 'show', 'HEAD:backend/app/services/tomorrow_print_report.py'], cwd=root).decode('utf-8')
baseline = types.ModuleType('baseline_tomorrow_print_report')
baseline.__file__ = str(root / 'backend/app/services/tomorrow_print_report.py')
sys.modules[baseline.__name__] = baseline
exec(compile(source, baseline.__file__, 'exec'), baseline.__dict__)
tests = runpy.run_path(str(root / 'backend/tests/test_tomorrow_print_report.py'))
for name in ('test_task_marker_legend_explains_the_report_symbols', 'test_one_h_marker_is_a_separate_badge_next_to_am_pm'):
    fn = tests[name]
    for helper in ('_task_marker_legend_html', '_html_table'):
        fn.__globals__[helper] = getattr(baseline, helper)
    try:
        fn()
    except AssertionError:
        print(name, 'also fails on HEAD (before this fix)')
    else:
        raise AssertionError(f'{name} did not fail on baseline')
