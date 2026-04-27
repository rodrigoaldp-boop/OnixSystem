"""Endpoints de contas a receber."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from sga_financeiro.database import get_db
from sga_financeiro.models.cadastro_geral import CadastroGeral
from sga_financeiro.models.categoria import Categoria, TipoCategoria
from sga_financeiro.models.categoria_produto import CategoriaProduto
from sga_financeiro.models.centro_custos import CentroCustos
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.conta_pagar import ContaPagar, StatusContaPagar
from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.models.fornecedor import Fornecedor
from sga_financeiro.models.produto import Produto
from sga_financeiro.models.venda import Venda
from sga_financeiro.schemas.conta_receber import ContaReceberBaixa, ContaReceberCreate, ContaReceberOut, ContaReceberUpdate
from sga_financeiro.services.pagamento_service import receber_conta_receber

router = APIRouter(prefix="/contas-receber", tags=["Contas a Receber"])


def _ultimo_dia_mes(ref: date) -> date:
    inicio_prox = ref.replace(day=28) + timedelta(days=4)
    return inicio_prox - timedelta(days=inicio_prox.day)


def _categoria_padrao_despesa(db: Session) -> Categoria:
    categoria = db.query(Categoria).filter(Categoria.nome == "Comissao de vendas").first()
    if categoria:
        return categoria
    categoria = Categoria(nome="Comissao de vendas", tipo=TipoCategoria.DESPESA, descricao="Criada automaticamente.")
    db.add(categoria)
    db.flush()
    return categoria


def _centro_custos_padrao(db: Session) -> CentroCustos:
    centro = db.query(CentroCustos).filter(CentroCustos.codigo == "GERAL").first()
    if centro:
        return centro
    centro = CentroCustos(nome="Geral", codigo="GERAL", descricao="Criado automaticamente.")
    db.add(centro)
    db.flush()
    return centro


def _garantir_fornecedor_vendedor(db: Session, vendedor_id: int | None) -> Fornecedor | None:
    if not vendedor_id:
        return None
    fornecedor = db.get(Fornecedor, vendedor_id)
    if fornecedor:
        return fornecedor
    cadastro = db.get(CadastroGeral, vendedor_id)
    if not cadastro or not cadastro.is_vendedor:
        return None
    fornecedor = Fornecedor(
        id=cadastro.id,
        nome=cadastro.razao_social,
        cnpj_cpf=cadastro.cnpj,
        telefone=cadastro.telefone,
        endereco=cadastro.endereco,
    )
    db.add(fornecedor)
    db.flush()
    return fornecedor


def _percentual_comissao_venda(db: Session, venda: Venda) -> Decimal:
    if not venda.total_liquido or Decimal(venda.total_liquido) <= 0:
        return Decimal("0")
    total_comissao = Decimal("0")
    for item in venda.itens:
        produto = db.get(Produto, item.produto_id)
        if not produto:
            continue
        cat_prod = db.get(CategoriaProduto, produto.categoria_produto_id)
        if not cat_prod:
            continue
        perc = Decimal(cat_prod.percentual_comissao or 0)
        if perc <= 0:
            continue
        total_comissao += (Decimal(item.total_item or 0) * perc / Decimal("100"))
    total_liq = Decimal(venda.total_liquido or 0)
    if total_liq <= 0:
        return Decimal("0")
    return (total_comissao / total_liq).quantize(Decimal("0.0001"))


def _gerar_comissao_no_recebimento(db: Session, conta_receber: ContaReceber) -> None:
    if conta_receber.comissao_gerada or not conta_receber.venda_id:
        return
    venda = (
        db.query(Venda)
        .options(joinedload(Venda.itens))
        .filter(Venda.id == conta_receber.venda_id)
        .first()
    )
    if not venda or not venda.vendedor_id:
        conta_receber.comissao_gerada = True
        return
    vendedor = db.get(CadastroGeral, venda.vendedor_id)
    if not vendedor or not vendedor.vendedor_comissionado:
        conta_receber.comissao_gerada = True
        return
    fornecedor = _garantir_fornecedor_vendedor(db, venda.vendedor_id)
    if not fornecedor:
        conta_receber.comissao_gerada = True
        return
    percentual = _percentual_comissao_venda(db, venda)
    valor_base = Decimal(conta_receber.valor or 0)
    valor_comissao = (valor_base * percentual).quantize(Decimal("0.01"))
    if valor_comissao <= 0:
        conta_receber.comissao_gerada = True
        return
    referencia = conta_receber.data_recebimento or date.today()
    vencimento = _ultimo_dia_mes(referencia)
    categoria = _categoria_padrao_despesa(db)
    centro = _centro_custos_padrao(db)
    conta_pagar = ContaPagar(
        descricao=f"Comissao vendedor pedido {venda.numero}",
        valor=valor_comissao,
        categoria_id=categoria.id,
        centro_custos_id=centro.id,
        fornecedor_id=fornecedor.id,
        data_vencimento=vencimento,
        status=StatusContaPagar.PENDENTE,
    )
    db.add(conta_pagar)
    conta_receber.comissao_gerada = True


@router.get("", response_model=list[ContaReceberOut])
def listar(db: Session = Depends(get_db)) -> list[ContaReceber]:
    return db.query(ContaReceber).order_by(ContaReceber.data_vencimento.asc()).all()


@router.post("", response_model=ContaReceberOut, status_code=status.HTTP_201_CREATED)
def criar(payload: ContaReceberCreate, db: Session = Depends(get_db)) -> ContaReceber:
    dados = payload.model_dump()
    status_solicitado = dados.pop("status", StatusContaReceber.PENDENTE)
    data_recebimento = dados.pop("data_recebimento", None)
    conta = ContaReceber(**dados, status=StatusContaReceber.PENDENTE)
    db.add(conta)
    db.flush()

    if status_solicitado == StatusContaReceber.RECEBIDO:
        if not conta.conta_destino_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Conta corrente obrigatoria para recebimento imediato.",
            )
        conta_corrente = db.get(ContaCorrente, conta.conta_destino_id)
        if not conta_corrente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")
        receber_conta_receber(
            db=db,
            conta_receber=conta,
            conta_corrente=conta_corrente,
            data_recebimento=data_recebimento,
            comprovante_url=conta.comprovante_url,
        )
        _gerar_comissao_no_recebimento(db, conta)
    elif status_solicitado == StatusContaReceber.VENCIDO:
        conta.status = StatusContaReceber.VENCIDO

    db.commit()
    db.refresh(conta)
    return conta


@router.get("/{conta_id}", response_model=ContaReceberOut)
def buscar(conta_id: int, db: Session = Depends(get_db)) -> ContaReceber:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    return conta


@router.put("/{conta_id}", response_model=ContaReceberOut)
def atualizar(conta_id: int, payload: ContaReceberUpdate, db: Session = Depends(get_db)) -> ContaReceber:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(conta, campo, valor)
    db.commit()
    db.refresh(conta)
    return conta


@router.put("/{conta_id}/receber", response_model=ContaReceberOut)
def receber(conta_id: int, payload: ContaReceberBaixa, db: Session = Depends(get_db)) -> ContaReceber:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    conta_corrente = db.get(ContaCorrente, payload.conta_destino_id)
    if not conta_corrente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")

    receber_conta_receber(
        db=db,
        conta_receber=conta,
        conta_corrente=conta_corrente,
        data_recebimento=payload.data_recebimento,
        comprovante_url=payload.comprovante_url,
    )
    _gerar_comissao_no_recebimento(db, conta)
    db.commit()
    db.refresh(conta)
    return conta


@router.delete("/{conta_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(conta_id: int, db: Session = Depends(get_db)) -> None:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    db.delete(conta)
    db.commit()
