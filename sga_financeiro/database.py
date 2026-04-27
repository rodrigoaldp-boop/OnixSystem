"""Modulo de conexao com banco PostgreSQL via SQLAlchemy."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from sga_financeiro.config import settings


class Base(DeclarativeBase):
    """Classe base para todos os models ORM."""


engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)

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
