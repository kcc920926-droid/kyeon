@echo off
rem Kyeon - install: register run-at-logon + start now.
rem   install.bat                       -> uses "python" on PATH
rem   install.bat C:\path\to\python.exe -> uses the given interpreter
rem Uses HKCU Run key only (no admin rights). Undo with uninstall.bat.
setlocal
cd /d "%~dp0"

set "PY=%~1"
if "%PY%"=="" set "PY=python"

"%PY%" -c "import sys, tkinter; sys.exit(0 if sys.version_info[:2] >= (3, 8) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.8+ with tkinter is required: %PY%
    exit /b 1
)

"%PY%" "%~dp0kyeon.py" --check
if errorlevel 1 (
    echo [ERROR] data check failed
    exit /b 1
)

"%PY%" "%~dp0kyeon.py" --install
exit /b %errorlevel%
