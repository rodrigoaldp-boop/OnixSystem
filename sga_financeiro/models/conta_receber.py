"""Model ORM para contas a receber."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Date, DateTime, Enum as SqlEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class StatusContaReceber(str, Enum):
    PENDENTE = "pendente"
    RECEBIDO = "recebido"
    VENCIDO = "vencido"


class ContaReceber(Base):
    __tablename__ = "contas_receber"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    descricao: Mapped[str] = mapped_column(String(200), nullable=False)
    valor: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"), nullable=False)
    centro_custos_id: Mapped[int] = mapped_column(ForeignKey("centros_custos.id"), nullable=False)
    cliente_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clientes.id"), nullable=True)
    venda_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendas.id"), nullable=True, index=True)
    conta_destino_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contas_correntes.id"), nullable=True)
    data_vencimento: Mapped[date] = mapped_column(Date, nullable=False)
    data_recebimento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[StatusContaReceber] = mapped_column(SqlEnum(StatusContaReceber), default=StatusContaReceber.PENDENTE, nullable=False)
    comissao_gerada: Mapped[bool] = mapped_column(default=False, nullable=False)
    comprovante_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    categoria = relationship("Categoria", back_populates="contas_receber")
    centro_custos = relationship("CentroCustos", back_populates="contas_receber")
    cliente = relationship("Cliente", back_populates="contas_receber")
    conta_destino = relationship("ContaCorrente", back_populates="contas_receber")
