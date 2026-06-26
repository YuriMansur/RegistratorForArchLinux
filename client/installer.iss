; installer.iss — сборка установщика RegistratorSetup.exe (Inno Setup).
; Пакует папку dist\Registrator\ (PyInstaller one-folder) в один установщик
; «как у игры»: установка без админа в %LOCALAPPDATA%\Programs\Registrator,
; ярлыки в меню Пуск и (опц.) на рабочем столе, деинсталлятор.
;
; Компиляция: ISCC.exe client\installer.iss  → client\dist\RegistratorSetup.exe

#define AppName "Registrator"
#define AppVersion "1.0.0"
#define AppExe "Registrator.exe"
#define AppPublisher "PKBA"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Установка для текущего пользователя — без прав администратора (без UAC).
PrivilegesRequired=lowest
; {autopf} при lowest = %LOCALAPPDATA%\Programs.
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Куда и под каким именем класть готовый установщик.
OutputDir=dist
OutputBaseFilename=RegistratorSetup
; Иконка самого установщика и в «Программах и компонентах».
SetupIconFile=app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"

[Files]
; Вся папка сборки PyInstaller рекурсивно (Registrator.exe + _internal\...).
Source: "dist\Registrator\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExe}"
Name: "{group}\Удалить {#AppName}";  Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";    Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Предложить запустить приложение по завершении установки.
Filename: "{app}\{#AppExe}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent
