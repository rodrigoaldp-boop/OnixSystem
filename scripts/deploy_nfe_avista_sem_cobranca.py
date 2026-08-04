#!/usr/bin/env python3
"""Deploy cirurgico: NF-e a vista sem grupo cobr (cStat 853)."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "sga_financeiro/services/venda_parcelas_fatura.py",
    "sga_financeiro/services/nfe_homolog_service.py",
]
ENVS = [
    Path("/opt/onixsystem-prod"),
    Path("/opt/onixsystem-homolog"),
]


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    for env in ENVS:
        for rel in FILES:
            src = ROOT / rel
            if not src.is_file():
                raise SystemExit(f"Fonte ausente: {src}")
            dst = env / rel
            # tambem espelha em schemas/ se existir copia paralela
            alts = [dst]
            schemas_alt = env / rel.replace("/services/", "/schemas/")
            if schemas_alt != dst:
                alts.append(schemas_alt)
            for target in alts:
                if not target.parent.is_dir():
                    print(f"SKIP {target}")
                    continue
                rp = env / "restore-points"
                rp.mkdir(parents=True, exist_ok=True)
                if target.is_file():
                    shutil.copy2(target, rp / f"{target.name}.pre-avista-cobr-{ts}")
                target.write_bytes(src.read_bytes())
                print(f"OK {target}")


if __name__ == "__main__":
    main()
