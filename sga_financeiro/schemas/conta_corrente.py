"""Schemas de conta corrente."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ContaCorrenteBase(BaseModel):
    banco: str
    agencia: str
    numero: str
    nome_conta: str = ""
    saldo_atual: Decimal = Decimal("0.00")
    ativa: bool = True


class ContaCorrenteCreate(ContaCorrenteBase):
    pass


class ContaCorrenteUpdate(BaseModel):
    banco: Optional[str] = None
    agencia: Optional[str] = None
    numero: Optional[str] = None
    nome_conta: Optional[str] = None
    saldo_atual: Optional[Decimal] = None
    ativa: Optional[bool] = None


class ContaCorrenteOut(ContaCorrenteBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransferenciaContaCreate(BaseModel):
    conta_origem_id: int
    conta_destino_id: int
    valor: Decimal = Field(gt=0)
    motivo: str
