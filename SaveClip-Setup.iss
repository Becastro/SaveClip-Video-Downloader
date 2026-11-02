#define AppName "SaveClip"
#define AppVersion "1.0.0"
#define AppPublisher "Bemastro"
#define AppExeName "SaveClip.exe"

[Setup]
AppId={{39A59684-51E5-4A4D-8B68-C94A72A72BB8}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\SaveClip
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=dist\installer
OutputBaseFilename=SaveClip-Setup
SetupIconFile=assets\saveclip.ico
UninstallDisplayIcon={app}\{#AppExeName}
LicenseFile=LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[CustomMessages]
english.DesktopIconDescription=Create a desktop shortcut
english.ShortcutsGroupDescription=Shortcuts:
english.LaunchProgram=Launch SaveClip
brazilianportuguese.DesktopIconDescription=Criar um atalho na área de trabalho
brazilianportuguese.ShortcutsGroupDescription=Atalhos:
brazilianportuguese.LaunchProgram=Abrir SaveClip

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIconDescription}"; GroupDescription: "{cm:ShortcutsGroupDescription}"; Flags: checkedonce

[Files]
Source: "dist\SaveClip.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\saveclip.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SaveClip"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\saveclip.ico"
Name: "{autodesktop}\SaveClip"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\saveclip.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram}"; Flags: postinstall nowait skipifsilent
