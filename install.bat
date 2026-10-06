@echo off
setlocal
cd /d "%~dp0"
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  python scripts\manage.py install
) else (
  py -3.11 scripts\manage.py install
)
set "result=%errorlevel%"
pause
exit /b %result%
