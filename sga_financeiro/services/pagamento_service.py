"""Regras de negocio para baixa de contas e pagamento de fatura."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, extract, or_, select
from sqlalchemy.orm import Session

from sga_financeiro.models.cartao_credito import CartaoCredito
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.conta_pagar import ContaPagar, StatusContaPagar
from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.models.fatura_cartao import FaturaCartao, StatusFatura
from sga_financeiro.services.conta_service import creditar_conta, debitar_conta


def _ultimo_dia_mes(year: int, month: int) -> int:
    if month == 12:
        primeiro_proximo_mes = date(year + 1, 1, 1)
    else:
        primeiro_proximo_mes = date(year, month + 1, 1)
    return (primeiro_proximo_mes - timedelta(days=1)).day


def _data_com_dia_seguro(year: int, month: int, dia: int) -> date:
    ultimo = _ultimo_dia_mes(year, month)
    return date(year, month, min(dia, ultimo))


def data_vencimento_prevista_fatura(mes_referencia: str, dia_vencimento_cartao: int) -> date:
    """Data em que a fatura costuma vencer: mes seguinte ao mes de referencia, no dia do cartao."""
    parts = mes_referencia.strip().split("/")
    if len(parts) != 2:
        raise ValueError("mes_referencia invalido")
    m, y = int(parts[0]), int(parts[1])
    if m == 12:
        m2, y2 = 1, y + 1
    else:
        m2, y2 = m + 1, y
    return _data_com_dia_seguro(y2, m2, dia_vencimento_cartao)


def primeiro_vencimento_fatura_cartao(data_compra: date, dia_fechamento: int, dia_vencimento: int) -> date:
    """Ate o dia de fechamento (inclusive): 1a parcela no dia de vencimento do mesmo mes. Depois do fechamento: mesmo dia no mes seguinte."""
    y, m = data_compra.year, data_compra.month
    if data_compra.day > dia_fechamento:
        m += 1
        if m > 12:
            m = 1
            y += 1
    return _data_com_dia_seguro(y, m, dia_vencimento)


def baixar_conta_pagar(
    db: Session,
    conta_pagar: ContaPagar,
    conta_corrente: ContaCorrente,
    data_pagamento: Optional[date] = None,
    comprovante_url: Optional[str] = None,
) -> ContaPagar:
    """Marca conta a pagar como paga e registra debito pendente de conciliacao."""
    if conta_pagar.status == StatusContaPagar.PAGO:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conta ja esta paga.")

    debitar_conta(
        db=db,
        conta=conta_corrente,
        valor=conta_pagar.valor,
        descricao=f"Pagamento: {conta_pagar.descricao}",
        referencia=f"conta_pagar:{conta_pagar.id}",
        conciliar_imediatamente=False,
    )
    conta_pagar.status = StatusContaPagar.PAGO
    conta_pagar.data_pagamento = data_pagamento or date.today()
    conta_pagar.conta_destino_id = conta_corrente.id
    if comprovante_url is not None:
        conta_pagar.comprovante_url = comprovante_url
    return conta_pagar


def receber_conta_receber(
    db: Session,
    conta_receber: ContaReceber,
    conta_corrente: ContaCorrente,
    data_recebimento: Optional[date] = None,
    comprovante_url: Optional[str] = None,
) -> ContaReceber:
    """Marca conta a receber como recebida e registra credito pendente de conciliacao."""
    if conta_receber.status == StatusContaReceber.RECEBIDO:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conta ja foi recebida.")

    creditar_conta(
        db=db,
        conta=conta_corrente,
        valor=conta_receber.valor,
        descricao=f"Recebimento: {conta_receber.descricao}",
        referencia=f"conta_receber:{conta_receber.id}",
        conciliar_imediatamente=False,
    )
    conta_receber.status = StatusContaReceber.RECEBIDO
    conta_receber.data_recebimento = data_recebimento or date.today()
    conta_receber.conta_destino_id = conta_corrente.id
    if comprovante_url is not None:
        conta_receber.comprovante_url = comprovante_url
    return conta_receber


def obter_ou_criar_fatura(db: Session, cartao: CartaoCredito, referencia: date) -> FaturaCartao:
    """Cria uma fatura aberta do mes se ela nao existir."""
    mes_referencia = referencia.strftime("%m/%Y")
    fatura = db.execute(
        select(FaturaCartao).where(
            FaturaCartao.cartao_id == cartao.id,
            FaturaCartao.mes_referencia == mes_referencia,
        )
    ).scalar_one_or_none()
    if fatura:
        return fatura

    dia_f = min(cartao.data_fechamento, _ultimo_dia_mes(referencia.year, referencia.month))
    fatura = FaturaCartao(
        cartao_id=cartao.id,
        mes_referencia=mes_referencia,
        data_fechamento=date(referencia.year, referencia.month, dia_f),
        valor_total=0,
        status=StatusFatura.ABERTA,
    )
    db.add(fatura)
    db.flush()
    return fatura


def adicionar_lancamento_no_cartao(db: Session, conta_pagar: ContaPagar, cartao: CartaoCredito) -> None:
    """Acumula saldo usado do cartao e valor da fatura."""
    fatura = obter_ou_criar_fatura(db, cartao, conta_pagar.data_vencimento)
    conta_pagar.fatura_id = fatura.id
    cartao.saldo_usado += conta_pagar.valor
    fatura.valor_total += conta_pagar.valor


def pagar_fatura(
    db: Session,
    fatura: FaturaCartao,
    conta_corrente: ContaCorrente,
    data_pagamento: Optional[date] = None,
) -> FaturaCartao:
    """Paga fatura do cartao, debita conta e baixa contas vinculadas do mesmo mes."""
    if fatura.status == StatusFatura.PAGA:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fatura ja esta paga.")

    debitar_conta(
        db=db,
        conta=conta_corrente,
        valor=fatura.valor_total,
        descricao=f"Pagamento fatura cartao {fatura.cartao_id} - {fatura.mes_referencia}",
        referencia=f"fatura:{fatura.id}",
    )

    month, year = fatura.mes_referencia.split("/")
    contas = db.execute(
        select(ContaPagar).where(
            ContaPagar.cartao_id == fatura.cartao_id,
            ContaPagar.status.in_([StatusContaPagar.PENDENTE, StatusContaPagar.VENCIDO]),
            or_(
                ContaPagar.fatura_id == fatura.id,
                and_(
                    ContaPagar.fatura_id.is_(None),
                    extract("month", ContaPagar.data_vencimento) == int(month),
                    extract("year", ContaPagar.data_vencimento) == int(year),
                ),
            ),
        )
    ).scalars()
    for conta in contas:
        conta.status = StatusContaPagar.PAGO
        conta.data_pagamento = data_pagamento or date.today()
        conta.conta_destino_id = conta_corrente.id

    cartao = db.get(CartaoCredito, fatura.cartao_id)
    if cartao:
        cartao.saldo_usado -= fatura.valor_total
        if cartao.saldo_usado < 0:
            cartao.saldo_usado = 0

    fatura.status = StatusFatura.PAGA
    fatura.data_pagamento = data_pagamento or date.today()
    return fatura


def listar_contas_vinculadas_fatura(db: Session, fatura: FaturaCartao) -> list[ContaPagar]:
    """Todos os lancamentos no cartao ligados a esta fatura (por fatura_id ou mes de vencimento)."""
    month, year = fatura.mes_referencia.split("/")
    rows = db.execute(
        select(ContaPagar)
        .where(
            ContaPagar.cartao_id == fatura.cartao_id,
            or_(
                ContaPagar.fatura_id == fatura.id,
                and_(
                    ContaPagar.fatura_id.is_(None),
                    extract("month", ContaPagar.data_vencimento) == int(month),
                    extract("year", ContaPagar.data_vencimento) == int(year),
                ),
            ),
        )
        .order_by(ContaPagar.data_vencimento.asc(), ContaPagar.id.asc())
    ).scalars()
    return list(rows)
