"""Schemas para grupo de contas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GrupoContaBase(BaseModel):
    nome: str


class GrupoContaCreate(GrupoContaBase):
    pass


class GrupoContaUpdate(GrupoContaBase):
    pass


class GrupoContaOut(GrupoContaBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
