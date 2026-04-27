"""Schemas para produtos."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ProdutoBase(BaseModel):
    nome: str
    categoria_produto_id: int = Field(..., gt=0)
    sku: Optional[str] = None
    is_servico: bool = False
    unidade: str = "UN"
    preco_custo: Decimal = Decimal("0")
    preco_venda: Decimal = Decimal("0")
    ncm: Optional[str] = None
    cest: Optional[str] = None
    cfop_compra: Optional[str] = None
    cfop_venda: Optional[str] = None
    csosn: Optional[str] = None
    aliquota_icms_entrada: Decimal = Decimal("0")
    aliquota_icms_saida: Decimal = Decimal("0")
    descricao: Optional[str] = None
    ativa: bool = True


class ProdutoCreate(ProdutoBase):
    pass


class ProdutoUpdate(BaseModel):
    nome: Optional[str] = None
    categoria_produto_id: Optional[int] = None
    sku: Optional[str] = None
    is_servico: Optional[bool] = None
    unidade: Optional[str] = None
    preco_custo: Optional[Decimal] = None
    preco_venda: Optional[Decimal] = None
    ncm: Optional[str] = None
    cest: Optional[str] = None
    cfop_compra: Optional[str] = None
    cfop_venda: Optional[str] = None
    csosn: Optional[str] = None
    aliquota_icms_entrada: Optional[Decimal] = None
    aliquota_icms_saida: Optional[Decimal] = None
    descricao: Optional[str] = None
    ativa: Optional[bool] = None


class ProdutoOut(ProdutoBase):
    id: int
    categoria_nome: str = ""
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
