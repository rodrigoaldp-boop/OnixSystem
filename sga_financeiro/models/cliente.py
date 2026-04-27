"""Model ORM para clientes."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    cnpj_cpf: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    telefone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    endereco: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    limite_credito: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    contas_receber = relationship("ContaReceber", back_populates="cliente")
