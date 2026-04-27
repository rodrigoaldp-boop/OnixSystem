"""Schemas de cliente."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class ClienteBase(BaseModel):
    nome: str
    cnpj_cpf: Optional[str] = None
    email: Optional[EmailStr] = None
    telefone: Optional[str] = None
    endereco: Optional[str] = None
    limite_credito: Decimal = Decimal("0.00")
    ativa: bool = True


class ClienteCreate(ClienteBase):
    pass


class ClienteUpdate(BaseModel):
    nome: Optional[str] = None
    cnpj_cpf: Optional[str] = None
    email: Optional[EmailStr] = None
    telefone: Optional[str] = None
    endereco: Optional[str] = None
    limite_credito: Optional[Decimal] = None
    ativa: Optional[bool] = None


class ClienteOut(ClienteBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
