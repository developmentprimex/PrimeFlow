"""Read-only readiness checks for the per-task tomorrow deployment."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = (root / 'tmp/verify-discord-m3.py').read_text(encoding='utf-8')
source = source.replace('DiscordM3-20261027', 'DiscordM3PerTask-20261027')
exec(compile(source, str(root / 'tmp/verify-discord-m3.py'), 'exec'))
