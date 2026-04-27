"""Schemas para cadastro geral."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class CadastroGeralBase(BaseModel):
    cnpj: str
    contexto: str = "pessoas"
    razao_social: str
    cidade_uf: Optional[str] = None
    nome_fantasia: Optional[str] = None
    endereco: str
    telefone: str
    cep: str
    is_cliente: bool = False
    is_funcionario: bool = False
    is_fornecedor: bool = False
    is_vendedor: bool = False
    chave_pix: Optional[str] = None
    vendedor_comissionado: bool = False


class CadastroGeralCreate(CadastroGeralBase):
    pass


class CadastroGeralUpdate(CadastroGeralBase):
    pass


class CnpjConsultaOut(BaseModel):
    cnpj: str
    razao_social: str
    cidade_uf: Optional[str] = None
    nome_fantasia: Optional[str] = None
    endereco: str
    telefone: Optional[str] = None
    cep: Optional[str] = None


class CadastroGeralOut(CadastroGeralBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
