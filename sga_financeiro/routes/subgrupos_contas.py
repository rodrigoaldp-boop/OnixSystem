"""Endpoints de subgrupo de contas."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.grupo_conta import GrupoConta
from sga_financeiro.models.subgrupo_conta import SubgrupoConta
from sga_financeiro.schemas.subgrupo_conta import SubgrupoContaCreate, SubgrupoContaOut, SubgrupoContaUpdate

router = APIRouter(prefix="/subgrupos-contas", tags=["Subgrupo de Contas"])


@router.get("", response_model=list[SubgrupoContaOut])
def listar(grupo_conta_id: Optional[int] = Query(None), db: Session = Depends(get_db)) -> list[SubgrupoConta]:
    query = db.query(SubgrupoConta)
    if grupo_conta_id:
        query = query.filter(SubgrupoConta.grupo_conta_id == grupo_conta_id)
    return query.order_by(SubgrupoConta.nome).all()


@router.post("", response_model=SubgrupoContaOut, status_code=status.HTTP_201_CREATED)
def criar(payload: SubgrupoContaCreate, db: Session = Depends(get_db)) -> SubgrupoConta:
    if not db.get(GrupoConta, payload.grupo_conta_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo de contas nao encontrado.")
    nome = payload.nome.strip()
    existente = (
        db.query(SubgrupoConta)
        .filter(SubgrupoConta.grupo_conta_id == payload.grupo_conta_id, SubgrupoConta.nome.ilike(nome))
        .first()
    )
    if existente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subgrupo ja cadastrado para este grupo.")
    item = SubgrupoConta(nome=nome, grupo_conta_id=payload.grupo_conta_id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=SubgrupoContaOut)
def atualizar(item_id: int, payload: SubgrupoContaUpdate, db: Session = Depends(get_db)) -> SubgrupoConta:
    item = db.get(SubgrupoConta, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subgrupo nao encontrado.")
    if not db.get(GrupoConta, payload.grupo_conta_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo de contas nao encontrado.")
    nome = payload.nome.strip()
    existente = (
        db.query(SubgrupoConta)
        .filter(
            SubgrupoConta.grupo_conta_id == payload.grupo_conta_id,
            SubgrupoConta.nome.ilike(nome),
            SubgrupoConta.id != item_id,
        )
        .first()
    )
    if existente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Subgrupo ja cadastrado para este grupo.")
    item.nome = nome
    item.grupo_conta_id = payload.grupo_conta_id
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(SubgrupoConta, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subgrupo nao encontrado.")
    db.delete(item)
    db.commit()
