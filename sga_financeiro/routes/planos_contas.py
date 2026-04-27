"""Endpoints de plano de contas."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.plano_conta import PlanoConta
from sga_financeiro.schemas.plano_conta import PlanoContaCreate, PlanoContaOut, PlanoContaUpdate

router = APIRouter(prefix="/planos-contas", tags=["Planos de Contas"])

PLANOS_INICIAIS = [
    "RECEITAS OPERACIONAIS",
    "RECEITAS NÃO OPERACIONAIS",
    "DESPESAS OPERACIONAIS",
    "DESPESAS NÃO OPERACIONAIS",
]
PLANOS_LEGADOS = {
    "receitas nao operacionais": "RECEITAS NÃO OPERACIONAIS",
    "despesas nao operacionais": "DESPESAS NÃO OPERACIONAIS",
}


def _normalizar_nome_plano(nome: str) -> str:
    return nome.strip().upper()


def _seed_planos(db: Session) -> None:
    itens = db.query(PlanoConta).all()
    existentes = {item.nome.lower(): item for item in itens}
    alterou = False

    for legado, atual in PLANOS_LEGADOS.items():
        item_legado = existentes.get(legado.lower())
        item_atual = existentes.get(atual.lower())
        if item_legado and not item_atual:
            item_legado.nome = atual
            existentes[atual.lower()] = item_legado
            alterou = True

    for item in itens:
        nome_maiusculo = _normalizar_nome_plano(item.nome)
        if item.nome != nome_maiusculo:
            item.nome = nome_maiusculo
            alterou = True

    for nome in PLANOS_INICIAIS:
        if nome.lower() not in existentes:
            db.add(PlanoConta(nome=nome))
            alterou = True
    if alterou:
        db.commit()


@router.get("", response_model=list[PlanoContaOut])
def listar(db: Session = Depends(get_db)) -> list[PlanoConta]:
    _seed_planos(db)
    return db.query(PlanoConta).order_by(PlanoConta.nome).all()


@router.post("", response_model=PlanoContaOut, status_code=status.HTTP_201_CREATED)
def criar(payload: PlanoContaCreate, db: Session = Depends(get_db)) -> PlanoConta:
    nome = _normalizar_nome_plano(payload.nome)
    if db.query(PlanoConta).filter(PlanoConta.nome.ilike(nome)).first():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plano de conta ja cadastrado.")
    item = PlanoConta(nome=nome)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=PlanoContaOut)
def atualizar(item_id: int, payload: PlanoContaUpdate, db: Session = Depends(get_db)) -> PlanoConta:
    item = db.get(PlanoConta, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plano de conta nao encontrado.")
    nome = _normalizar_nome_plano(payload.nome)
    existente = db.query(PlanoConta).filter(PlanoConta.nome.ilike(nome), PlanoConta.id != item_id).first()
    if existente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plano de conta ja cadastrado.")
    item.nome = nome
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(PlanoConta, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plano de conta nao encontrado.")
    db.delete(item)
    db.commit()
