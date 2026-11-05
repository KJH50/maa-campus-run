@echo off
rem Compatibility entry: same behavior as the one-click entry (calls oneclick.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0oneclick.ps1" %*
set "CODE=%ERRORLEVEL%"
echo.
echo ===== Finished, exit code: %CODE% =====
pause
exit /b %CODE%
