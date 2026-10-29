[Setup]
AppId=org.akaakuhub.codex-goal-monitor
AppName=Codex Goal Monitor
AppVersion={#AppVersion}
AppPublisher=AkaakuHub
AppPublisherURL=https://github.com/AkaakuHub/codex-goal-monitor
DefaultDirName={localappdata}\Programs\Codex Goal Monitor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=codex-goal-monitor-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\assets\icons\app.ico
UninstallDisplayIcon={app}\codex-goal-monitor.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "..\..\target\release\codex-goal-monitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Codex Goal Monitor"; Filename: "{app}\codex-goal-monitor.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Codex Goal Monitor"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\codex-goal-monitor.exe"; Description: "Codex Goal Monitor"; Flags: nowait postinstall skipifsilent
