"""Remove registros financeiros ja liquidados e movimentacoes vinculadas."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from sga_financeiro.models.cartao_credito import CartaoCredito
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.conta_pagar import ContaPagar, StatusContaPagar
from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.models.fatura_cartao import FaturaCartao, StatusFatura
from sga_financeiro.models.movimentacao import Movimentacao, TipoMovimentacao


def _refs_para_movimentos(db: Session) -> list[str]:
    ids_pagar = db.execute(select(ContaPagar.id).where(ContaPagar.status == StatusContaPagar.PAGO)).scalars().all()
    ids_receber = db.execute(select(ContaReceber.id).where(ContaReceber.status == StatusContaReceber.RECEBIDO)).scalars().all()
    ids_fatura = db.execute(select(FaturaCartao.id).where(FaturaCartao.status == StatusFatura.PAGA)).scalars().all()
    refs: list[str] = []
    refs.extend(f"conta_pagar:{i}" for i in ids_pagar)
    refs.extend(f"conta_receber:{i}" for i in ids_receber)
    refs.extend(f"fatura:{i}" for i in ids_fatura)
    return refs


def _remover_movimentacoes_vinculadas(db: Session, refs: list[str]) -> tuple[int, int]:
    """Remove movimentacoes cuja referencia corresponde aos registros liquidados.
    Retorna (total_removidas, reversões_de_saldo_aplicadas)."""
    if not refs:
        return 0, 0
    movs = db.execute(select(Movimentacao).where(Movimentacao.referencia.in_(refs))).scalars().all()
    revertidas = 0
    for mov in movs:
        if mov.conciliado:
            conta = db.get(ContaCorrente, mov.conta_id)
            if conta is not None:
                if mov.tipo == TipoMovimentacao.DEBITO:
                    conta.saldo_atual += mov.valor
                else:
                    conta.saldo_atual -= mov.valor
                revertidas += 1
        db.delete(mov)
    return len(movs), revertidas


def _recalcular_saldo_usado_cartoes(db: Session) -> None:
    cartoes = db.execute(select(CartaoCredito)).scalars().all()
    for cartao in cartoes:
        total = db.execute(
            select(func.coalesce(func.sum(ContaPagar.valor), 0)).where(
                ContaPagar.cartao_id == cartao.id,
                ContaPagar.status.in_([StatusContaPagar.PENDENTE, StatusContaPagar.VENCIDO]),
            )
        ).scalar_one()
        cartao.saldo_usado = Decimal(str(total)) if total is not None else Decimal("0")


def excluir_historicos_liquidados(db: Session) -> dict[str, Any]:
    """Apaga contas a pagar pagas, contas a receber recebidas e faturas de cartao pagas,
    removendo antes as movimentacoes bancarias com referencia associada (revertendo saldo se conciliado)."""
    refs = _refs_para_movimentos(db)
    mov_rem, saldo_rev = _remover_movimentacoes_vinculadas(db, refs)

    r_pagar = db.execute(delete(ContaPagar).where(ContaPagar.status == StatusContaPagar.PAGO))
    n_pagar = r_pagar.rowcount if r_pagar.rowcount is not None else 0

    sub_pagas = select(FaturaCartao.id).where(FaturaCartao.status == StatusFatura.PAGA)
    db.execute(update(ContaPagar).where(ContaPagar.fatura_id.in_(sub_pagas)).values(fatura_id=None))

    r_receber = db.execute(delete(ContaReceber).where(ContaReceber.status == StatusContaReceber.RECEBIDO))
    n_receber = r_receber.rowcount if r_receber.rowcount is not None else 0

    r_fat = db.execute(delete(FaturaCartao).where(FaturaCartao.status == StatusFatura.PAGA))
    n_fat = r_fat.rowcount if r_fat.rowcount is not None else 0

    _recalcular_saldo_usado_cartoes(db)

    return {
        "contas_pagar_excluidas": n_pagar,
        "contas_receber_excluidas": n_receber,
        "faturas_cartao_excluidas": n_fat,
        "movimentacoes_excluidas": mov_rem,
        "movimentacoes_saldo_revertido": saldo_rev,
    }


def excluir_fatura_paga(db: Session, fatura_id: int) -> dict[str, Any]:
    """Remove apenas o registro da fatura paga. Nao estorna banco, cartao nem lancamentos."""
    fatura = db.get(FaturaCartao, fatura_id)
    if not fatura:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fatura nao encontrada.")
    if fatura.status != StatusFatura.PAGA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="So e possivel excluir fatura com status PAGA.",
        )

    db.execute(update(ContaPagar).where(ContaPagar.fatura_id == fatura_id).values(fatura_id=None))
    db.delete(fatura)

    return {
        "status": "ok",
        "fatura_id": fatura_id,
        "mensagem": "Registro da fatura removido. Lancamentos e movimentacoes bancarias nao foram alterados.",
    }
