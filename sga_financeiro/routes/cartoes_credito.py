"""Endpoints de cartoes de credito e faturas."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from sga_financeiro.database import get_db
from sga_financeiro.models.cartao_credito import CartaoCredito
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.fatura_cartao import FaturaCartao
from sga_financeiro.schemas.cartao_credito import (
    CartaoCreditoCreate,
    CartaoCreditoOut,
    CartaoCreditoUpdate,
    FaturaCartaoDetalheOut,
    FaturaCartaoOut,
    LancamentoFaturaItem,
)
from sga_financeiro.models.conta_pagar import ContaPagar
from sga_financeiro.services.exclusao_historico_service import excluir_fatura_paga
from sga_financeiro.services.pagamento_service import (
    data_vencimento_prevista_fatura,
    listar_contas_vinculadas_fatura,
    pagar_fatura,
)

router = APIRouter(prefix="/cartoes-credito", tags=["Cartoes de Credito"])


def _montar_fatura_out(f: FaturaCartao) -> FaturaCartaoOut:
    cartao = f.cartao
    dia = int(cartao.data_vencimento) if cartao is not None and cartao.data_vencimento is not None else 10
    prev: Optional[date] = None
    try:
        prev = data_vencimento_prevista_fatura(f.mes_referencia, dia)
    except ValueError:
        prev = None
    base = FaturaCartaoOut.model_validate(f).model_dump()
    base["data_vencimento_prevista"] = prev
    return FaturaCartaoOut(**base)


@router.get("", response_model=list[CartaoCreditoOut])
def listar(db: Session = Depends(get_db)) -> list[CartaoCredito]:
    return db.query(CartaoCredito).order_by(CartaoCredito.id.desc()).all()


@router.post("", response_model=CartaoCreditoOut, status_code=status.HTTP_201_CREATED)
def criar(payload: CartaoCreditoCreate, db: Session = Depends(get_db)) -> CartaoCredito:
    item = CartaoCredito(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/faturas", response_model=list[FaturaCartaoOut])
def listar_faturas(db: Session = Depends(get_db)) -> list[FaturaCartaoOut]:
    faturas = (
        db.query(FaturaCartao)
        .options(joinedload(FaturaCartao.cartao))
        .order_by(FaturaCartao.data_fechamento.desc())
        .all()
    )
    return [_montar_fatura_out(f) for f in faturas]


@router.get("/faturas/{fatura_id}/detalhes", response_model=FaturaCartaoDetalheOut)
def detalhes_fatura(fatura_id: int, db: Session = Depends(get_db)) -> FaturaCartaoDetalheOut:
    fatura = (
        db.execute(select(FaturaCartao).where(FaturaCartao.id == fatura_id).options(joinedload(FaturaCartao.cartao)))
        .scalar_one_or_none()
    )
    if not fatura:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fatura nao encontrada.")
    cartao = fatura.cartao if fatura.cartao is not None else db.get(CartaoCredito, fatura.cartao_id)
    nome_cartao = ""
    if cartao:
        nome = (cartao.nome_conta or "").strip()
        nome_cartao = cartao.banco + (f" — {nome}" if nome else "")
    contas = listar_contas_vinculadas_fatura(db, fatura)
    lancamentos = [LancamentoFaturaItem.model_validate(c) for c in contas]
    return FaturaCartaoDetalheOut(
        fatura=_montar_fatura_out(fatura),
        nome_cartao=nome_cartao or f"Cartao #{fatura.cartao_id}",
        lancamentos=lancamentos,
    )


@router.put("/faturas/{fatura_id}/pagar", response_model=FaturaCartaoOut)
def pagar_fatura_endpoint(
    fatura_id: int,
    conta_id: int = Query(..., description="Conta corrente que fara o pagamento"),
    data_pagamento: Optional[date] = None,
    db: Session = Depends(get_db),
) -> FaturaCartao:
    fatura = db.get(FaturaCartao, fatura_id)
    if not fatura:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fatura nao encontrada.")
    conta = db.get(ContaCorrente, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")

    pagar_fatura(db=db, fatura=fatura, conta_corrente=conta, data_pagamento=data_pagamento)
    db.commit()
    atual = db.execute(
        select(FaturaCartao).where(FaturaCartao.id == fatura_id).options(joinedload(FaturaCartao.cartao))
    ).scalar_one()
    return _montar_fatura_out(atual)


@router.delete("/faturas/{fatura_id}")
def excluir_fatura_paga_endpoint(fatura_id: int, db: Session = Depends(get_db)) -> dict:
    """Remove apenas o registro da fatura paga (sem estornar banco, cartao nem lancamentos)."""
    resultado = excluir_fatura_paga(db, fatura_id)
    db.commit()
    return resultado


@router.get("/{item_id}", response_model=CartaoCreditoOut)
def buscar(item_id: int, db: Session = Depends(get_db)) -> CartaoCredito:
    item = db.get(CartaoCredito, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartao nao encontrado.")
    return item


@router.put("/{item_id}", response_model=CartaoCreditoOut)
def atualizar(item_id: int, payload: CartaoCreditoUpdate, db: Session = Depends(get_db)) -> CartaoCredito:
    item = db.get(CartaoCredito, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartao nao encontrado.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(CartaoCredito, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartao nao encontrado.")
    tem_conta = db.query(ContaPagar).filter(ContaPagar.cartao_id == item_id).first()
    if tem_conta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel excluir cartao com lancamentos vinculados.",
        )
    db.query(FaturaCartao).filter(FaturaCartao.cartao_id == item_id).delete()
    db.delete(item)
    db.commit()
