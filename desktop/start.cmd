@echo off
cd /d "%~dp0\.."
if not exist desktop\.venv\Scripts\pythonw.exe (
  echo Run powershell -ExecutionPolicy Bypass -File desktop\build.ps1 first.
  pause
  exit /b 1
)
start "" desktop\.venv\Scripts\pythonw.exe desktop\launch.py
