"""Read-only readiness verification for all-day M2 continuation."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
source = (root / 'tmp/verify-discord-m3.py').read_text(encoding='utf-8')
source = source.replace('DiscordM3-20261027', 'M2AllDay-20261027')
exec(compile(source, str(root / 'tmp/verify-discord-m3.py'), 'exec'))
