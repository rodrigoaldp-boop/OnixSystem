"""Modulo de conexao com banco PostgreSQL via SQLAlchemy."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sga_financeiro.config import settings


class Base(DeclarativeBase):
    """Classe base para todos os models ORM."""


def _create_engine():
    """Evita UnicodeDecodeError no Windows: libpq decodifica a DSN como UTF-8 estrito."""
    os.environ.setdefault("PGCLIENTENCODING", "UTF8")
    raw = (settings.DATABASE_URL or "").strip()
    if not raw.startswith("postgresql"):
        return create_engine(raw, echo=settings.DEBUG, future=True, pool_pre_ping=True)
    try:
        u = make_url(raw)
        connect_args: dict = {
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
