"""Endpoints de grupo de contas."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.grupo_conta import GrupoConta
from sga_financeiro.models.subgrupo_conta import SubgrupoConta
from sga_financeiro.schemas.grupo_conta import GrupoContaCreate, GrupoContaOut, GrupoContaUpdate

router = APIRouter(prefix="/grupos-contas", tags=["Grupo de Contas"])


@router.get("", response_model=list[GrupoContaOut])
def listar(db: Session = Depends(get_db)) -> list[GrupoConta]:
    return db.query(GrupoConta).order_by(GrupoConta.nome).all()


@router.post("", response_model=GrupoContaOut, status_code=status.HTTP_201_CREATED)
def criar(payload: GrupoContaCreate, db: Session = Depends(get_db)) -> GrupoConta:
    nome = payload.nome.strip()
    if db.query(GrupoConta).filter(GrupoConta.nome.ilike(nome)).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Grupo de contas ja cadastrado.")
    item = GrupoConta(nome=nome)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=GrupoContaOut)
def atualizar(item_id: int, payload: GrupoContaUpdate, db: Session = Depends(get_db)) -> GrupoConta:
    item = db.get(GrupoConta, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo de contas nao encontrado.")
    nome = payload.nome.strip()
    existente = db.query(GrupoConta).filter(GrupoConta.nome.ilike(nome), GrupoConta.id != item_id).first()
    if existente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Grupo de contas ja cadastrado.")
    item.nome = nome
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(GrupoConta, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo de contas nao encontrado.")
    if db.query(SubgrupoConta).filter(SubgrupoConta.grupo_conta_id == item_id).first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel excluir: existem subgrupos vinculados a este grupo.",
        )
    db.delete(item)
    db.commit()
