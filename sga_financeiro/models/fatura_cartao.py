"""Model ORM para faturas de cartao de credito."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Date, DateTime, Enum as SqlEnum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class StatusFatura(str, Enum):
    ABERTA = "aberta"
    FECHADA = "fechada"
    PAGA = "paga"


class FaturaCartao(Base):
    __tablename__ = "faturas_cartao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cartao_id: Mapped[int] = mapped_column(ForeignKey("cartoes_credito.id"), nullable=False)
    mes_referencia: Mapped[str] = mapped_column(String(7), nullable=False)
    data_fechamento: Mapped[date] = mapped_column(Date, nullable=False)
    valor_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    status: Mapped[StatusFatura] = mapped_column(SqlEnum(StatusFatura), default=StatusFatura.ABERTA, nullable=False)
    data_pagamento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    cartao = relationship("CartaoCredito", back_populates="faturas")
    contas_pagar = relationship("ContaPagar", back_populates="fatura")
