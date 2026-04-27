"""Cadastro de condicoes de pagamento (PIX, Boleto, etc.)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base

if TYPE_CHECKING:
    from sga_financeiro.models.venda import Venda


class CondicaoPagamento(Base):
    __tablename__ = "condicoes_pagamento"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)

    vendas = relationship("Venda", back_populates="condicao_pag_catalogo")
