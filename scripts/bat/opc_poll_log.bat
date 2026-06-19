@echo off
rem %~dp0 — папка scripts\bat\, ..\..\ поднимает к корню проекта.
rem Аргументы (%*) пробрасываем в скрипт: [host] [интервал_сек].
rem Примеры:
rem   opc_poll_log.bat
rem   opc_poll_log.bat 192.168.100.100
rem   opc_poll_log.bat 192.168.10.222 0.5
"%~dp0..\..\client\.venv\Scripts\python.exe" "%~dp0..\opc_poll_log.py" %*
pause
