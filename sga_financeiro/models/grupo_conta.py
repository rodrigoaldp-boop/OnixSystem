"""Model ORM para grupo de contas."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class GrupoConta(Base):
    __tablename__ = "grupos_contas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    subgrupos = relationship("SubgrupoConta", back_populates="grupo_conta")
