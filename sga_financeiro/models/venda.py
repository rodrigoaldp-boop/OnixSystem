"""Model ORM de vendas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class Venda(Base):
    __tablename__ = "vendas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    numero: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    cliente_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cadastros_gerais.id"), nullable=True)
    vendedor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cadastros_gerais.id"), nullable=True)
    observacao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    valor_frete: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    prazo_pagamento: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    condicao_pagamento_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("condicoes_pagamento.id"), nullable=True, index=True
    )
    total_bruto: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total_desconto: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total_liquido: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    financeiro_gerado: Mapped[bool] = mapped_column(default=False, nullable=False)
    nfse_gerada: Mapped[bool] = mapped_column(default=False, nullable=False)
    nfe_gerada: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    itens = relationship("VendaItem", back_populates="venda", cascade="all, delete-orphan")
    condicao_pag_catalogo = relationship("CondicaoPagamento", back_populates="vendas")
