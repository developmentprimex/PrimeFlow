import json
import subprocess
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow')
files = ['backend/app/api/routers/__init__.py', 'backend/app/models/__init__.py',
         'backend/discord_bot.py', 'backend/app/api/routers/m2_reporting_points.py',
         'backend/app/services/m2_reporting_points.py']
for file in files:
    deployed = (remote / file).read_text(encoding='utf-8-sig')
    base = subprocess.check_output(['git', 'show', 'HEAD:' + file], cwd=root).decode('utf-8-sig').replace('\r\n', '\n')
    print(json.dumps({'file': file, 'matches_head': deployed == base, 'matches_worktree': deployed == (root / file).read_text(encoding='utf-8-sig')}))
env = dotenv_values(remote / 'backend/.env')
print(json.dumps({'remote_discord_enabled': env.get('DISCORD_ASSISTANT_ENABLED'),
                  'remote_token_present': bool(env.get('DISCORD_BOT_TOKEN')), 'remote_guild': env.get('DISCORD_GUILD_ID'),
                  'remote_api_base': env.get('PRIMEFLOW_API_BASE_URL')}))
