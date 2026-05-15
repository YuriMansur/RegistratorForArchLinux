@echo off
setlocal enabledelayedexpansion

rem === Create client/.venv on this machine using installed Python, then install deps. ===
rem === Run once after `git clone`. Idempotent: safe to re-run to refresh dependencies. ===

set "ROOT_DIR=%~dp0"
set "CLIENT_DIR=%ROOT_DIR%client"
set "VENV=%CLIENT_DIR%\.venv"
set "REQ=%CLIENT_DIR%\requirements.txt"

if not exist "%REQ%" (
    echo [ERROR] %REQ% not found. Run this script from the project root.
    pause
    exit /b 1
)

rem ---- Find a Python interpreter on this machine ----
set "PY_CMD="

rem 1) py launcher with latest Python 3.x
where py >nul 2>&1
if not errorlevel 1 (
    py -3 -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3"
)

rem 2) `python` from PATH
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo.
    echo [ERROR] No working Python found on this machine.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo Using: !PY_CMD!
!PY_CMD! --version

rem ---- Create venv if missing ----
if exist "%VENV%\Scripts\python.exe" (
    echo [1/2] venv already exists at %VENV%, reusing it.
) else (
    echo [1/2] Creating venv at %VENV%...
    !PY_CMD! -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
)

rem ---- Install dependencies into venv ----
echo [2/2] Installing dependencies from %REQ%...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r "%REQ%"
if errorlevel 1 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

echo.
echo ======================================================
echo  Done. Run run_client.bat to start the client.
echo ======================================================
pause
endlocal
