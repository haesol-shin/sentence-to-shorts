; Inno Setup script generated from this template by the installer probe.
; The probe fills the @...@ values at run time from core/config/brand.yaml and runtime.json.
[Setup]
AppId=@APP_ID@
AppName=@DISPLAY_NAME@
AppVersion=@VERSION@
DefaultDirName={localappdata}\Programs\@APP_ID@\@VERSION@
DefaultGroupName=@DISPLAY_NAME@
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableWelcomePage=yes
OutputDir=@OUTPUT_DIR@
OutputBaseFilename=@OUTPUT_NAME@
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=@DISPLAY_NAME@
CloseApplications=no

[Files]
Source: "@BUNDLE_DIR@\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\@DISPLAY_NAME@"; Filename: "{app}\env\Scripts\pythonw.exe"; Parameters: """{app}\launcher.py"""; WorkingDir: "{app}"

[Run]
Filename: "{app}\env\Scripts\pythonw.exe"; Parameters: """{app}\launcher.py"""; Description: "@DISPLAY_NAME@"; Flags: nowait postinstall skipifsilent
