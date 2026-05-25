@echo off
setlocal enabledelayedexpansion

rem === Create client/.venv on this machine using installed Python, then install deps. ===
rem === Run once after `git clone`. Idempotent: safe to re-run to refresh dependencies. ===

rem Required Python major.minor (must match what client/.venv was built against).
set "PY_TAG=3.12"

rem %~dp0 — папка scripts\bat\, ..\..\ поднимает к корню проекта.
set "ROOT_DIR=%~dp0..\..\"
set "CLIENT_DIR=%ROOT_DIR%client"
set "VENV=%CLIENT_DIR%\.venv"
set "REQ=%CLIENT_DIR%\requirements.txt"

if not exist "%REQ%" (
    echo [ERROR] %REQ% not found. Run this script from the project root.
    pause
    exit /b 1
)

rem ---- Find Python %PY_TAG%.x on this machine ----
set "PY_CMD="

rem 1) py launcher with exact -X.Y (most reliable)
where py >nul 2>&1
if not errorlevel 1 (
    py -%PY_TAG% -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -%PY_TAG%"
)

rem 2) `python` from PATH, only if major.minor matches
if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%v in ('python -c "import sys; print('{}.{}'.format(sys.version_info[0],sys.version_info[1]))" 2^>nul') do (
            if "%%v"=="%PY_TAG%" set "PY_CMD=python"
        )
    )
)

if not defined PY_CMD (
    echo.
    echo [ERROR] Python %PY_TAG% not found on this machine.
    echo This project requires Python %PY_TAG%.x.
    echo Install it from https://www.python.org/downloads/
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
