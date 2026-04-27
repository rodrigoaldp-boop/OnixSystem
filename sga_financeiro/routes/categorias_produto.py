"""CRUD de categorias de produto."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.categoria_produto import CategoriaProduto
from sga_financeiro.models.produto import Produto
from sga_financeiro.schemas.categoria_produto import CategoriaProdutoOut, CategoriaProdutoUpdate

router = APIRouter(prefix="/categorias-produto", tags=["Categorias de produto"])

_CODIGOS_IMUTAVEIS = frozenset({"PRODUTOS", "SERVICOS"})


def garantir_categorias_produto_padrao(db: Session) -> None:
    """Garante as categorias padrao PRODUTOS e SERVICOS."""
    padroes: list[tuple[str, str, Decimal]] = [
        ("PRODUTOS", "PRODUTOS", Decimal("0")),
        ("SERVICOS", "SERVIÇOS", Decimal("0")),
    ]
    for codigo, nome, pct in padroes:
        existente = db.query(CategoriaProduto).filter(CategoriaProduto.codigo == codigo).first()
        if not existente:
            db.add(CategoriaProduto(codigo=codigo, nome=nome, percentual_comissao=pct))
    db.commit()


@router.get("", response_model=list[CategoriaProdutoOut])
def listar(db: Session = Depends(get_db)) -> list[CategoriaProduto]:
    garantir_categorias_produto_padrao(db)
    return db.query(CategoriaProduto).order_by(CategoriaProduto.id.asc()).all()


@router.put("/{item_id}", response_model=CategoriaProdutoOut)
def atualizar(item_id: int, payload: CategoriaProdutoUpdate, db: Session = Depends(get_db)) -> CategoriaProduto:
    garantir_categorias_produto_padrao(db)
    item = db.get(CategoriaProduto, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria nao encontrada.")
    dados = payload.model_dump(exclude_unset=True)
    if item.codigo in _CODIGOS_IMUTAVEIS and "nome" in dados:
        del dados["nome"]
    for campo, valor in dados.items():
        if campo == "percentual_comissao" and valor is not None:
            v = Decimal(str(valor))
            if v < Decimal("0"):
                v = Decimal("0")
            if v > Decimal("100"):
                v = Decimal("100")
            valor = v
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    garantir_categorias_produto_padrao(db)
    item = db.get(CategoriaProduto, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria nao encontrada.")
    if item.codigo in _CODIGOS_IMUTAVEIS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Categorias padrao (PRODUTOS e SERVICOS) nao podem ser excluidas.",
        )
    em_uso = db.query(Produto.id).filter(Produto.categoria_produto_id == item_id).first()
    if em_uso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Existem produtos vinculados a esta categoria. Altere-os antes de excluir.",
        )
    db.delete(item)
    db.commit()
