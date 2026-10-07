@echo off
setlocal
cd /d "%~dp0"
echo Subtitle Editor - installation
echo Checking for Python 3.11...
set "subtitle_python="

rem Verify actual Python execution, not only the exit code of a Windows alias.
for /f "delims=" %%V in ('py -3.11 -c "import sys; print('SUBTITLE_PYTHON_311' if sys.version_info[:2] == (3, 11) else 'OTHER_VERSION')" 2^>nul') do if "%%V"=="SUBTITLE_PYTHON_311" set "subtitle_python=py -3.11"
if defined subtitle_python goto install
for /f "delims=" %%V in ('python -c "import sys; print('SUBTITLE_PYTHON_311' if sys.version_info[:2] == (3, 11) else 'OTHER_VERSION')" 2^>nul') do if "%%V"=="SUBTITLE_PYTHON_311" set "subtitle_python=python"
if defined subtitle_python goto install

echo.
echo Python 3.11 was not found or could not run.
echo Install Python 3.11 from https://www.python.org/downloads/windows/
echo Enable "Add python.exe to PATH" and the Python Launcher during installation.
echo Then close this window and run install.bat again.
echo If Python is already installed, open Command Prompt and run: py -3.11 --version
pause
exit /b 1

:install
echo Using %subtitle_python%
%subtitle_python% scripts\manage.py install
set "result=%errorlevel%"
echo.
if "%result%"=="0" (
  echo Installation complete. Run start.bat to open the application.
) else (
  echo Installation failed. Read the error above before closing this window.
)
pause
exit /b %result%
