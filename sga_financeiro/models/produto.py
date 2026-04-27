"""Model ORM para produtos e servicos."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class Produto(Base):
    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    categoria_produto_id: Mapped[int] = mapped_column(
        ForeignKey("categorias_produto.id"),
        nullable=False,
        index=True,
    )
    nome: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    sku: Mapped[Optional[str]] = mapped_column(String(60), nullable=True, unique=True, index=True)
    is_servico: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    unidade: Mapped[str] = mapped_column(String(20), default="UN", nullable=False)
    preco_custo: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    preco_venda: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    ncm: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cest: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cfop_compra: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    cfop_venda: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    csosn: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    aliquota_icms_entrada: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    aliquota_icms_saida: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    descricao: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    categoria_produto = relationship("CategoriaProduto", back_populates="produtos")
    itens_venda = relationship("VendaItem", back_populates="produto")
