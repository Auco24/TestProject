; Inno Setup script for the Dev Toolkit Windows installer.
; Built by CI after PyInstaller:  ISCC.exe /DAppVersion=1.0.0 packaging\windows\installer.iss
; Output: dist\installer\DevToolkit-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "Dev Toolkit"
#define AppExe "DevToolkit.exe"
#define AppPublisher "Auco24"
#define AppURL "https://github.com/Auco24/TestProject"

[Setup]
; never change AppId: Windows uses it to recognise upgrades of the same app
AppId={{7D3A2E61-4F0B-4C7E-9A55-2B8D6C1E9F42}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
; per-user install: no administrator rights needed
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
SetupIconFile=..\..\devtool\assets\icon.ico
OutputDir=..\..\dist\installer
OutputBaseFilename=DevToolkit-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\DevToolkit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Your snippets, journal and settings live in %USERPROFILE%\.devtool and are kept on uninstall.
