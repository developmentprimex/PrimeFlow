"""Stage the requested desktop-only activation with exact source guards."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess

LOCAL = Path(__file__).resolve().parents[1]
STATE_DIR = LOCAL/'tmp'
REMOTE = Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend')
NAME = 'MiraWindows-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
OPS = Path(r'\\192.168.10.8\C$\PrimeFlowOps')/NAME
SERVER_OPS = Path(r'C:\PrimeFlowOps')/NAME


def digest(raw):return hashlib.sha256(raw).hexdigest()


def main():
    staged={name:(LOCAL/'backend'/name).read_bytes() for name in (
        'app/models/mira_desktop.py','app/schemas/mira_desktop.py',
        'app/services/mira_desktop.py','app/api/routers/mira_desktop.py',
        'alembic/versions/0164_project_is_active.py',
        'alembic/versions/0165_mira_desktop.py')}
    router_name='app/api/routers/__init__.py'
    router=(REMOTE/router_name).read_text(encoding='utf-8-sig')
    anchor='api_router = APIRouter()'
    if router.count(anchor)!=1 or 'mira_desktop' in router:raise RuntimeError('Unexpected router state')
    staged[router_name]=router.replace(anchor,anchor+'\nfrom app.api.routers.mira_desktop import router as mira_desktop_router\n'
        'api_router.include_router(mira_desktop_router, prefix="/mira-desktop", tags=["mira-desktop"])').encode()
    model_name='app/models/__init__.py'
    model=(REMOTE/model_name).read_text(encoding='utf-8-sig')
    if 'mira_desktop' in model:raise RuntimeError('Unexpected model state')
    staged[model_name]=(model.rstrip()+'\nfrom app.models.mira_desktop import MiraDesktopSession, MiraDesktopSegment\n').encode()
    publish_staged(staged)


def publish_staged(staged):
    OPS.mkdir(parents=True)
    manifest=[]
    for name,raw in staged.items():
        target=REMOTE/name
        before=digest(target.read_bytes()) if target.exists() else None
        stage=OPS/'staged'/name;stage.parent.mkdir(parents=True,exist_ok=True);stage.write_bytes(raw)
        manifest.append(dict(path=name,before=before,after=digest(raw)))
    (OPS/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    shutil.copy2(LOCAL/'desktop/activate_server.py',OPS/'activate_server.py')
    command_lines=['@echo off',r'cd /d C:\actions-runner\_work\PrimeFlow\PrimeFlow\backend',
        r'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe '
        +str(SERVER_OPS/'activate_server.py')+' > '+str(SERVER_OPS/'activation.log')+' 2>&1',
        'exit /b %ERRORLEVEL%']
    (OPS/'activate.cmd').write_text('\r\n'.join(command_lines)+'\r\n',encoding='ascii')
    xml=f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<RegistrationInfo><Description>User-authorized one-time Mira Windows API activation, desktop files only.</Description></RegistrationInfo>
<Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><Hidden>true</Hidden><ExecutionTimeLimit>PT10M</ExecutionTimeLimit><AllowStartOnDemand>true</AllowStartOnDemand></Settings>
<Actions Context="Author"><Exec><Command>{SERVER_OPS/'activate.cmd'}</Command></Exec></Actions></Task>'''
    STATE_DIR.mkdir(parents=True,exist_ok=True)
    task_xml=STATE_DIR/'mira-activate-server.xml';task_xml.write_text(xml,encoding='utf-16')
    task='PrimeFlow-'+NAME
    (STATE_DIR/'mira-server-activation.json').write_text(json.dumps(dict(ops=str(OPS),task=task)),encoding='utf-8')
    subprocess.run(['schtasks.exe','/Create','/S','192.168.10.8','/TN',task,'/XML',str(task_xml),'/F'],check=True)
    subprocess.run(['schtasks.exe','/Run','/S','192.168.10.8','/TN',task],check=True)
    print(json.dumps(dict(ops=str(OPS),task=task,staged_files=len(manifest))))


if __name__=='__main__':main()
