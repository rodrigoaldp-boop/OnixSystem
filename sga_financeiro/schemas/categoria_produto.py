"""Schemas de categorias de produto."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoriaProdutoOut(BaseModel):
    id: int
    codigo: str
    nome: str
    percentual_comissao: Decimal = Field(default=Decimal("0"))
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoriaProdutoUpdate(BaseModel):
    nome: Optional[str] = Field(None, max_length=120)
    percentual_comissao: Optional[Decimal] = None
