"""Endpoints CRUD de fornecedores."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.fornecedor import Fornecedor
from sga_financeiro.schemas.fornecedor import FornecedorCreate, FornecedorOut, FornecedorUpdate

router = APIRouter(prefix="/fornecedores", tags=["Fornecedores"])


@router.get("", response_model=list[FornecedorOut])
def listar(db: Session = Depends(get_db)) -> list[Fornecedor]:
    return db.query(Fornecedor).order_by(Fornecedor.nome).all()


@router.post("", response_model=FornecedorOut, status_code=status.HTTP_201_CREATED)
def criar(payload: FornecedorCreate, db: Session = Depends(get_db)) -> Fornecedor:
    item = Fornecedor(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=FornecedorOut)
def buscar(item_id: int, db: Session = Depends(get_db)) -> Fornecedor:
    item = db.get(Fornecedor, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor nao encontrado.")
    return item


@router.put("/{item_id}", response_model=FornecedorOut)
def atualizar(item_id: int, payload: FornecedorUpdate, db: Session = Depends(get_db)) -> Fornecedor:
    item = db.get(Fornecedor, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor nao encontrado.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(Fornecedor, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor nao encontrado.")
    db.delete(item)
    db.commit()
