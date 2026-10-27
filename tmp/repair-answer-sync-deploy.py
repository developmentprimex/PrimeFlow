"""Restore the tested sync entry points without unpublished concurrent M3 imports."""
import subprocess
from pathlib import Path
root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow')
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\DiscordAnswerSync-20261027')
for file in ('backend/app/api/routers/__init__.py', 'backend/discord_bot.py'):
    data = subprocess.check_output(['git', 'show', ':' + file], cwd=root)
    assert b'answer_sync' in data and b'discord_m3' not in data and b'm3_client' not in data
    target = remote / file
    current = target.read_bytes()
    assert b'discord_m3' in current, 'Unexpected current deployment; review before replacing'
    backup = ops / ('concurrent-' + Path(file).name + '.txt')
    if not backup.exists():
        backup.write_bytes(current)
    target.write_bytes(data)
    assert target.read_bytes() == data
subprocess.run(['schtasks.exe', '/Run', '/S', '192.168.10.8', '/TN', 'PrimeFlow-DiscordAnswerSync-20261027'], check=True)
print('SYNC_ENTRY_POINTS_RESTORED_WITHOUT_M3_WORKTREE_CHANGES')
