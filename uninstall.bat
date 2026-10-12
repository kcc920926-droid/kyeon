@echo off
rem Kyeon - uninstall: remove run-at-logon + stop the widget.
rem   uninstall.bat                       -> uses "python" on PATH
rem   uninstall.bat C:\path\to\python.exe -> uses the given interpreter
rem Saved state (%LOCALAPPDATA%\Kyeon) is kept; delete that folder to reset fully.
setlocal
cd /d "%~dp0"
set "PY=%~1"
if "%PY%"=="" set "PY=python"
"%PY%" "%~dp0kyeon.py" --uninstall
exit /b %errorlevel%
