"""Servicos relacionados a saldo e movimentacoes bancarias."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.movimentacao import Movimentacao, TipoMovimentacao


def creditar_conta(
    db: Session,
    conta: ContaCorrente,
    valor: Decimal,
    descricao: str,
    referencia: Optional[str] = None,
    conciliar_imediatamente: bool = True,
) -> None:
    """Credita valor e registra movimentacao (imediata ou pendente)."""
    if conciliar_imediatamente:
        conta.saldo_atual += valor
    db.add(
        Movimentacao(
            tipo=TipoMovimentacao.CREDITO,
            conta_id=conta.id,
            valor=valor,
            descricao=descricao,
            referencia=referencia,
            conciliado=conciliar_imediatamente,
            data_conciliacao=datetime.utcnow() if conciliar_imediatamente else None,
        )
    )


def debitar_conta(
    db: Session,
    conta: ContaCorrente,
    valor: Decimal,
    descricao: str,
    referencia: Optional[str] = None,
    conciliar_imediatamente: bool = True,
) -> None:
    """Debita valor e registra movimentacao (imediata ou pendente)."""
    if conciliar_imediatamente:
        conta.saldo_atual -= valor
    db.add(
        Movimentacao(
            tipo=TipoMovimentacao.DEBITO,
            conta_id=conta.id,
            valor=valor,
            descricao=descricao,
            referencia=referencia,
            conciliado=conciliar_imediatamente,
            data_conciliacao=datetime.utcnow() if conciliar_imediatamente else None,
        )
    )
