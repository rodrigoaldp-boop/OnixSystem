; Inclui caminhos absolutos gerados por build_windows_installer.ps1 (scripts/_generated_paths.iss).
; Sem esse include, compile pelo script / CI, nao abra o Inno "as cegas" na pasta errada.
#include "_generated_paths.iss"

[Setup]
AppId={{7F8D2CE8-4D10-4EAF-A7DB-2C8EF13D4B2A}
AppName=Onix System
AppVersion=1.0.0
AppPublisher=Onix System
DefaultDirName={autopf}\OnixSystem
DefaultGroupName=Onix System
DisableProgramGroupPage=yes
OutputDir={#RepoRoot}\release
OutputBaseFilename=OnixSystem-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#PayloadRoot}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#ExampleConfigPath}"; DestDir: "{app}"; DestName: "config.local.example.json"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Onix System"; Filename: "{app}\OnixSystem.exe"
Name: "{autodesktop}\Onix System"; Filename: "{app}\OnixSystem.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OnixSystem.exe"; Description: "{cm:LaunchProgram,Onix System}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if (not FileExists(ExpandConstant('{app}\config.local.json'))) and
       FileExists(ExpandConstant('{app}\config.local.example.json')) then
      FileCopy(
        ExpandConstant('{app}\config.local.example.json'),
        ExpandConstant('{app}\config.local.json'),
        False);
  end;
end;
