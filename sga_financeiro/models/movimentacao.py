"""Model ORM de historico de movimentacoes bancarias."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum as SqlEnum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class TipoMovimentacao(str, Enum):
    DEBITO = "debito"
    CREDITO = "credito"


class Movimentacao(Base):
    __tablename__ = "movimentacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tipo: Mapped[TipoMovimentacao] = mapped_column(SqlEnum(TipoMovimentacao), nullable=False)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas_correntes.id"), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False)
    referencia: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    data_movimento: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    conciliado: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    data_conciliacao: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    conta = relationship("ContaCorrente", back_populates="movimentacoes")
