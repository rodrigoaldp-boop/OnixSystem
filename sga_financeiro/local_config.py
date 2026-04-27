"""Configuracao local por instalacao (ex.: Windows setup)."""

from __future__ import annotations

from pathlib import Path
import json
import sys
from urllib.parse import quote_plus
from typing import Any


def _project_root() -> Path:
    # PyInstaller: config.local.json fica ao lado do executavel (pasta da instalacao).
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def local_config_path() -> Path:
    return _project_root() / "config.local.json"


def load_local_config() -> dict[str, Any]:
    path = local_config_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def save_local_config(data: dict[str, Any]) -> None:
    path = local_config_path()
    payload = dict(data or {})
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def montar_database_url(cfg: dict[str, Any]) -> str:
    host = str(cfg.get("db_host") or "").strip()
    port = int(cfg.get("db_port") or 5432)
    db_name = str(cfg.get("db_name") or "").strip()
    user = str(cfg.get("db_user") or "").strip()
    password = str(cfg.get("db_password") or "").strip()
    if not host or not db_name or not user:
        return ""
    user_enc = quote_plus(user)
    pass_enc = quote_plus(password)
    return f"postgresql+psycopg2://{user_enc}:{pass_enc}@{host}:{port}/{db_name}"

