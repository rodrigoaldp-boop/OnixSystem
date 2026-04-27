"""Model ORM de categorias financeiras."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class TipoCategoria(str, Enum):
    DESPESA = "despesa"
    RECEITA = "receita"


class Categoria(Base):
    __tablename__ = "categorias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    tipo: Mapped[TipoCategoria] = mapped_column(SqlEnum(TipoCategoria), nullable=False)
    descricao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cor: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    contas_pagar = relationship("ContaPagar", back_populates="categoria")
    contas_receber = relationship("ContaReceber", back_populates="categoria")
