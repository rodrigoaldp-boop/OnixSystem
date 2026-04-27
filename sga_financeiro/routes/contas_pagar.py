"""Endpoints de contas a pagar."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from sga_financeiro.models.categoria import Categoria
from sga_financeiro.models.centro_custos import CentroCustos
from sga_financeiro.database import get_db
from sga_financeiro.models.cartao_credito import CartaoCredito
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.conta_pagar import ContaPagar, StatusContaPagar
from sga_financeiro.models.fornecedor import Fornecedor
from sga_financeiro.models.categoria import TipoCategoria
from sga_financeiro.models.cadastro_geral import CadastroGeral
from sga_financeiro.schemas.conta_pagar import (
    ContaPagarBaixa,
    ContaPagarCreate,
    ContaPagarListaOut,
    ContaPagarOut,
    ContaPagarUpdate,
)
from sga_financeiro.services.pagamento_service import adicionar_lancamento_no_cartao, baixar_conta_pagar

router = APIRouter(prefix="/contas-pagar", tags=["Contas a Pagar"])


def _categoria_padrao_despesa(db: Session) -> Categoria:
    categoria = db.query(Categoria).filter(Categoria.nome == "Sem categoria").first()
    if categoria:
        return categoria
    categoria = Categoria(nome="Sem categoria", tipo=TipoCategoria.DESPESA, descricao="Criada automaticamente.")
    db.add(categoria)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        categoria = db.query(Categoria).filter(Categoria.nome == "Sem categoria").first()
        if categoria:
            return categoria
        raise
    return categoria


def _centro_custos_padrao(db: Session) -> CentroCustos:
    centro = db.query(CentroCustos).filter(CentroCustos.codigo == "GERAL").first()
    if centro:
        return centro
    centro = CentroCustos(nome="Geral", codigo="GERAL", descricao="Criado automaticamente.")
    db.add(centro)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        centro = db.query(CentroCustos).filter(CentroCustos.codigo == "GERAL").first()
        if centro:
            return centro
        raise
    return centro


def _conta_com_relacionamentos(db: Session, conta_id: int) -> ContaPagar | None:
    return (
        db.query(ContaPagar)
        .options(joinedload(ContaPagar.fatura), joinedload(ContaPagar.cartao))
        .filter(ContaPagar.id == conta_id)
        .first()
    )


def _garantir_fornecedor(db: Session, fornecedor_id: int) -> Fornecedor:
    fornecedor = db.get(Fornecedor, fornecedor_id)
    if fornecedor:
        return fornecedor

    cadastro = db.get(CadastroGeral, fornecedor_id)
    if not cadastro or not cadastro.is_fornecedor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor nao encontrado.")

    fornecedor = Fornecedor(
        id=cadastro.id,
        nome=cadastro.razao_social,
        cnpj_cpf=cadastro.cnpj,
        telefone=cadastro.telefone,
        endereco=cadastro.endereco,
    )
    db.add(fornecedor)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Falha ao sincronizar fornecedor do cadastro geral.",
        ) from exc
    return fornecedor


def _conta_para_lista_out(conta: ContaPagar) -> ContaPagarListaOut:
    base = ContaPagarOut.model_validate(conta).model_dump()
    cartao_label: str | None = None
    fatura_mes: str | None = None
    if conta.cartao:
        nome = (conta.cartao.nome_conta or "").strip()
        cartao_label = conta.cartao.banco + (f" — {nome}" if nome else "")
    if conta.fatura:
        fatura_mes = conta.fatura.mes_referencia
    elif conta.cartao_id and conta.data_vencimento:
        fatura_mes = conta.data_vencimento.strftime("%m/%Y")
    return ContaPagarListaOut(**{**base, "cartao_label": cartao_label, "fatura_mes_referencia": fatura_mes})


@router.get("", response_model=list[ContaPagarListaOut])
def listar(db: Session = Depends(get_db)) -> list[ContaPagarListaOut]:
    contas = (
        db.query(ContaPagar)
        .options(joinedload(ContaPagar.fatura), joinedload(ContaPagar.cartao))
        .order_by(ContaPagar.data_vencimento.asc())
        .all()
    )
    return [_conta_para_lista_out(c) for c in contas]


@router.post("", response_model=ContaPagarListaOut, status_code=status.HTTP_201_CREATED)
def criar(payload: ContaPagarCreate, db: Session = Depends(get_db)) -> ContaPagarListaOut:
    dados = payload.model_dump()
    status_solicitado = dados.pop("status", StatusContaPagar.PENDENTE)
    data_pagamento = dados.pop("data_pagamento", None)

    categoria = db.get(Categoria, dados["categoria_id"])
    if not categoria:
        dados["categoria_id"] = _categoria_padrao_despesa(db).id

    centro = db.get(CentroCustos, dados["centro_custos_id"])
    if not centro:
        dados["centro_custos_id"] = _centro_custos_padrao(db).id

    if dados.get("fornecedor_id"):
        _garantir_fornecedor(db, int(dados["fornecedor_id"]))

    conta = ContaPagar(**dados, status=StatusContaPagar.PENDENTE)
    if conta.cartao_id and status_solicitado == StatusContaPagar.PAGO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lancamento no cartao de credito nao pode ser marcado como pago imediato na conta corrente.",
        )
    db.add(conta)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dados invalidos para criar conta a pagar. Verifique categoria, centro de custos e fornecedor.",
        ) from exc

    # Quando o lancamento ja nasce no cartao, atualiza uso e fatura.
    if conta.cartao_id:
        cartao = db.get(CartaoCredito, conta.cartao_id)
        if not cartao:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartao nao encontrado.")
        adicionar_lancamento_no_cartao(db=db, conta_pagar=conta, cartao=cartao)

    if status_solicitado == StatusContaPagar.PAGO:
        if not conta.conta_destino_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Conta corrente obrigatoria para pagamento imediato.",
            )
        conta_corrente = db.get(ContaCorrente, conta.conta_destino_id)
        if not conta_corrente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")
        baixar_conta_pagar(
            db=db,
            conta_pagar=conta,
            conta_corrente=conta_corrente,
            data_pagamento=data_pagamento,
            comprovante_url=conta.comprovante_url,
        )
    elif status_solicitado == StatusContaPagar.VENCIDO:
        conta.status = StatusContaPagar.VENCIDO

    db.commit()
    db.refresh(conta)
    rich = _conta_com_relacionamentos(db, conta.id)
    if not rich:
        return _conta_para_lista_out(conta)
    return _conta_para_lista_out(rich)


@router.get("/{conta_id}", response_model=ContaPagarListaOut)
def buscar(conta_id: int, db: Session = Depends(get_db)) -> ContaPagarListaOut:
    conta = _conta_com_relacionamentos(db, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a pagar nao encontrada.")
    return _conta_para_lista_out(conta)


@router.put("/{conta_id}", response_model=ContaPagarListaOut)
def atualizar(conta_id: int, payload: ContaPagarUpdate, db: Session = Depends(get_db)) -> ContaPagarListaOut:
    conta = db.get(ContaPagar, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a pagar nao encontrada.")
    campos = payload.model_dump(exclude_unset=True)
    if "categoria_id" in campos and not db.get(Categoria, campos["categoria_id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoria nao encontrada.")
    if "centro_custos_id" in campos and not db.get(CentroCustos, campos["centro_custos_id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Centro de custos nao encontrado.")
    if "fornecedor_id" in campos and campos["fornecedor_id"]:
        _garantir_fornecedor(db, int(campos["fornecedor_id"]))

    for campo, valor in campos.items():
        setattr(conta, campo, valor)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dados invalidos para atualizar conta a pagar.",
        ) from exc
    db.refresh(conta)
    rich = _conta_com_relacionamentos(db, conta_id)
    return _conta_para_lista_out(rich or conta)


@router.put("/{conta_id}/baixar", response_model=ContaPagarListaOut)
def baixar(conta_id: int, payload: ContaPagarBaixa, db: Session = Depends(get_db)) -> ContaPagarListaOut:
    conta = db.get(ContaPagar, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a pagar nao encontrada.")
    conta_corrente = db.get(ContaCorrente, payload.conta_destino_id)
    if not conta_corrente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")

    baixar_conta_pagar(
        db=db,
        conta_pagar=conta,
        conta_corrente=conta_corrente,
        data_pagamento=payload.data_pagamento,
        comprovante_url=payload.comprovante_url,
    )
    db.commit()
    db.refresh(conta)
    rich = _conta_com_relacionamentos(db, conta_id)
    return _conta_para_lista_out(rich or conta)


@router.delete("/{conta_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(conta_id: int, db: Session = Depends(get_db)) -> None:
    conta = db.get(ContaPagar, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a pagar nao encontrada.")
    db.delete(conta)
    db.commit()
