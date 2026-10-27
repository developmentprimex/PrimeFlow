"""Read-only verification of the M3 preview suppression deployment."""
from pathlib import Path
root = Path(__file__).resolve().parents[1]
source = (root / 'tmp/verify-discord-m3.py').read_text(encoding='utf-8')
source = source.replace('DiscordM3-20261027', 'DiscordM3NoPreview-20261027')
exec(compile(source, str(root / 'tmp/verify-discord-m3.py'), 'exec'))
