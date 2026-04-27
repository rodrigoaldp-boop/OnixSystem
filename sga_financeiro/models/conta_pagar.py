"""Model ORM para contas a pagar."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Date, DateTime, Enum as SqlEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class StatusContaPagar(str, Enum):
    PENDENTE = "pendente"
    PAGO = "pago"
    VENCIDO = "vencido"


class ContaPagar(Base):
    __tablename__ = "contas_pagar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    descricao: Mapped[str] = mapped_column(String(200), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"), nullable=False)
    centro_custos_id: Mapped[int] = mapped_column(ForeignKey("centros_custos.id"), nullable=False)
    fornecedor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("fornecedores.id"), nullable=True)
    conta_destino_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contas_correntes.id"), nullable=True)
    cartao_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cartoes_credito.id"), nullable=True)
    fatura_id: Mapped[Optional[int]] = mapped_column(ForeignKey("faturas_cartao.id"), nullable=True)
    data_vencimento: Mapped[date] = mapped_column(Date, nullable=False)
    data_pagamento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[StatusContaPagar] = mapped_column(SqlEnum(StatusContaPagar), default=StatusContaPagar.PENDENTE, nullable=False)
    comprovante_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    categoria = relationship("Categoria", back_populates="contas_pagar")
    centro_custos = relationship("CentroCustos", back_populates="contas_pagar")
    fornecedor = relationship("Fornecedor", back_populates="contas_pagar")
    conta_destino = relationship("ContaCorrente", back_populates="contas_pagar")
    cartao = relationship("CartaoCredito", back_populates="contas_pagar")
    fatura = relationship("FaturaCartao", back_populates="contas_pagar")
