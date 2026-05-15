@echo off
setlocal
cd /d "%~dp0client"
set "PY_BIN=.venv\Scripts\python.exe"

rem First-time setup after `git clone`: create venv + install deps.
if not exist "%PY_BIN%" (
    echo venv not found, running setup_venv.bat...
    call "%~dp0setup_venv.bat"
    if errorlevel 1 exit /b 1
)

"%PY_BIN%" main.py 2>&1
pause
endlocal
