#!/usr/bin/env python3
"""Deploy CIRURGICO do faturamento automatico mensalista no Onix completo (AlmaLinux).

REGRAS:
- Só substitui faturamento_automatico_mensalista_service.py
- NUNCA copia main.py / rotas inteiras do GitHub enxuto sobre producao
- Faz backup timestampado antes de qualquer escrita
- Nao toca BotBot, Fopa, lembrete, SMTP, mobile, etc.

Uso (no servidor AlmaLinux, como root):
  python3 scripts/deploy_faturamento_auto_cirurgico.py
  python3 scripts/deploy_faturamento_auto_cirurgico.py --restart
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOTS = [
    Path("/opt/onixsystem-prod/sga_financeiro"),
    Path("/opt/onixsystem-homolog/sga_financeiro"),
]

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_SGA = SCRIPT_DIR.parent / "sga_financeiro"
SERVICE_SRC = REPO_SGA / "services" / "faturamento_automatico_mensalista_service.py"
REL = Path("services/faturamento_automatico_mensalista_service.py")


def die(msg: str) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def md5(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def backup(path: Path, backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    dest = backup_root / path.name
    shutil.copy2(path, dest)
    print(f"  backup: {path} -> {dest}")
    return dest


def deploy_one(root: Path, stamp: str) -> None:
    if not root.is_dir():
        print(f"SKIP (nao existe): {root}")
        return
    dest = root / REL
    if not dest.is_file():
        die(f"destino ausente (nao criar do zero sem validar): {dest}")
    before = md5(dest)
    broot = root.parent / "restore-points" / f"faturamento-auto-{stamp}"
    backup(dest, broot)
    shutil.copy2(SERVICE_SRC, dest)
    after = md5(dest)
    print(f"OK {root.parent.name}: {before} -> {after}")


def restart_services() -> None:
    for unit in ("onix-prod", "onix-homolog"):
        r = subprocess.run(["systemctl", "restart", unit], check=False)
        print(f"restart {unit}: rc={r.returncode}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()
    if not SERVICE_SRC.is_file():
        die(f"fonte ausente: {SERVICE_SRC}")
    # Guardas minimas: categoria MENSALISTA + catch-up
    text = SERVICE_SRC.read_text(encoding="utf-8")
    if "MENSALISTA" not in text:
        die("fonte sem MENSALISTA — abortando")
    if "_deve_faturar_hoje" not in text:
        die("fonte sem catch-up (_deve_faturar_hoje) — abortando")
    if "_emitir_nfse_e_enviar_documentos" not in text:
        die("fonte sem fluxo NFS-e/documentos — abortando")
    if "completar_fluxo_fiscal_pos_faturamento_once" not in text:
        die("fonte sem catch-up fiscal — abortando")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"fonte md5={md5(SERVICE_SRC)}")
    for root in ROOTS:
        deploy_one(root, stamp)
    if args.restart:
        restart_services()
    print("deploy cirurgico concluido")


if __name__ == "__main__":
    main()
