"""Stage a bounded read-only probe using the already-authorized admin channel."""
from pathlib import Path
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
info=json.loads((ROOT/'tmp/mira-server-activation.json').read_text())
ops=Path(info['ops'])
server_ops=Path(r'C:\PrimeFlowOps')/ops.name
shutil.copy2(ROOT/'desktop/diagnose_server.py',ops/'diagnose_server.py')
lines=['@echo off',r'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe '+
    str(server_ops/'diagnose_server.py')+' > '+str(server_ops/'diagnose.log')+' 2>&1']
(ops/'diagnose.cmd').write_text('\r\n'.join(lines)+'\r\n',encoding='ascii')
xml=f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
<Settings><Hidden>true</Hidden><ExecutionTimeLimit>PT2M</ExecutionTimeLimit><AllowStartOnDemand>true</AllowStartOnDemand></Settings>
<Actions Context="Author"><Exec><Command>{server_ops/'diagnose.cmd'}</Command></Exec></Actions></Task>'''
path=ROOT/'tmp/mira-diagnose-server.xml';path.write_text(xml,encoding='utf-16')
task=info['task']+'-Diagnose'
subprocess.run(['schtasks.exe','/Create','/S','192.168.10.8','/TN',task,'/XML',str(path),'/F'],check=True)
subprocess.run(['schtasks.exe','/Run','/S','192.168.10.8','/TN',task],check=True)
print(json.dumps(dict(task=task,report=str(ops/'processes.json'))))
