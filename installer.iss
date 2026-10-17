; Installer Spotify Now Playing (Inno Setup 6)
; Build lewat build.ps1, atau: ISCC.exe /DAppVersion=1.0.0 installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Spotify Now Playing"
#define AppExe "SpotifyNowPlaying.exe"

[Setup]
AppId={{6F1C8E2A-3B4D-4E5F-9A1B-2C3D4E5F6A7B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=mohammadrafly
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; install per-user, tidak perlu admin
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=SpotifyNowPlaying-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
StartupTask=Jalankan otomatis saat Windows menyala (minimized)
SettingsIcon=Pengaturan (browser)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "{cm:StartupTask}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\SpotifyNowPlaying\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:SettingsIcon}"; Filename: "http://127.0.0.1:8765/settings"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--no-browser"; Flags: runminimized; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "KillApp"
