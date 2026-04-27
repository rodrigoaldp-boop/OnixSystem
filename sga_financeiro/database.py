"""Modulo de conexao com banco PostgreSQL via SQLAlchemy."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sga_financeiro.config import settings
from sga_financeiro.local_config import load_local_config


class Base(DeclarativeBase):
    """Classe base para todos os models ORM."""


def _connect_args_do_config_local() -> dict[str, object] | None:
    """Monta kwargs do psycopg2 direto do JSON (sem parsear URL). Evita UnicodeDecodeError."""
    cfg = load_local_config()
    host = str(cfg.get("db_host") or "").strip()
    db_name = str(cfg.get("db_name") or "").strip()
    user = str(cfg.get("db_user") or "").strip()
    if not host or not db_name or not user:
        return None
    port = int(cfg.get("db_port") or 5432)
    password = str(cfg.get("db_password") or "")
    return {
        "host": host,
        "port": port,
        "dbname": db_name,
        "user": user,
        "password": password,
        "client_encoding": "UTF8",
    }


def _create_engine():
    """Evita UnicodeDecodeError no Windows (DSN/libpq + variaveis PG* em ANSI)."""
    os.environ.setdefault("PGCLIENTENCODING", "UTF8")

    direct = _connect_args_do_config_local()
    if direct:
        # PGPASSWORD no sistema costuma estar em cp1252; libpq tenta UTF-8 e quebra com acentos.
        for key in ("PGPASSWORD", "PGUSER", "PGDATABASE", "PGHOST", "PGPORT"):
            os.environ.pop(key, None)
        return create_engine(
            "postgresql+psycopg2://",
            connect_args=direct,
            echo=settings.DEBUG,
            future=True,
            pool_pre_ping=True,
        )

    raw = (settings.DATABASE_URL or "").strip()
    if not raw.startswith("postgresql"):
        return create_engine(raw, echo=settings.DEBUG, future=True, pool_pre_ping=True)
    try:
        u = make_url(raw)
        os.environ.pop("PGPASSWORD", None)
        connect_args: dict[str, object] = {
            "dbname": u.database or "",
            "user": u.username or "",
            "password": u.password if u.password is not None else "",
            "host": u.host or "localhost",
            "port": u.port or 5432,
            "client_encoding": "UTF8",
        }
        return create_engine(
            "postgresql+psycopg2://",
            connect_args=connect_args,
            echo=settings.DEBUG,
            future=True,
            pool_pre_ping=True,
        )
    except Exception:
        return create_engine(raw, echo=settings.DEBUG, future=True, pool_pre_ping=True)


engine = _create_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    class_=Session,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency do FastAPI para obter uma sessao por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
