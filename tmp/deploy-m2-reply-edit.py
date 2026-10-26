"""Publish the two-file fix for editing an existing M2 reply."""
import hashlib
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
remote = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow')
backup_root = Path(r'\\192.168.10.8\C$\PrimeFlowOps\M2Replies-20261026\backup')
files = ['backend/app/api/routers/discord_m2.py', 'backend/discord_m2_client.py']
for file in files:
    target, source, backup = remote / file, root / file, backup_root / file
    assert target.resolve().is_relative_to(remote.resolve())
    deployed = target.read_text(encoding='utf-8-sig')
    if deployed != source.read_text(encoding='utf-8-sig'):
        if backup.exists() and deployed != backup.read_text(encoding='utf-8-sig'):
            raise RuntimeError('Unexpected server change: ' + file)
        if not backup.exists() and 'expected_answered_at' in deployed:
            raise RuntimeError('An edit-enabled version is already deployed: ' + file)
for file in files:
    target, source, backup = remote / file, root / file, backup_root / file
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    shutil.copy2(source, target)
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest()
print(json.dumps({'copied': len(files), 'backup': str(backup_root)}))
