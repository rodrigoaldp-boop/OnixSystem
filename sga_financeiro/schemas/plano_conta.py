"""Schemas para plano de contas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlanoContaBase(BaseModel):
    nome: str


class PlanoContaCreate(PlanoContaBase):
    pass


class PlanoContaUpdate(PlanoContaBase):
    pass


class PlanoContaOut(PlanoContaBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
