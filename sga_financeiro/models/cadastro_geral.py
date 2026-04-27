"""Model ORM para cadastro geral de pessoas/empresas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from sga_financeiro.database import Base


class CadastroGeral(Base):
    __tablename__ = "cadastros_gerais"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cnpj: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    contexto: Mapped[str] = mapped_column(String(20), default="pessoas", nullable=False, index=True)
    razao_social: Mapped[str] = mapped_column(String(180), nullable=False)
    cidade_uf: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    nome_fantasia: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    endereco: Mapped[str] = mapped_column(Text, nullable=False)
    telefone: Mapped[str] = mapped_column(String(30), nullable=False)
    cep: Mapped[str] = mapped_column(String(12), nullable=False)
    is_cliente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_funcionario: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_fornecedor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_vendedor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    chave_pix: Mapped[Optional[str]] = mapped_column(String(180), nullable=True)
    vendedor_comissionado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
