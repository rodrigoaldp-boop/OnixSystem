"""Schemas de condicoes de pagamento."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CondicaoPagamentoCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=100)


class CondicaoPagamentoUpdate(BaseModel):
    nome: str = Field(min_length=1, max_length=100)


class CondicaoPagamentoOut(BaseModel):
    id: int
    nome: str

    model_config = ConfigDict(from_attributes=True)
