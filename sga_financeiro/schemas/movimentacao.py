"""Schemas de movimentacao bancaria."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sga_financeiro.models.movimentacao import TipoMovimentacao


class MovimentacaoOut(BaseModel):
    id: int
    tipo: TipoMovimentacao
    conta_id: int
    valor: Decimal
    descricao: str
    referencia: Optional[str] = None
    data_movimento: datetime
    conciliado: bool
    data_conciliacao: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MovimentacaoPendenteOut(BaseModel):
    id: int
    tipo: TipoMovimentacao
    conta_id: int
    conta_nome: str
    valor: Decimal
    descricao: str
    referencia: Optional[str] = None
    data_movimento: datetime


class ConciliarMovimentacoesIn(BaseModel):
    ids: list[int] = Field(min_length=1)
