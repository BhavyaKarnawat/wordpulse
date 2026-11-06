; Inno Setup script for WordPulse (per-user install, no admin rights needed).
; Build: install Inno Setup 6 (free, jrsoftware.org), then run build.ps1 - it compiles this automatically.

#define AppName "WordPulse"
#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif

[Setup]
AppId={{6E1E5B7A-3C2F-4B8E-9A41-5F2C8D7E0A13}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=WordPulse
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=WordPulse-Setup-{#AppVersion}
SetupIconFile=..\assets\wordpulse.ico
UninstallDisplayIcon={app}\WordPulse.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
Name: "autostart"; Description: "Start WordPulse when I sign in to Windows"
Name: "screensaver"; Description: "Use WordPulse as my screensaver"; Flags: unchecked

[Files]
Source: "..\dist\WordPulse.exe"; DestDir: "{app}"; Flags: ignoreversion
; the screensaver is the same program under another name: Inno stores the file once
Source: "..\dist\WordPulse.exe"; DestDir: "{app}"; DestName: "WordPulse.scr"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\WordPulse.exe"
Name: "{group}\{#AppName} Settings"; Filename: "{app}\WordPulse.exe"; Parameters: "--settings"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\WordPulse.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WordPulse"; ValueData: """{app}\WordPulse.exe"""; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Control Panel\Desktop"; ValueType: string; ValueName: "SCRNSAVE.EXE"; ValueData: "{app}\WordPulse.scr"; Tasks: screensaver

[Run]
Filename: "{app}\WordPulse.exe"; Description: "Start WordPulse now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/IM WordPulse.exe /F"; Flags: runhidden; RunOnceId: "StopApp"

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\WordPulse\logs"
