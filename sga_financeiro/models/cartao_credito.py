"""Model ORM para cartoes de credito."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sga_financeiro.database import Base


class CartaoCredito(Base):
    __tablename__ = "cartoes_credito"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    banco: Mapped[str] = mapped_column(String(120), nullable=False)
    nome_conta: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    ultimos_digitos: Mapped[str] = mapped_column(String(4), nullable=False)
    data_fechamento: Mapped[int] = mapped_column(Integer, nullable=False)
    data_vencimento: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    limite: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    saldo_usado: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    contas_pagar = relationship("ContaPagar", back_populates="cartao")
    faturas = relationship("FaturaCartao", back_populates="cartao")
