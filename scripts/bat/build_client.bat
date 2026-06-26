@echo off
rem Сборка клиентского приложения в .exe (PyInstaller, one-folder).
rem %~dp0 — папка scripts\bat\, ..\..\ поднимает к корню проекта.
rem Результат: client\dist\Registrator\Registrator.exe
"%~dp0..\..\client\.venv\Scripts\python.exe" "%~dp0..\..\client\build_app.py"
pause
