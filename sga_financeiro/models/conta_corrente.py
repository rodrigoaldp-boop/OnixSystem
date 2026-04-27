"""Model ORM para contas correntes bancarias."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class ContaCorrente(Base):
    __tablename__ = "contas_correntes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    banco: Mapped[str] = mapped_column(String(120), nullable=False)
    agencia: Mapped[str] = mapped_column(String(20), nullable=False)
    numero: Mapped[str] = mapped_column(String(30), nullable=False)
    nome_conta: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    saldo_atual: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    contas_pagar = relationship("ContaPagar", back_populates="conta_destino")
    contas_receber = relationship("ContaReceber", back_populates="conta_destino")
    movimentacoes = relationship("Movimentacao", back_populates="conta")
