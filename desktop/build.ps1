$ErrorActionPreference = 'Stop'
$miraRoot = Split-Path -Parent $PSScriptRoot
Set-Location $miraRoot
python -m venv desktop/.venv
& desktop/.venv/Scripts/python.exe -m pip install --disable-pip-version-check -r desktop/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Mira dependency installation failed' }
& desktop/.venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name Mira --paths desktop --exclude-module pytest --exclude-module IPython --exclude-module matplotlib --distpath output/mira-windows --workpath tmp/mira-build --specpath tmp desktop/launch.py
if ($LASTEXITCODE -ne 0) { throw 'Mira packaging failed' }
Write-Output 'Ready: output/mira-windows/Mira/Mira.exe'
