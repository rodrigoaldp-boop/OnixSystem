"""Endpoints CRUD de produtos."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.categoria_produto import CategoriaProduto
from sga_financeiro.models.produto import Produto
from sga_financeiro.routes.categorias_produto import garantir_categorias_produto_padrao
from sga_financeiro.schemas.produto import ProdutoCreate, ProdutoOut, ProdutoUpdate

router = APIRouter(prefix="/produtos", tags=["Produtos"])


def _map_nomes_categorias(db: Session) -> dict[int, str]:
    return {c.id: c.nome for c in db.query(CategoriaProduto).all()}


def _sync_produto_flags_por_categoria(db: Session, item: Produto, categoria_id: int) -> None:
    cat = db.get(CategoriaProduto, categoria_id)
    if not cat:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Categoria de produto invalida.")
    item.categoria_produto_id = cat.id
    item.is_servico = cat.codigo == "SERVICOS"
    item.ativa = True


def _to_out(db: Session, item: Produto, nomes: dict[int, str] | None = None) -> ProdutoOut:
    m = nomes if nomes is not None else _map_nomes_categorias(db)
    return ProdutoOut.model_validate(item).model_copy(
        update={"categoria_nome": m.get(item.categoria_produto_id, "")},
    )


def garantir_produto_padrao(db: Session) -> None:
    garantir_categorias_produto_padrao(db)
    existe = db.query(Produto).filter(Produto.nome == "CARTAO RFID").first()
    if existe:
        return
    cid = db.query(CategoriaProduto.id).filter(CategoriaProduto.codigo == "PRODUTOS").scalar()
    if not cid:
        raise RuntimeError("Categoria PRODUTOS nao encontrada apos seed.")
    item = Produto(
        nome="CARTAO RFID",
        sku="CARTAO-RFID-001",
        categoria_produto_id=int(cid),
        is_servico=False,
        unidade="UN",
        preco_custo=Decimal("6.50"),
        preco_venda=Decimal("15.00"),
        ncm="85235290",
        cest="",
        cfop_compra="1102",
        cfop_venda="5102",
        csosn="102",
        aliquota_icms_entrada=Decimal("0"),
        aliquota_icms_saida=Decimal("0"),
        descricao="Produto padrao para identificacao RFID.",
        ativa=True,
    )
    db.add(item)
    db.commit()


@router.get("", response_model=list[ProdutoOut])
def listar(db: Session = Depends(get_db)) -> list[ProdutoOut]:
    garantir_categorias_produto_padrao(db)
    garantir_produto_padrao(db)
    itens = db.query(Produto).order_by(Produto.id.desc()).all()
    nomes = _map_nomes_categorias(db)
    return [_to_out(db, p, nomes) for p in itens]


@router.post("", response_model=ProdutoOut, status_code=status.HTTP_201_CREATED)
def criar(payload: ProdutoCreate, db: Session = Depends(get_db)) -> ProdutoOut:
    garantir_categorias_produto_padrao(db)
    dados = payload.model_dump()
    item = Produto(**dados)
    _sync_produto_flags_por_categoria(db, item, int(payload.categoria_produto_id))
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_out(db, item)


@router.put("/{item_id}", response_model=ProdutoOut)
def atualizar(item_id: int, payload: ProdutoUpdate, db: Session = Depends(get_db)) -> ProdutoOut:
    garantir_categorias_produto_padrao(db)
    item = db.get(Produto, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto nao encontrado.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        if campo in ("is_servico", "ativa"):
            continue
        setattr(item, campo, valor)
    cat_id = int(item.categoria_produto_id)
    if payload.categoria_produto_id is not None:
        cat_id = int(payload.categoria_produto_id)
    _sync_produto_flags_por_categoria(db, item, cat_id)
    db.commit()
    db.refresh(item)
    return _to_out(db, item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(Produto, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Produto nao encontrado.")
    db.delete(item)
    db.commit()
