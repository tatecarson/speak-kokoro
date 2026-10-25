#define AppVersion "0.4.1"
[Setup]
AppId={{903F68F0-66F7-4B29-8F72-E806CA9AF0B1}
AppName=Speak Kokoro
AppVersion={#AppVersion}
AppPublisher=Tate Carson
AppPublisherURL=https://github.com/tatecarson/speak-kokoro
DefaultDirName={localappdata}\Programs\Speak Kokoro
DefaultGroupName=Speak Kokoro
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\installers
OutputBaseFilename=speak-kokoro-{#AppVersion}-windows-x64-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Speak Kokoro.exe
SetupIconFile=speak-kokoro.ico
CloseApplications=yes
LicenseFile=..\LICENSE

[Files]
Source: "..\dist\speak-kokoro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\packaging\GETTING-STARTED.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Speak Kokoro"; Filename: "{app}\Speak Kokoro.exe"; Parameters: "--gui"; WorkingDir: "{app}"
Name: "{group}\Speak Kokoro terminal"; Filename: "{cmd}"; Parameters: "/K """"{app}\speak-kokoro.exe"" --help"""; WorkingDir: "{app}"
Name: "{group}\Getting started"; Filename: "{app}\GETTING-STARTED.txt"
Name: "{group}\Uninstall Speak Kokoro"; Filename: "{uninstallexe}"

[UninstallRun]
Filename: "{app}\speak-kokoro.exe"; Parameters: "--quit"; Flags: runhidden; RunOnceId: "StopKokoro"
