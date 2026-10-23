import json
from pathlib import Path

server = r'\\192.168.10.8'

def unc(path):
    if len(path) > 2 and path[1] == ':':
        return Path(server + '\\' + path[0] + '$' + path[2:].replace('/', '\\'))
    return Path(path)

roots = set()
dump = Path(server + r'\C$\pm2-system\dump.pm2')
for item in json.loads(dump.read_text(encoding='utf-8-sig')):
    if 'backend' in item.get('name', '') or 'api' in item.get('name', ''):
        cwd = item.get('pm_cwd', '')
        configured = item.get('MEETING_RECORDINGS_ROOT') or item.get('env', {}).get('MEETING_RECORDINGS_ROOT')
        print(json.dumps({'process': item.get('name'), 'cwd': cwd, 'recordings_root': configured}))
        if cwd:
            root = unc(cwd)
            env = root / '.env'
            if env.is_file():
                for line in env.read_text(encoding='utf-8-sig').splitlines():
                    if line.startswith('MEETING_RECORDINGS_ROOT='):
                        configured = line.split('=', 1)[1].strip().strip('"')
                        print(json.dumps({'configured_in_env': configured}))
            roots.add(str(unc(configured) if configured and ':' in configured else root / (configured or 'uploads/meeting-recordings')))
for repo in ('PrimeFlow', 'Primex-TaskManager'):
    roots.add(str(Path(server + r'\C$\actions-runner\_work') / repo / repo / 'backend/uploads/meeting-recordings'))
rid = '78e048ae-6965-407d-96d4-99f21fe315fa'
for root in sorted(roots):
    path = Path(root)
    session = path / '2026/10' / rid
    if not path.is_dir():
        print(json.dumps({'root': root, 'exists': False}))
        continue
    files = []
    if session.is_dir():
        files = [{'name': p.name, 'bytes': p.stat().st_size} for p in session.iterdir() if p.is_file()]
    chunks = session / 'chunks'
    print(json.dumps({'root': root, 'exists': True, 'session_exists': session.is_dir(), 'files': files,
                      'chunks': len(list(chunks.glob('*.chunk'))) if chunks.is_dir() else 0}))
