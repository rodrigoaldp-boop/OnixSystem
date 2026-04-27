"""Schemas de contas a receber."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from sga_financeiro.models.conta_receber import StatusContaReceber


class ContaReceberBase(BaseModel):
    descricao: str
    valor: Decimal
    categoria_id: int
    centro_custos_id: int
    cliente_id: Optional[int] = None
    conta_destino_id: Optional[int] = None
    data_vencimento: date
    comprovante_url: Optional[str] = None


class ContaReceberCreate(ContaReceberBase):
    status: StatusContaReceber = StatusContaReceber.PENDENTE
    data_recebimento: Optional[date] = None


class ContaReceberUpdate(BaseModel):
    descricao: Optional[str] = None
    valor: Optional[Decimal] = None
    categoria_id: Optional[int] = None
    centro_custos_id: Optional[int] = None
    cliente_id: Optional[int] = None
    conta_destino_id: Optional[int] = None
    data_vencimento: Optional[date] = None
    status: Optional[StatusContaReceber] = None
    comprovante_url: Optional[str] = None


class ContaReceberBaixa(BaseModel):
    conta_destino_id: int
    data_recebimento: Optional[date] = None
    comprovante_url: Optional[str] = None


class ContaReceberOut(ContaReceberBase):
    id: int
    data_recebimento: Optional[date] = None
    status: StatusContaReceber
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
