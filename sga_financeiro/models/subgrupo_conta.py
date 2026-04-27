"""Model ORM para subgrupo de contas."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class SubgrupoConta(Base):
    __tablename__ = "subgrupos_contas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    grupo_conta_id: Mapped[int] = mapped_column(ForeignKey("grupos_contas.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    grupo_conta = relationship("GrupoConta", back_populates="subgrupos")
