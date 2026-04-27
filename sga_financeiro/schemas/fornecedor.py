"""Schemas de fornecedor."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class FornecedorBase(BaseModel):
    nome: str
    cnpj_cpf: Optional[str] = None
    email: Optional[EmailStr] = None
    telefone: Optional[str] = None
    endereco: Optional[str] = None
    banco: Optional[str] = None
    agencia: Optional[str] = None
    conta: Optional[str] = None
    limite_credito: Decimal = Decimal("0.00")
    ativa: bool = True


class FornecedorCreate(FornecedorBase):
    pass


class FornecedorUpdate(BaseModel):
    nome: Optional[str] = None
    cnpj_cpf: Optional[str] = None
    email: Optional[EmailStr] = None
    telefone: Optional[str] = None
    endereco: Optional[str] = None
    banco: Optional[str] = None
    agencia: Optional[str] = None
    conta: Optional[str] = None
    limite_credito: Optional[Decimal] = None
    ativa: Optional[bool] = None


class FornecedorOut(FornecedorBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
