@echo off
rem Kyeon - show it now (starts it if it is not running; re-opens it if dismissed today).
rem   show.bat                        -> finds pythonw.exe on PATH (or next to python.exe)
rem   show.bat C:\path\to\pythonw.exe -> uses the given interpreter
setlocal
cd /d "%~dp0"

if not "%~1"=="" (
    start "" "%~1" "%~dp0kyeon.py"
    exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0kyeon.py"
    exit /b 0
)

for /f "delims=" %%i in ('where python 2^>nul') do (
    if exist "%%~dpipythonw.exe" (
        start "" "%%~dpipythonw.exe" "%~dp0kyeon.py"
        exit /b 0
    )
)

echo [ERROR] pythonw.exe was not found. Run: show.bat C:\path\to\pythonw.exe
exit /b 1
