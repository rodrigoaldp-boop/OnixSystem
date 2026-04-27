"""Endpoints CRUD de centros de custos."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.centro_custos import CentroCustos
from sga_financeiro.schemas.centro_custos import CentroCustosCreate, CentroCustosOut, CentroCustosUpdate

router = APIRouter(prefix="/centros-custos", tags=["Centros de Custos"])


@router.get("", response_model=list[CentroCustosOut])
def listar(db: Session = Depends(get_db)) -> list[CentroCustos]:
    return db.query(CentroCustos).order_by(CentroCustos.nome).all()


@router.post("", response_model=CentroCustosOut, status_code=status.HTTP_201_CREATED)
def criar(payload: CentroCustosCreate, db: Session = Depends(get_db)) -> CentroCustos:
    item = CentroCustos(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/{item_id}", response_model=CentroCustosOut)
def buscar(item_id: int, db: Session = Depends(get_db)) -> CentroCustos:
    item = db.get(CentroCustos, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Centro de custos nao encontrado.")
    return item


@router.put("/{item_id}", response_model=CentroCustosOut)
def atualizar(item_id: int, payload: CentroCustosUpdate, db: Session = Depends(get_db)) -> CentroCustos:
    item = db.get(CentroCustos, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Centro de custos nao encontrado.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(CentroCustos, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Centro de custos nao encontrado.")
    db.delete(item)
    db.commit()
