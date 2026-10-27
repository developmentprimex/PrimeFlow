"""Publish the per-task tomorrow flow using the verified M3 deployment procedure."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
previous = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordM3-20261027\manifest.json')
reviewed_manifest = json.loads(previous.read_text(encoding='utf-8'))
source = (root / 'tmp/deploy-discord-m3.py').read_text(encoding='utf-8')
start = source.index('files = [')
end = source.index('\n]', start) + 2
source = source[:start] + "files = ['app/api/routers/discord_m3.py', 'discord_m3_client.py']" + source[end:]
source = source.replace('DiscordM3-20261027', 'DiscordM3PerTask-20261027')
source = source.replace("for prerequisite in (", "reviewed.update(" + repr({item['path']: item['sha256'] for item in reviewed_manifest}) + ")\n\nfor prerequisite in (")
exec(compile(source, str(root / 'tmp/deploy-discord-m3.py'), 'exec'))
