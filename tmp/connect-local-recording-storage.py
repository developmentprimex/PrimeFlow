from pathlib import Path
import shutil
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.recording_files_archive import digest_file

workspace = Path(__file__).resolve().parents[1]
source_root = workspace / 'backend/uploads/meeting-recordings'
target_root = Path(r'\\192.168.10.8\C$\PrimeFlowData\MeetingRecordings')
if not target_root.is_dir():
    raise RuntimeError('Verified persistent server storage is unavailable')
count = 0
for source in source_root.rglob('*'):
    if not source.is_file() or source.name == '.finalize.lock' or source.suffix == '.part':
        continue
    target = target_root / source.relative_to(source_root)
    if target.exists():
        if digest_file(source) != digest_file(target):
            raise RuntimeError(f'Conflicting file, original retained: {source.relative_to(source_root)}')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert digest_file(source) == digest_file(target)
    count += 1
env = workspace / 'backend/.env'
key = 'MEETING_RECORDINGS_ROOT='
lines = [line for line in env.read_text(encoding='utf-8').splitlines() if not line.startswith(key)]
lines.append(key + str(target_root))
env.write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(f'Local media verified ({count} files); configured persistent shared recording root')
