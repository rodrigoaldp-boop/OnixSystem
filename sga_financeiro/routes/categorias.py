"""Endpoints CRUD de categorias."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.categoria import Categoria
from sga_financeiro.schemas.categoria import CategoriaCreate, CategoriaOut, CategoriaUpdate

router = APIRouter(prefix="/categorias", tags=["Categorias"])


@router.get("", response_model=list[CategoriaOut])
def listar_categorias(db: Session = Depends(get_db)) -> list[Categoria]:
    return db.query(Categoria).order_by(Categoria.nome).all()


@router.post("", response_model=CategoriaOut, status_code=status.HTTP_201_CREATED)
def criar_categoria(payload: CategoriaCreate, db: Session = Depends(get_db)) -> Categoria:
    categoria = Categoria(**payload.model_dump())
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return categoria


@router.get("/{categoria_id}", response_model=CategoriaOut)
def buscar_categoria(categoria_id: int, db: Session = Depends(get_db)) -> Categoria:
    categoria = db.get(Categoria, categoria_id)
    if not categoria:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria nao encontrada.")
    return categoria


@router.put("/{categoria_id}", response_model=CategoriaOut)
def atualizar_categoria(categoria_id: int, payload: CategoriaUpdate, db: Session = Depends(get_db)) -> Categoria:
    categoria = db.get(Categoria, categoria_id)
    if not categoria:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria nao encontrada.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(categoria, campo, valor)
    db.commit()
    db.refresh(categoria)
    return categoria


@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def deletar_categoria(categoria_id: int, db: Session = Depends(get_db)) -> None:
    categoria = db.get(Categoria, categoria_id)
    if not categoria:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria nao encontrada.")
    db.delete(categoria)
    db.commit()
