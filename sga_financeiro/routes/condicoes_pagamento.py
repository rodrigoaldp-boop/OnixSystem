"""CRUD de condicoes de pagamento (PIX, Boleto, etc.)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.condicao_pagamento import CondicaoPagamento
from sga_financeiro.models.venda import Venda
from sga_financeiro.schemas.condicao_pagamento import (
    CondicaoPagamentoCreate,
    CondicaoPagamentoOut,
    CondicaoPagamentoUpdate,
)

router = APIRouter(prefix="/condicoes-pagamento", tags=["Condicoes de pagamento"])


def garantir_condicoes_padrao(db: Session) -> None:
    """Garante registros padrao PIX e Boleto."""
    for nome in ("PIX", "Boleto"):
        existente = db.query(CondicaoPagamento).filter(CondicaoPagamento.nome == nome).first()
        if not existente:
            db.add(CondicaoPagamento(nome=nome))
    db.commit()


@router.get("", response_model=list[CondicaoPagamentoOut])
def listar(db: Session = Depends(get_db)) -> list[CondicaoPagamento]:
    garantir_condicoes_padrao(db)
    return db.query(CondicaoPagamento).order_by(CondicaoPagamento.nome.asc()).all()


@router.post("", response_model=CondicaoPagamentoOut, status_code=status.HTTP_201_CREATED)
def criar(payload: CondicaoPagamentoCreate, db: Session = Depends(get_db)) -> CondicaoPagamento:
    garantir_condicoes_padrao(db)
    nome = (payload.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe o nome.")
    dup = db.query(CondicaoPagamento).filter(CondicaoPagamento.nome == nome).first()
    if dup:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ja existe condicao com este nome.")
    item = CondicaoPagamento(nome=nome)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=CondicaoPagamentoOut)
def atualizar(item_id: int, payload: CondicaoPagamentoUpdate, db: Session = Depends(get_db)) -> CondicaoPagamento:
    garantir_condicoes_padrao(db)
    item = db.get(CondicaoPagamento, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condicao nao encontrada.")
    nome = (payload.nome or "").strip()
    if not nome:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe o nome.")
    dup = (
        db.query(CondicaoPagamento)
        .filter(CondicaoPagamento.nome == nome, CondicaoPagamento.id != item_id)
        .first()
    )
    if dup:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ja existe condicao com este nome.")
    item.nome = nome
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    garantir_condicoes_padrao(db)
    item = db.get(CondicaoPagamento, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condicao nao encontrada.")
    em_uso = db.query(Venda.id).filter(Venda.condicao_pagamento_id == item_id).first()
    if em_uso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Existem vendas usando esta condicao. Altere-as antes de excluir.",
        )
    db.delete(item)
    db.commit()
