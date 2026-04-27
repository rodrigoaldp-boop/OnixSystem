"""Schemas de contas a pagar."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from sga_financeiro.models.conta_pagar import StatusContaPagar


class ContaPagarBase(BaseModel):
    descricao: str
    valor: Decimal
    categoria_id: int
    centro_custos_id: int
    fornecedor_id: Optional[int] = None
    conta_destino_id: Optional[int] = None
    cartao_id: Optional[int] = None
    data_vencimento: date
    comprovante_url: Optional[str] = None


class ContaPagarCreate(ContaPagarBase):
    status: StatusContaPagar = StatusContaPagar.PENDENTE
    data_pagamento: Optional[date] = None


class ContaPagarUpdate(BaseModel):
    descricao: Optional[str] = None
    valor: Optional[Decimal] = None
    categoria_id: Optional[int] = None
    centro_custos_id: Optional[int] = None
    fornecedor_id: Optional[int] = None
    conta_destino_id: Optional[int] = None
    cartao_id: Optional[int] = None
    data_vencimento: Optional[date] = None
    status: Optional[StatusContaPagar] = None
    comprovante_url: Optional[str] = None


class ContaPagarBaixa(BaseModel):
    conta_destino_id: int
    data_pagamento: Optional[date] = None
    comprovante_url: Optional[str] = None


class ContaPagarOut(ContaPagarBase):
    id: int
    fatura_id: Optional[int] = None
    data_pagamento: Optional[date] = None
    status: StatusContaPagar
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContaPagarListaOut(ContaPagarOut):
    """Resposta enriquecida para telas que mostram vínculo com cartao e fatura."""

    cartao_label: Optional[str] = None
    fatura_mes_referencia: Optional[str] = None
