#!/usr/bin/env python3
"""Deploy cirurgico: valores + total nos relatorios de saida (NF-e / NFS-e)."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "sga_financeiro" / "services" / "contador_envio_service.py"

TARGETS = [
    Path("/opt/onixsystem-prod/sga_financeiro/services/contador_envio_service.py"),
    Path("/opt/onixsystem-prod/sga_financeiro/schemas/contador_envio_service.py"),
    Path("/opt/onixsystem-homolog/sga_financeiro/services/contador_envio_service.py"),
    Path("/opt/onixsystem-homolog/sga_financeiro/schemas/contador_envio_service.py"),
]


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"Fonte nao encontrada: {SRC}")
    blob = SRC.read_bytes()
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    for dst in TARGETS:
        if not dst.parent.is_dir():
            print(f"SKIP (dir ausente): {dst}")
            continue
        rp = dst.parent.parent / "restore-points"
        rp.mkdir(parents=True, exist_ok=True)
        if dst.is_file():
            shutil.copy2(dst, rp / f"{dst.name}.pre-valores-saida-{ts}")
        dst.write_bytes(blob)
        print(f"OK {dst}")


if __name__ == "__main__":
    main()
