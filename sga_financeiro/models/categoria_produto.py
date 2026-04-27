"""Categorias de produto (distintas das categorias financeiras)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base

if TYPE_CHECKING:
    from sga_financeiro.models.produto import Produto


class CategoriaProduto(Base):
    __tablename__ = "categorias_produto"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    codigo: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    percentual_comissao: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    produtos: Mapped[list["Produto"]] = relationship("Produto", back_populates="categoria_produto")
