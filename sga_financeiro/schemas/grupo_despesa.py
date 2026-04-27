"""Schemas para grupo de despesas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GrupoDespesaBase(BaseModel):
    nome: str


class GrupoDespesaCreate(GrupoDespesaBase):
    pass


class GrupoDespesaUpdate(GrupoDespesaBase):
    pass


class GrupoDespesaOut(GrupoDespesaBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
