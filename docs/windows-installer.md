# Onix System - Instalador Windows (base)

Este roteiro cria um executavel base do sistema e prepara o caminho para um `setup.exe`.

## 0) Copiar o projeto do Linux (AlmaLinux) para o Windows

**Importante:** nao copie a pasta `dist\` gerada no Linux esperando montar um instalador Windows — o PyInstaller no Linux produz binarios Linux. No PC Windows voce precisa do **codigo-fonte** e rodar o build de novo.

### O que copiar

Inclua pelo menos:

- `sga_financeiro\` (aplicacao)
- `scripts\` (`build_windows_installer.ps1` e `OnixSystem.iss`)

Opcional: `docs\`, `.github\`. Nao e obrigatorio para gerar o `.exe`.

### O que pode omitir (para arquivo menor)

- `.venv\` na raiz e `sga_financeiro\.venv\` — serao recriados no Windows pelo script
- `dist\`, `build\` — saidas antigas
- `restore-points\` — backups locais, em geral nao precisam no instalador

Evite copiar `.env` com segredos em rede aberta; no cliente use `config.local.json` depois da instalacao.

### Empacotar no servidor (exemplo)

No AlmaLinux, na pasta pai do projeto:

```bash
cd /caminho/pai
tar --exclude='OnixSystem/.venv' \
    --exclude='OnixSystem/sga_financeiro/.venv' \
    --exclude='OnixSystem/dist' \
    --exclude='OnixSystem/build' \
    --exclude='OnixSystem/restore-points' \
    --exclude='OnixSystem/.git' \
    -czvf OnixSystem-windows-build.tar.gz OnixSystem
```

Transfira o `.tar.gz` para o Windows (SCP, pen drive, pasta de rede), extraia para algo como `C:\dev\OnixSystem`.

Depois siga a secao **1)** abaixo no Windows.

## 1) Build local no Windows

No PowerShell (como usuario normal):

```powershell
cd C:\caminho\OnixSystem
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_installer.ps1
```

Saida esperada:

- pasta `dist\OnixSystem\` com binario e arquivos do app
- se o Inno Setup estiver instalado, tambem gera `release\OnixSystem-Setup.exe`

## 2) Criar setup.exe (Inno Setup)

O script `build_windows_installer.ps1` ja tenta gerar o instalador automaticamente usando
`scripts\OnixSystem.iss`.

Se o script avisar que o Inno Setup nao foi encontrado:

1. instalar o Inno Setup 6: <https://jrsoftware.org/isinfo.php>
2. rodar novamente:

```powershell
cd C:\caminho\OnixSystem
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_installer.ps1
```

### Inno Setup manual (GUI)

Se voce ja rodou o script ate gerar `dist\OnixSystem\` e so quer compilar o instalador:

1. Abra **Inno Setup Compiler**.
2. File → Open → `scripts\OnixSystem.iss`.
3. Build → Compile (ou `Ctrl+F9`).

O script `.iss` usa caminhos relativos (`..\dist\OnixSystem`, `..\release`); nao e necessario definir `MyAppRoot`, desde que **antes** exista `dist\OnixSystem\` (rode o PyInstaller pelo `build_windows_installer.ps1`).

O `setup.exe` sai em `release\OnixSystem-Setup.exe` na raiz do projeto.

Fluxo sugerido no assistente de instalacao:

1. escolher pasta de instalacao
2. abrir o app pela primeira vez
3. em `Onix Home -> Configuracoes -> Configurar Banco (Instalacao)`:
   - informar host/ip, porta, banco, usuario, senha
   - testar conexao
   - salvar configuracao
4. reiniciar sistema

## 3) Arquivo de configuracao por maquina

- arquivo: **`config.local.json`** na **mesma pasta do `OnixSystem.exe`** (tipicamente `C:\Program Files\OnixSystem\`).
- O instalador tambem copia **`config.local.example.json`** como modelo e, na **primeira instalacao**, gera **`config.local.json`** a partir dele se voce ainda nao tiver esse arquivo (edite host, porta, nome do banco, usuario e senha).
- Prefira salvar como **UTF-8** no Notepad (Salvar como → Codificação UTF-8).
- cada computador pode apontar para o mesmo PostgreSQL ou bancos diferentes
- alteracoes de banco nao exigem reinstalacao (somente salvar e reiniciar)

## 4) Atualizacoes futuras

- o usuario pode verificar e aplicar update no proprio sistema
- fluxo com snapshot e rollback manual ja disponivel no painel de atualizacoes

