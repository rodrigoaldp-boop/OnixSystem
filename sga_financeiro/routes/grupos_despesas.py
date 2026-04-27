"""Endpoints de grupos de despesas."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.grupo_despesa import GrupoDespesa
from sga_financeiro.schemas.grupo_despesa import GrupoDespesaCreate, GrupoDespesaOut, GrupoDespesaUpdate

router = APIRouter(prefix="/grupos-despesas", tags=["Grupos de Despesas"])

GRUPOS_INICIAIS = ["GERAL", "ONIX", "PESSOAL"]


def _seed_grupos(db: Session) -> None:
    existentes = {item.nome.lower(): item for item in db.query(GrupoDespesa).all()}
    alterou = False
    for nome in GRUPOS_INICIAIS:
        if nome.lower() not in existentes:
            db.add(GrupoDespesa(nome=nome))
            alterou = True
    if alterou:
        db.commit()


@router.get("", response_model=list[GrupoDespesaOut])
def listar(db: Session = Depends(get_db)) -> list[GrupoDespesa]:
    _seed_grupos(db)
    return db.query(GrupoDespesa).order_by(GrupoDespesa.nome).all()


@router.post("", response_model=GrupoDespesaOut, status_code=status.HTTP_201_CREATED)
def criar(payload: GrupoDespesaCreate, db: Session = Depends(get_db)) -> GrupoDespesa:
    nome = payload.nome.strip()
    if db.query(GrupoDespesa).filter(GrupoDespesa.nome.ilike(nome)).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Grupo de despesa ja cadastrado.")
    item = GrupoDespesa(nome=nome)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=GrupoDespesaOut)
def atualizar(item_id: int, payload: GrupoDespesaUpdate, db: Session = Depends(get_db)) -> GrupoDespesa:
    item = db.get(GrupoDespesa, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo de despesa nao encontrado.")
    nome = payload.nome.strip()
    existente = db.query(GrupoDespesa).filter(GrupoDespesa.nome.ilike(nome), GrupoDespesa.id != item_id).first()
    if existente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Grupo de despesa ja cadastrado.")
    item.nome = nome
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(GrupoDespesa, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo de despesa nao encontrado.")
    db.delete(item)
    db.commit()
