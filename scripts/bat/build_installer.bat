@echo off
rem Сборка установщика RegistratorSetup.exe (Inno Setup) из client\installer.iss.
rem ПЕРЕД этим должна быть собрана папка client\dist\Registrator (build_client.bat).
rem Результат: client\dist\RegistratorSetup.exe

rem Inno Setup может стоять per-user (winget) или в Program Files — пробуем оба.
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo ISCC.exe не найден. Установите Inno Setup: winget install JRSoftware.InnoSetup
  pause
  exit /b 1
)

"%ISCC%" "%~dp0..\..\client\installer.iss"
pause
