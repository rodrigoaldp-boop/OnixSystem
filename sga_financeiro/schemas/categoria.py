"""Schemas de categoria."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from sga_financeiro.models.categoria import TipoCategoria


class CategoriaBase(BaseModel):
    nome: str
    tipo: TipoCategoria
    descricao: Optional[str] = None
    cor: Optional[str] = None
    ativa: bool = True


class CategoriaCreate(CategoriaBase):
    pass


class CategoriaUpdate(BaseModel):
    nome: Optional[str] = None
    tipo: Optional[TipoCategoria] = None
    descricao: Optional[str] = None
    cor: Optional[str] = None
    ativa: Optional[bool] = None


class CategoriaOut(CategoriaBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
