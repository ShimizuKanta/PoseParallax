#ifndef AppVersion
#define AppVersion "0.3.0"
#endif
[Setup]
AppId={{FF56D2A3-95A7-48F6-AF79-3B9883104F25}
AppName=Pose Parallax
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\PoseParallax
DefaultGroupName=Pose Parallax
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\release
OutputBaseFilename=PoseParallax-Setup-{#AppVersion}-windows-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Files]
Source: "..\..\release\PoseParallax\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Pose Parallax"; Filename: "{app}\PoseParallax.exe"
Name: "{autodesktop}\Pose Parallax"; Filename: "{app}\PoseParallax.exe"
[Run]
Filename: "{app}\PoseParallax.exe"; Description: "Pose Parallax を起動"; Flags: nowait postinstall skipifsilent
; Persistent data in {localappdata}\PoseParallax is intentionally retained on uninstall.
