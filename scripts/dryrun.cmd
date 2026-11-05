@echo off
rem 安全演练：只截图 + 识别当前距离，不点击任何按钮
cd /d "%~dp0.."
.venv\Scripts\python.exe run.py --now --dry
pause
