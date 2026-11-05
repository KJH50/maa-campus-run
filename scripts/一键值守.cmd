@echo off
rem ============================================================
rem Campus run one-click entry (calls scripts\oneclick.ps1)
rem Flow: single-instance check -> env self-check (auto launch MuMu)
rem       -> run.py --now -> result summary in logs\oneclick
rem Exit codes: 0 OK / 1 connect-init / 2 not reached / 3 start-stop fail / 5 already running
rem ============================================================
title Campus Run One-Click
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0oneclick.ps1" %*
set "CODE=%ERRORLEVEL%"
echo.
echo ===== Finished, exit code: %CODE% =====
echo Entry log  : %~dp0..\logs\oneclick
echo Run log    : %~dp0..\logs
echo Screenshots: %~dp0..\logs\shots
pause
exit /b %CODE%
