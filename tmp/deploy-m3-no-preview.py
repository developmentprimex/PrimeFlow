"""Deploy suppression of automatic link previews on M3 messages."""
import json
from pathlib import Path
root = Path(__file__).resolve().parents[1]
previous = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordM3Compact-20261027\manifest.json')
reviewed_manifest = json.loads(previous.read_text(encoding='utf-8'))
source = (root / 'tmp/deploy-discord-m3.py').read_text(encoding='utf-8')
start = source.index('files = [')
end = source.index('\n]', start) + 2
source = source[:start] + "files = ['discord_m3_client.py']" + source[end:]
source = source.replace('DiscordM3-20261027', 'DiscordM3NoPreview-20261027')
source = source.replace("for prerequisite in (", "reviewed.update(" + repr({item['path']: item['sha256'] for item in reviewed_manifest}) + ")\n\nfor prerequisite in (")
source = source.replace('"& \'C:\\\\PrimeFlowOps\\\\DiscordM3NoPreview-20261027\\\\restart-apis.ps1\'\\n"', '""')
exec(compile(source, str(root / 'tmp/deploy-discord-m3.py'), 'exec'))
