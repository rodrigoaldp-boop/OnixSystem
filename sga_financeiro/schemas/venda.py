"""Schemas para vendas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VendaItemCreate(BaseModel):
    produto_id: int
    quantidade: Decimal = Field(gt=0)
    valor_unitario: Optional[Decimal] = None
    desconto: Decimal = Decimal("0")


class VendaCreate(BaseModel):
    cliente_id: Optional[int] = None
    vendedor_id: Optional[int] = None
    observacao: Optional[str] = None
    valor_frete: Decimal = Decimal("0")
    prazo_pagamento: Optional[str] = None
    condicao_pagamento_id: Optional[int] = None
    itens: list[VendaItemCreate]


class VendaUpdate(VendaCreate):
    """Mesmos campos de criacao para substituir o pedido inteiro."""

    pass


class VendaItemOut(BaseModel):
    id: int
    produto_id: int
    quantidade: Decimal
    valor_unitario: Decimal
    desconto: Decimal
    total_item: Decimal

    model_config = ConfigDict(from_attributes=True)


class VendaOut(BaseModel):
    id: int
    numero: str
    cliente_id: Optional[int] = None
    vendedor_id: Optional[int] = None
    observacao: Optional[str] = None
    valor_frete: Decimal = Decimal("0")
    prazo_pagamento: Optional[str] = None
    condicao_pagamento_id: Optional[int] = None
    condicao_pagamento_nome: Optional[str] = None
    total_bruto: Decimal
    total_desconto: Decimal
    total_liquido: Decimal
    financeiro_gerado: bool = False
    nfse_gerada: bool = False
    nfe_gerada: bool = False
    created_at: datetime
    itens: list[VendaItemOut]

    model_config = ConfigDict(from_attributes=True)
