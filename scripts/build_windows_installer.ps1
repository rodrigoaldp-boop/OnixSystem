$ErrorActionPreference = "Stop"

Write-Host "== Onix System | Build Windows Installer =="

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$innoScript = Join-Path $root "scripts\OnixSystem.iss"
$innoCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"

if (!(Test-Path ".venv")) {
  python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r ".\sga_financeiro\requirements.txt"
& ".\.venv\Scripts\python.exe" -m pip install pyinstaller

# Gera executavel do backend FastAPI (modo local/browser).
& ".\.venv\Scripts\pyinstaller.exe" `
  --noconfirm `
  --clean `
  --name OnixSystem `
  --add-data "sga_financeiro; sga_financeiro" `
  ".\sga_financeiro\main.py"

Write-Host "Build concluido. Saida em .\dist\OnixSystem\"

if (Test-Path $innoCompiler) {
  if (!(Test-Path $innoScript)) {
    throw "Arquivo Inno Setup nao encontrado: $innoScript"
  }

  $distPayload = Join-Path $root "dist\OnixSystem"
  if (!(Test-Path (Join-Path $distPayload "OnixSystem.exe"))) {
    throw "PyInstaller nao gerou dist\OnixSystem\OnixSystem.exe em: $distPayload"
  }

  Write-Host "Inno Setup encontrado. Gerando setup.exe..."
  # Caminho absoluto evita instalador sem arquivos se o ISCC resolver relativo errado.
  & $innoCompiler "/DRepoRoot=$root" $innoScript
  Write-Host "Instalador gerado em .\release\OnixSystem-Setup.exe"
} else {
  Write-Host "Inno Setup nao encontrado."
  Write-Host "Instale em https://jrsoftware.org/isinfo.php e rode o script novamente para gerar o setup.exe."
}

