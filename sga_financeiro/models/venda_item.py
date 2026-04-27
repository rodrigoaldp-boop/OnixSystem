"""Model ORM de itens da venda."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class VendaItem(Base):
    __tablename__ = "vendas_itens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    venda_id: Mapped[int] = mapped_column(ForeignKey("vendas.id"), nullable=False, index=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), nullable=False)
    quantidade: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    valor_unitario: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    desconto: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total_item: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    venda = relationship("Venda", back_populates="itens")
    produto = relationship("Produto", back_populates="itens_venda")
