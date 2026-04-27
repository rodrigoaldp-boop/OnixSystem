"""Schemas de centro de custos."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CentroCustosBase(BaseModel):
    nome: str
    codigo: str
    descricao: Optional[str] = None
    responsavel: Optional[str] = None
    ativa: bool = True


class CentroCustosCreate(CentroCustosBase):
    pass


class CentroCustosUpdate(BaseModel):
    nome: Optional[str] = None
    codigo: Optional[str] = None
    descricao: Optional[str] = None
    responsavel: Optional[str] = None
    ativa: Optional[bool] = None


class CentroCustosOut(CentroCustosBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
