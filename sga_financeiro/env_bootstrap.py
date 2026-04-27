"""Carrega .env antes do Pydantic sem exigir UTF-8 (ANSI/cp1252 no Windows)."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _exe_or_repo_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _ler_texto(path: Path) -> str | None:
    if not path.is_file():
        return None
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_dotenv_linhas(texto: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("export "):
            linha = linha[7:].strip()
        if "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if chave:
            out[chave] = valor
    return out


def aplicar_dotenv_no_ambiente() -> None:
    """Popula os.environ com .env (UTF-8 ou cp1252). Ordem: pasta do exe, repo, cwd."""
    candidatos: list[Path] = []
    candidatos.append(_exe_or_repo_root() / ".env")
    candidatos.append(Path(__file__).resolve().parents[1] / ".env")
    candidatos.append(Path.cwd() / ".env")
    vistos: set[Path] = set()
    for arq in candidatos:
        try:
            rp = arq.resolve()
        except Exception:
            continue
        if rp in vistos:
            continue
        vistos.add(rp)
        texto = _ler_texto(arq)
        if not texto:
            continue
        for chave, valor in _parse_dotenv_linhas(texto).items():
            os.environ.setdefault(chave, valor)
