"""Servicos de dashboard e relatorios consolidados."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sga_financeiro.models.categoria import Categoria
from sga_financeiro.models.centro_custos import CentroCustos
from sga_financeiro.models.cliente import Cliente
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.conta_pagar import ContaPagar
from sga_financeiro.models.conta_receber import ContaReceber
from sga_financeiro.models.fornecedor import Fornecedor
from sga_financeiro.models.movimentacao import Movimentacao


def resumo_dashboard(db: Session) -> dict:
    """Retorna indicadores de saldo e ultimas movimentacoes."""
    saldo_total = db.execute(select(func.coalesce(func.sum(ContaCorrente.saldo_atual), 0))).scalar_one()
    ultimas = db.execute(select(Movimentacao).order_by(Movimentacao.data_movimento.desc()).limit(10)).scalars().all()

    categorias = db.execute(
        select(Categoria.nome, func.coalesce(func.sum(ContaPagar.valor), 0))
        .join(ContaPagar, ContaPagar.categoria_id == Categoria.id)
        .group_by(Categoria.nome)
    ).all()
    return {
        "saldo_total": saldo_total,
        "ultimos_lancamentos": ultimas,
        "total_por_categoria": [{"categoria": nome, "total": total} for nome, total in categorias],
    }


def total_por_centro_custos(db: Session) -> list[dict]:
    rows = db.execute(
        select(CentroCustos.nome, func.coalesce(func.sum(ContaPagar.valor), 0))
        .join(ContaPagar, ContaPagar.centro_custos_id == CentroCustos.id)
        .group_by(CentroCustos.nome)
    ).all()
    return [{"centro_custos": nome, "total": total} for nome, total in rows]


def total_por_parte(db: Session) -> dict:
    fornecedores = db.execute(
        select(Fornecedor.nome, func.coalesce(func.sum(ContaPagar.valor), 0))
        .join(ContaPagar, ContaPagar.fornecedor_id == Fornecedor.id)
        .group_by(Fornecedor.nome)
    ).all()
    clientes = db.execute(
        select(Cliente.nome, func.coalesce(func.sum(ContaReceber.valor), 0))
        .join(ContaReceber, ContaReceber.cliente_id == Cliente.id)
        .group_by(Cliente.nome)
    ).all()
    return {
        "fornecedores": [{"nome": nome, "total": total} for nome, total in fornecedores],
        "clientes": [{"nome": nome, "total": total} for nome, total in clientes],
    }


def fluxo_caixa(db: Session, data_inicio: date, data_fim: date) -> dict:
    """Consolida entradas e saidas no intervalo."""
    entradas = db.execute(
        select(func.coalesce(func.sum(ContaReceber.valor), 0)).where(
            ContaReceber.data_recebimento >= data_inicio,
            ContaReceber.data_recebimento <= data_fim,
        )
    ).scalar_one()
    saidas = db.execute(
        select(func.coalesce(func.sum(ContaPagar.valor), 0)).where(
            ContaPagar.data_pagamento >= data_inicio,
            ContaPagar.data_pagamento <= data_fim,
        )
    ).scalar_one()
    saldo = Decimal(entradas) - Decimal(saidas)
    return {"data_inicio": data_inicio, "data_fim": data_fim, "entradas": entradas, "saidas": saidas, "saldo": saldo}
