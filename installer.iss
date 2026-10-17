[Setup]
AppId={{B9AF1C1A-EDC7-4A3E-9A17-5C86BC7DBB56}
AppName=Notas Estudiantes
AppVersion=1.0.0
AppPublisher=Notas Estudiantes
DefaultDirName={localappdata}\Notas Estudiantes
DefaultGroupName=Notas Estudiantes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=NotasEstudiantes-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\NotasEstudiantes.exe

[Files]
Source: "dist\NotasEstudiantes\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Notas Estudiantes"; Filename: "{app}\NotasEstudiantes.exe"
Name: "{autodesktop}\Notas Estudiantes"; Filename: "{app}\NotasEstudiantes.exe"

[Run]
Filename: "{app}\NotasEstudiantes.exe"; Description: "Iniciar Notas Estudiantes"; Flags: nowait postinstall skipifsilent
