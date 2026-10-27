"""Publish the M2 all-day continuation selector through the standard API restart."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / 'tmp/deploy-discord-m3.py').read_text(encoding='utf-8')
start = source.index('files = [')
end = source.index('\n]', start) + 2
source = source[:start] + "files = ['app/services/m2_reporting_points.py']" + source[end:]
source = source.replace('DiscordM3-20261027', 'M2AllDay-20261027')
exec(compile(source, str(root / 'tmp/deploy-discord-m3.py'), 'exec'))
