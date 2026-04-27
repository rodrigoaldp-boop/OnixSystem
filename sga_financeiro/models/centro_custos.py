"""Model ORM para centros de custos."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class CentroCustos(Base):
    __tablename__ = "centros_custos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    codigo: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    descricao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    responsavel: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    contas_pagar = relationship("ContaPagar", back_populates="centro_custos")
    contas_receber = relationship("ContaReceber", back_populates="centro_custos")
