"""Endpoints CRUD de clientes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.cliente import Cliente
from sga_financeiro.schemas.cliente import ClienteCreate, ClienteOut, ClienteUpdate

router = APIRouter(prefix="/clientes", tags=["Clientes"])


@router.get("", response_model=list[ClienteOut])
def listar(db: Session = Depends(get_db)) -> list[Cliente]:
    return db.query(Cliente).order_by(Cliente.nome).all()


@router.post("", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
def criar(payload: ClienteCreate, db: Session = Depends(get_db)) -> Cliente:
    item = Cliente(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=ClienteOut)
def buscar(item_id: int, db: Session = Depends(get_db)) -> Cliente:
    item = db.get(Cliente, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente nao encontrado.")
    return item


@router.put("/{item_id}", response_model=ClienteOut)
def atualizar(item_id: int, payload: ClienteUpdate, db: Session = Depends(get_db)) -> Cliente:
    item = db.get(Cliente, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente nao encontrado.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(Cliente, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente nao encontrado.")
    db.delete(item)
    db.commit()
