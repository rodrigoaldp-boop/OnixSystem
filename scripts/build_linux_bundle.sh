#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Onix System | Build Linux (PyInstaller) =="

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"

python -m pip install --upgrade pip
python -m pip install -r "$ROOT/sga_financeiro/requirements.txt"
python -m pip install pyinstaller

# POSIX --add-data usa ':' (no Windows e ';')
pyinstaller \
  --noconfirm \
  --clean \
  --name OnixSystem \
  --add-data "sga_financeiro:sga_financeiro" \
  "$ROOT/sga_financeiro/main.py"

echo "Build concluido. Saida em $ROOT/dist/OnixSystem/"
echo "Executavel: $ROOT/dist/OnixSystem/OnixSystem"
