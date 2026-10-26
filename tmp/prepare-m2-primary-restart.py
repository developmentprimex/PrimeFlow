from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
ops = Path(r'\\192.168.10.8\C$\PrimeFlowOps\M2Replies-20261026')
ops.mkdir(parents=True, exist_ok=True)
shutil.copy2(root / 'tmp/restart-m2-primary.ps1', ops / 'restart-primary.ps1')
(ops / 'restart-primary.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\PrimeFlowOps\\M2Replies-20261026\\restart-primary.ps1 > C:\\PrimeFlowOps\\M2Replies-20261026\\restart-primary.log 2>&1\r\nexit /b %ERRORLEVEL%\r\n', encoding='ascii')
xml = (root / 'tmp/m2-activate-task.xml').read_text(encoding='utf-8-sig')
xml = xml.replace('encoding="UTF-8"', 'encoding="UTF-16"').replace('<LogonType>ServiceAccount</LogonType>', '')
xml = xml.replace('C:\\PrimeFlowOps\\M2-20261026\\activate.cmd', 'C:\\PrimeFlowOps\\M2Replies-20261026\\restart-primary.cmd')
(root / 'tmp/m2-primary-restart-utf16.xml').write_text(xml, encoding='utf-16')
print('Prepared primary API restart with verified listener checks.')
