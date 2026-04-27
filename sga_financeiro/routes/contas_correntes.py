"""Endpoints de contas correntes."""

from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sga_financeiro.database import get_db
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.movimentacao import Movimentacao, TipoMovimentacao
from sga_financeiro.schemas.conta_corrente import (
    ContaCorrenteCreate,
    ContaCorrenteOut,
    ContaCorrenteUpdate,
    TransferenciaContaCreate,
)
from sga_financeiro.schemas.movimentacao import ConciliarMovimentacoesIn, MovimentacaoPendenteOut
from sga_financeiro.services.conta_service import creditar_conta, debitar_conta

router = APIRouter(prefix="/contas-correntes", tags=["Contas Correntes"])


@router.get("", response_model=list[ContaCorrenteOut])
def listar(db: Session = Depends(get_db)) -> list[ContaCorrente]:
    return db.query(ContaCorrente).order_by(ContaCorrente.id.desc()).all()


@router.post("", response_model=ContaCorrenteOut, status_code=status.HTTP_201_CREATED)
def criar(payload: ContaCorrenteCreate, db: Session = Depends(get_db)) -> ContaCorrente:
    conta = ContaCorrente(**payload.model_dump())
    db.add(conta)
    db.commit()
    db.refresh(conta)
    return conta


@router.post("/transferencias")
def transferir(payload: TransferenciaContaCreate, db: Session = Depends(get_db)) -> dict:
    if payload.conta_origem_id == payload.conta_destino_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Origem e destino devem ser diferentes.")

    conta_origem = db.get(ContaCorrente, payload.conta_origem_id)
    if not conta_origem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta de origem nao encontrada.")

    conta_destino = db.get(ContaCorrente, payload.conta_destino_id)
    if not conta_destino:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta de destino nao encontrada.")

    valor = Decimal(payload.valor)
    if valor <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valor da transferencia deve ser maior que zero.")

    referencia = f"TRANSF:{conta_origem.id}->{conta_destino.id}"
    motivo = (payload.motivo or "").strip()
    descricao_saida = f"Transferencia para {conta_destino.banco}/{conta_destino.numero}"
    descricao_entrada = f"Transferencia de {conta_origem.banco}/{conta_origem.numero}"
    if motivo:
        descricao_saida = f"{descricao_saida} - {motivo}"
        descricao_entrada = f"{descricao_entrada} - {motivo}"

    debitar_conta(db, conta_origem, valor, descricao_saida, referencia=referencia)
    creditar_conta(db, conta_destino, valor, descricao_entrada, referencia=referencia)

    db.commit()
    db.refresh(conta_origem)
    db.refresh(conta_destino)

    return {
        "status": "ok",
        "saldo_origem": conta_origem.saldo_atual,
        "saldo_destino": conta_destino.saldo_atual,
    }


@router.get("/lancamentos-pendentes", response_model=list[MovimentacaoPendenteOut])
def listar_lancamentos_pendentes(db: Session = Depends(get_db)) -> list[MovimentacaoPendenteOut]:
    pendentes = (
        db.query(Movimentacao, ContaCorrente.nome_conta, ContaCorrente.banco, ContaCorrente.numero)
        .join(ContaCorrente, ContaCorrente.id == Movimentacao.conta_id)
        .filter(Movimentacao.conciliado.is_(False))
        .order_by(Movimentacao.data_movimento.desc(), Movimentacao.id.desc())
        .all()
    )
    saida: list[MovimentacaoPendenteOut] = []
    for mov, nome_conta, banco, numero in pendentes:
        conta_nome = (nome_conta or "").strip() or f"{banco}/{numero}"
        saida.append(
            MovimentacaoPendenteOut(
                id=mov.id,
                tipo=mov.tipo,
                conta_id=mov.conta_id,
                conta_nome=conta_nome,
                valor=mov.valor,
                descricao=mov.descricao,
                referencia=mov.referencia,
                data_movimento=mov.data_movimento,
            )
        )
    return saida


@router.post("/lancamentos-pendentes/conciliar")
def conciliar_lancamentos_pendentes(payload: ConciliarMovimentacoesIn, db: Session = Depends(get_db)) -> dict:
    movimentos = (
        db.query(Movimentacao)
        .filter(Movimentacao.id.in_(payload.ids))
        .order_by(Movimentacao.data_movimento.asc(), Movimentacao.id.asc())
        .all()
    )
    if not movimentos:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lancamentos nao encontrados.")

    conciliados = 0
    for mov in movimentos:
        if mov.conciliado:
            continue
        conta = db.get(ContaCorrente, mov.conta_id)
        if not conta:
            continue
        if mov.tipo == TipoMovimentacao.DEBITO:
            conta.saldo_atual -= mov.valor
        else:
            conta.saldo_atual += mov.valor
        mov.conciliado = True
        mov.data_conciliacao = datetime.utcnow()
        conciliados += 1

    db.commit()
    return {"status": "ok", "conciliados": conciliados}


@router.get("/{conta_id}", response_model=ContaCorrenteOut)
def buscar(conta_id: int, db: Session = Depends(get_db)) -> ContaCorrente:
    conta = db.get(ContaCorrente, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")
    return conta


@router.put("/{conta_id}", response_model=ContaCorrenteOut)
def atualizar(conta_id: int, payload: ContaCorrenteUpdate, db: Session = Depends(get_db)) -> ContaCorrente:
    conta = db.get(ContaCorrente, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(conta, campo, valor)
    db.commit()
    db.refresh(conta)
    return conta


@router.delete("/{conta_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(conta_id: int, db: Session = Depends(get_db)) -> None:
    conta = db.get(ContaCorrente, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta corrente nao encontrada.")
    db.delete(conta)
    db.commit()
