"""Schemas de cartao de credito e fatura."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sga_financeiro.models.conta_pagar import StatusContaPagar
from sga_financeiro.models.fatura_cartao import StatusFatura


class CartaoCreditoBase(BaseModel):
    banco: str
    nome_conta: str = ""
    ultimos_digitos: str = Field(default="0000", min_length=4, max_length=4)
    data_fechamento: int = Field(ge=1, le=31)
    data_vencimento: int = Field(default=10, ge=1, le=31)
    limite: Decimal
    saldo_usado: Decimal = Decimal("0.00")
    ativa: bool = True


class CartaoCreditoCreate(CartaoCreditoBase):
    pass


class CartaoCreditoUpdate(BaseModel):
    banco: Optional[str] = None
    nome_conta: Optional[str] = None
    ultimos_digitos: Optional[str] = Field(default=None, min_length=4, max_length=4)
    data_fechamento: Optional[int] = Field(default=None, ge=1, le=31)
    data_vencimento: Optional[int] = Field(default=None, ge=1, le=31)
    limite: Optional[Decimal] = None
    saldo_usado: Optional[Decimal] = None
    ativa: Optional[bool] = None


class CartaoCreditoOut(CartaoCreditoBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FaturaCartaoOut(BaseModel):
    id: int
    cartao_id: int
    mes_referencia: str
    data_fechamento: date
    valor_total: Decimal
    status: StatusFatura
    data_pagamento: Optional[date] = None
    created_at: datetime
    data_vencimento_prevista: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class LancamentoFaturaItem(BaseModel):
    id: int
    descricao: str
    valor: Decimal
    status: StatusContaPagar
    data_vencimento: date

    model_config = ConfigDict(from_attributes=True)


class FaturaCartaoDetalheOut(BaseModel):
    fatura: FaturaCartaoOut
    nome_cartao: str
    lancamentos: list[LancamentoFaturaItem]
