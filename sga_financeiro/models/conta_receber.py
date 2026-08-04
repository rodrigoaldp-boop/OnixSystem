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
    # Principal original da divida (para multa integral apos recebimento parcial).
    valor_original: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    # Multa congelada (valor integral) apos o primeiro recebimento parcial em atraso.
    multa_fixada: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    # Juros ja corridos ate o ultimo recebimento parcial.
    juros_acumulados: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    # A partir desta data, juros novos incidem so sobre o principal restante (valor).
    juros_apos_data: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    categoria_id: Mapped[int] = mapped_column(ForeignKey("categorias.id"), nullable=False)
    centro_custos_id: Mapped[int] = mapped_column(ForeignKey("centros_custos.id"), nullable=False)
    cliente_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clientes.id"), nullable=True)
    venda_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendas.id"), nullable=True, index=True)
    conta_destino_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contas_correntes.id"), nullable=True)
    data_vencimento: Mapped[date] = mapped_column(Date, nullable=False)
    data_recebimento: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[StatusContaReceber] = mapped_column(SqlEnum(StatusContaReceber), default=StatusContaReceber.PENDENTE, nullable=False)
    comissao_gerada: Mapped[bool] = mapped_column(default=False, nullable=False)
    comissionar_recebimento: Mapped[bool] = mapped_column(default=False, nullable=False)
    comissao_vendedor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cadastros_gerais.id"), nullable=True)
    comissao_percentual: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    comprovante_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asaas_payment_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    asaas_boleto_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asaas_linha_digitavel: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    asaas_status: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    asaas_pix_copia_cola: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asaas_billing_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    boleto_email_enviado_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    boleto_email_destino: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    boleto_email_anexos: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    categoria = relationship("Categoria", back_populates="contas_receber")
    centro_custos = relationship("CentroCustos", back_populates="contas_receber")
    cliente = relationship("Cliente", back_populates="contas_receber")
    conta_destino = relationship("ContaCorrente", back_populates="contas_receber")
