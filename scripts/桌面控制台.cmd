@echo off
cd /d "%~dp0.."
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "run.py" --desktop
) else (
  ".venv\Scripts\python.exe" "run.py" --desktop
  if errorlevel 1 pause
)
