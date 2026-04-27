"""Schemas para subgrupo de contas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SubgrupoContaBase(BaseModel):
    nome: str
    grupo_conta_id: int


class SubgrupoContaCreate(SubgrupoContaBase):
    pass


class SubgrupoContaUpdate(SubgrupoContaBase):
    pass


class SubgrupoContaOut(SubgrupoContaBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
