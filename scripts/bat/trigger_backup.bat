@echo off
rem %~dp0 — папка scripts\bat\, ..\..\ поднимает к корню проекта.
"%~dp0..\..\client\.venv\Scripts\python.exe" "%~dp0..\trigger_backup.py"
pause
