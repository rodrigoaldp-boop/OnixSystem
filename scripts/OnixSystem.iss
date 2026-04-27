; Caminhos relativos a esta pasta (scripts/), para nao depender de /DMyAppRoot no ISCC.
; Evita instalador vazio quando o .iss e compilado pelo assistente sem defines.
#define RepoRoot ".."

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

[Icons]
Name: "{autoprograms}\Onix System"; Filename: "{app}\OnixSystem.exe"
Name: "{autodesktop}\Onix System"; Filename: "{app}\OnixSystem.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\OnixSystem.exe"; Description: "{cm:LaunchProgram,Onix System}"; Flags: nowait postinstall skipifsilent
