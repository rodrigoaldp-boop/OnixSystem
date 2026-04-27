; RepoRoot = raiz do repositorio (pasta que contem dist\ e release\).
; Build pelo script PowerShell passa /DRepoRoot=C:\...\OnixSystem (absoluto).
; Compilar manual pelo Inno: User defines -> RepoRoot=C:\caminho\completo\DoProjeto
#ifndef RepoRoot
#define RepoRoot ".."
#endif

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
Source: "{#RepoRoot}\dist\OnixSystem\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
; Modelo de configuracao — na primeira instalacao copiamos para config.local.json se ainda nao existir (ver [Code]).
Source: "{#RepoRoot}\scripts\config.local.example.json"; DestDir: "{app}"; DestName: "config.local.example.json"; Flags: ignoreversion

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
