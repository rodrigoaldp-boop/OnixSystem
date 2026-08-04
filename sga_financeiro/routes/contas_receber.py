"""Endpoints de contas a receber."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pypdf import PdfReader, PdfWriter
from typing import Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text

from sga_financeiro.cobrancas_config import effective_asaas_runtime
from sga_financeiro.database import get_db
from sga_financeiro.models.cadastro_geral import CadastroGeral
from sga_financeiro.models.categoria import Categoria, TipoCategoria
from sga_financeiro.models.categoria_produto import CategoriaProduto
from sga_financeiro.models.centro_custos import CentroCustos
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.comissao_lancamento import ComissaoLancamento
from sga_financeiro.models.conta_pagar import ContaPagar, StatusContaPagar
from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.models.fornecedor import Fornecedor
from sga_financeiro.models.produto import Produto
from sga_financeiro.models.venda import Venda
from sga_financeiro.schemas.conta_receber import (
    ContaReceberBaixa,
    ContaReceberBoletoAsaasIn,
    ContaReceberBoletoAsaasOut,
    ContaReceberBoletosAsaasLoteIn,
    ContaReceberBoletosAsaasLoteOut,
    ContaReceberBoletosPdfMergeIn,
    ContaReceberBoletoLoteFalha,
    ContaReceberCancelarAsaasOut,
    ContaReceberCreate,
    ContaReceberEnviarBoletoEmailIn,
    ContaReceberEnviarBoletoEmailOut,
    ContaReceberEnviarBoletosEmailLoteIn,
    ContaReceberEnviarBoletosEmailLoteOut,
    ContaReceberEnviarPixWhatsappOut,
    ContaReceberImportCsvBlingOut,
    ContaReceberImportRetornoSicoobOut,
    ContaReceberOut,
    ContaReceberPixAsaasIn,
    ContaReceberPixAsaasOut,
    ContaReceberPreviewRetornoSicoobOut,
    ContaReceberSimularRecebimentoIn,
    ContaReceberSimularRecebimentoItemOut,
    ContaReceberSimularRecebimentoOut,
    ContaReceberUpdate,
)
from sga_financeiro.services import asaas_service
from sga_financeiro.services.asaas_service import cancelar_cobranca_asaas_conta
from sga_financeiro.services.cliente_sync_service import garantir_cliente_de_cadastro as _garantir_cliente
from sga_financeiro.services.documentos_email_service import (
    enviar_boleto_conta_receber_por_email,
    enviar_boletos_contas_receber_lote_por_email,
    enviar_lembrete_pagamento_conta_whatsapp,
    enviar_pix_conta_receber_whatsapp,
    listar_historico_lembrete_whatsapp_conta,
    obter_whatsapp_enviado_por_contas,
    _resolver_telefone_whatsapp_cliente,
    _nome_cliente_documento,
)
from sga_financeiro.services.historico_edicao_service import CAMPOS_CONTA, registrar_historico_edicao, snapshot_campos
from sga_financeiro.services.importacao_bling_csv_service import importar_contas_receber_csv_bling
from sga_financeiro.services.importacao_sicoob_retorno_service import (
    aplicar_retorno_sicoob_receber,
    importar_retorno_sicoob_baixar_receber,
    preview_retorno_sicoob_receber,
)
from sga_financeiro.services.pagamento_service import receber_conta_receber
from sga_financeiro.services.pagamento_service import estornar_recebimento_conta_receber

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


def _primeiro_dia_mes_atual(ref: date) -> date:
    return ref.replace(day=1)


def _registrar_comissao_lancamento(
    db: Session,
    conta_receber: ContaReceber,
    *,
    vendedor_id: int,
    venda_id: int | None,
    percentual: Decimal,
    valor_base: Decimal,
    valor_comissao: Decimal,
) -> None:
    if conta_receber.comissao_gerada or valor_comissao <= 0:
        return
    vendedor = db.get(CadastroGeral, int(vendedor_id))
    if not vendedor or not vendedor.vendedor_comissionado:
        conta_receber.comissao_gerada = True
        return
    referencia = conta_receber.data_recebimento or date.today()
    competencia = _primeiro_dia_mes_atual(referencia).strftime("%m/%Y")
    db.add(
        ComissaoLancamento(
            vendedor_id=int(vendedor_id),
            venda_id=int(venda_id) if venda_id else None,
            conta_receber_id=int(conta_receber.id),
            competencia=competencia,
            data_recebimento=referencia,
            percentual=percentual.quantize(Decimal("0.0001")),
            valor_base=valor_base.quantize(Decimal("0.01")),
            valor_comissao=valor_comissao.quantize(Decimal("0.01")),
        )
    )
    conta_receber.comissao_gerada = True


def _percentual_comissao_venda(db: Session, venda: Venda) -> Decimal:
    from sga_financeiro.services.venda_comissao_service import percentual_comissao_efetivo_venda

    return percentual_comissao_efetivo_venda(db, venda)


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
    from sga_financeiro.services.venda_comissao_service import comissao_padrao_pedido

    valor_base = Decimal(conta_receber.valor or 0)
    total_pedido = Decimal(venda.total_liquido or 0)
    if bool(getattr(venda, "comissao_personalizada", False)):
        valor_total_com = Decimal(getattr(venda, "comissao_valor", None) or 0)
        percentual = _percentual_comissao_venda(db, venda)
    else:
        percentual, valor_total_com, _ = comissao_padrao_pedido(db, venda.itens)
    if valor_total_com <= 0 or total_pedido <= 0 or valor_base <= 0:
        return
    valor_comissao = (valor_total_com * valor_base / total_pedido).quantize(Decimal("0.01"))
    _registrar_comissao_lancamento(
        db,
        conta_receber,
        vendedor_id=int(venda.vendedor_id),
        venda_id=int(venda.id),
        percentual=percentual,
        valor_base=valor_base,
        valor_comissao=valor_comissao,
    )


def _gerar_comissao_titulo_configurado(db: Session, conta_receber: ContaReceber) -> None:
    """Comissao manual no titulo (ex.: importacao Bling) — vendedor e percentual no cadastro da conta."""
    if conta_receber.comissao_gerada or conta_receber.venda_id:
        return
    if not bool(getattr(conta_receber, "comissionar_recebimento", False)):
        return
    vendedor_id = int(getattr(conta_receber, "comissao_vendedor_id", None) or 0)
    perc = Decimal(str(getattr(conta_receber, "comissao_percentual", None) or 0)).quantize(Decimal("0.0001"))
    if not vendedor_id or perc <= 0:
        return
    valor_base = Decimal(conta_receber.valor or 0)
    if valor_base <= 0:
        return
    valor_comissao = (valor_base * perc / Decimal("100")).quantize(Decimal("0.01"))
    _registrar_comissao_lancamento(
        db,
        conta_receber,
        vendedor_id=vendedor_id,
        venda_id=None,
        percentual=perc,
        valor_base=valor_base,
        valor_comissao=valor_comissao,
    )


def _gerar_comissao_por_cliente(db: Session, conta_receber: ContaReceber) -> None:
    """Fallback: mapa cliente->vendedor quando nao ha venda_id nem comissao no titulo."""
    if conta_receber.comissao_gerada or conta_receber.venda_id or not conta_receber.cliente_id:
        return
    if bool(getattr(conta_receber, "comissionar_recebimento", False)):
        return
    row = db.execute(
        text(
            "SELECT vendedor_id, percentual, ativo "
            "FROM clientes_comissao_vendedor "
            "WHERE cliente_id = :cid"
        ),
        {"cid": int(conta_receber.cliente_id)},
    ).mappings().first()
    if not row or not row.get("ativo"):
        return
    vendedor_id = int(row.get("vendedor_id") or 0)
    if not vendedor_id:
        return
    perc = Decimal(str(row.get("percentual") or 0)).quantize(Decimal("0.0001"))
    if perc <= 0:
        return
    valor_base = Decimal(conta_receber.valor or 0)
    valor_comissao = (valor_base * perc / Decimal("100")).quantize(Decimal("0.01"))
    _registrar_comissao_lancamento(
        db,
        conta_receber,
        vendedor_id=vendedor_id,
        venda_id=None,
        percentual=perc,
        valor_base=valor_base,
        valor_comissao=valor_comissao,
    )


def _gerar_todas_comissoes_recebimento(db: Session, conta_receber: ContaReceber) -> None:
    _gerar_comissao_no_recebimento(db, conta_receber)
    _gerar_comissao_titulo_configurado(db, conta_receber)
    _gerar_comissao_por_cliente(db, conta_receber)


def _cliente_id_efetivo_conta_receber(db: Session, conta: ContaReceber) -> int | None:
    if conta.cliente_id:
        return int(conta.cliente_id)
    if conta.venda_id:
        venda = db.get(Venda, int(conta.venda_id))
        if venda and venda.cliente_id:
            return int(venda.cliente_id)
    return None


@router.get("", response_model=list[ContaReceberOut])
def listar(db: Session = Depends(get_db)) -> list[ContaReceberOut]:
    contas = db.query(ContaReceber).order_by(ContaReceber.data_vencimento.asc()).all()
    wa_map = obter_whatsapp_enviado_por_contas(db, [int(c.id) for c in contas])
    out: list[ContaReceberOut] = []
    for conta in contas:
        item = ContaReceberOut.model_validate(conta)
        cliente_id_ef = _cliente_id_efetivo_conta_receber(db, conta)
        nome_cli = _nome_cliente_documento(db, cliente_id_ef) if cliente_id_ef else None
        if nome_cli == "Cliente":
            nome_cli = None
        updates: dict = {
            "cliente_nome": nome_cli,
            "cliente_telefone_whatsapp": _resolver_telefone_whatsapp_cliente(
                db,
                cliente_id=int(conta.cliente_id) if conta.cliente_id else None,
                venda_id=int(conta.venda_id) if conta.venda_id else None,
            ),
        }
        ultimo = wa_map.get(int(conta.id))
        if ultimo is not None:
            updates["whatsapp_enviado"] = True
            updates["whatsapp_enviado_em"] = ultimo
        item = item.model_copy(update=updates)
        out.append(item)
    return out


@router.post("", response_model=ContaReceberOut, status_code=status.HTTP_201_CREATED)
def criar(
    payload: ContaReceberCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> ContaReceber:
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
        _gerar_todas_comissoes_recebimento(db, conta)
    elif status_solicitado == StatusContaReceber.VENCIDO:
        conta.status = StatusContaReceber.VENCIDO

    depois = snapshot_campos(conta, CAMPOS_CONTA)
    registrar_historico_edicao(
        db,
        request,
        "conta_receber",
        conta.id,
        acao="cadastro",
        campos_depois=depois,
        campos_tracked=CAMPOS_CONTA,
    )
    db.commit()
    db.refresh(conta)
    return conta


@router.post("/importar-csv-bling", response_model=ContaReceberImportCsvBlingOut)
async def importar_csv_bling(
    arquivo: UploadFile = File(...),
    categoria_id: Optional[int] = Form(default=None),
    centro_custos_id: Optional[int] = Form(default=None),
    db: Session = Depends(get_db),
) -> ContaReceberImportCsvBlingOut:
    raw = await arquivo.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
    try:
        out = importar_contas_receber_csv_bling(
            db,
            raw,
            categoria_id=categoria_id,
            centro_custos_id=centro_custos_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ContaReceberImportCsvBlingOut(**out)


@router.post("/importar-retorno-sicoob/preview", response_model=ContaReceberPreviewRetornoSicoobOut)
async def preview_retorno_sicoob(
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> ContaReceberPreviewRetornoSicoobOut:
    raw = await arquivo.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
    try:
        out = preview_retorno_sicoob_receber(db, raw)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ContaReceberPreviewRetornoSicoobOut(**out)


@router.post("/importar-retorno-sicoob/aplicar", response_model=ContaReceberImportRetornoSicoobOut)
async def aplicar_retorno_sicoob(
    arquivo: UploadFile = File(...),
    conta_destino_id: int = Form(...),
    confirmar_conta_ids_json: str = Form(default="[]"),
    db: Session = Depends(get_db),
) -> ContaReceberImportRetornoSicoobOut:
    raw = await arquivo.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
    import json

    try:
        ids_raw = json.loads(confirmar_conta_ids_json or "[]")
        confirmar_ids = [int(x) for x in ids_raw if int(x) > 0]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirmar_conta_ids_json invalido.",
        ) from exc
    if not confirmar_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum titulo selecionado para baixar.",
        )
    try:
        out = aplicar_retorno_sicoob_receber(
            db,
            raw,
            conta_destino_id=int(conta_destino_id),
            confirmar_conta_ids=confirmar_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # Comissao: mesma regra do recebimento manual.
    try:
        for det in (out.get("detalhes") or []):
            if det.get("status") != "baixado":
                continue
            cid = int(det.get("conta_id") or 0)
            if not cid:
                continue
            conta = db.get(ContaReceber, cid)
            if conta:
                _gerar_todas_comissoes_recebimento(db, conta)
        db.commit()
    except Exception:
        db.rollback()
    return ContaReceberImportRetornoSicoobOut(**out)


@router.post("/importar-retorno-sicoob", response_model=ContaReceberImportRetornoSicoobOut)
async def importar_retorno_sicoob(
    arquivo: UploadFile = File(...),
    conta_destino_id: int = Form(...),
    db: Session = Depends(get_db),
) -> ContaReceberImportRetornoSicoobOut:
    raw = await arquivo.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
    try:
        out = importar_retorno_sicoob_baixar_receber(db, raw, conta_destino_id=int(conta_destino_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ContaReceberImportRetornoSicoobOut(**out)


@router.post("/boletos-asaas-lote", response_model=ContaReceberBoletosAsaasLoteOut)
def emitir_boletos_asaas_lote(
    payload: ContaReceberBoletosAsaasLoteIn, db: Session = Depends(get_db)
) -> ContaReceberBoletosAsaasLoteOut:
    if not payload.conta_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe ao menos uma conta (conta_ids).")
    if len(payload.conta_ids) > 500:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Limite de 500 contas por lote.")
    vistos: set[int] = set()
    falhas: list[ContaReceberBoletoLoteFalha] = []
    sucesso = 0
    for raw_id in payload.conta_ids:
        if raw_id in vistos:
            continue
        vistos.add(int(raw_id))
        try:
            conta = db.get(ContaReceber, int(raw_id))
            if not conta:
                falhas.append(ContaReceberBoletoLoteFalha(conta_id=int(raw_id), detail="Conta nao encontrada."))
                continue
            if not conta.cliente_id:
                falhas.append(
                    ContaReceberBoletoLoteFalha(conta_id=int(raw_id), detail="Conta sem cliente; associe cliente com CPF/CNPJ.")
                )
                continue
            cliente = _garantir_cliente(db, int(conta.cliente_id))
            if not cliente:
                falhas.append(ContaReceberBoletoLoteFalha(conta_id=int(conta.id), detail="Cliente invalido ou nao cadastrado."))
                continue
            asaas_service.emitir_ou_atualizar_boleto(db, conta, cliente)
            db.commit()
            sucesso += 1
        except HTTPException as exc:
            db.rollback()
            det = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            falhas.append(ContaReceberBoletoLoteFalha(conta_id=int(raw_id), detail=det))
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            falhas.append(ContaReceberBoletoLoteFalha(conta_id=int(raw_id), detail=str(exc)[:500]))
    return ContaReceberBoletosAsaasLoteOut(sucesso=sucesso, falhas=falhas)


def _url_boleto_asaas_segura(url: str, conta_id: int) -> str:
    u = (url or "").strip()
    if not u.startswith("https://"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Conta #{conta_id}: URL do boleto invalida (somente HTTPS).")
    host = (urlparse(u).hostname or "").lower()
    if "asaas.com" not in host:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Conta #{conta_id}: URL do boleto nao reconhecida como Asaas.")
    return u


@router.post("/boletos-asaas-pdf-junto")
def boletos_asaas_pdf_junto(payload: ContaReceberBoletosPdfMergeIn, db: Session = Depends(get_db)) -> Response:
    if not payload.conta_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe ao menos uma conta (conta_ids).")
    if len(payload.conta_ids) > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Limite de 200 contas por PDF unificado.")
    vistos: set[int] = set()
    pares: list[tuple[int, str]] = []
    for raw_id in payload.conta_ids:
        cid = int(raw_id)
        if cid in vistos:
            continue
        vistos.add(cid)
        conta = db.get(ContaReceber, cid)
        if not conta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conta #{cid} nao encontrada.")
        raw_url = (conta.asaas_boleto_url or "").strip()
        if not raw_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Conta #{cid} sem PDF de boleto; gere o boleto antes de unificar.")
        pares.append((cid, _url_boleto_asaas_segura(raw_url, cid)))
    writer = PdfWriter()
    for cid, url in pares:
        try:
            r = requests.get(url, timeout=120, headers={"User-Agent": "OnixSystem/1.0 (boletos-pdf-junto)"})
            r.raise_for_status()
        except requests.RequestException as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Falha ao baixar PDF da conta #{cid}: {str(exc)[:400]}") from exc
        head = r.content[:5] if r.content else b""
        if not r.content or not head.startswith(b"%PDF"):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Resposta da conta #{cid} nao parece ser um PDF.")
        try:
            reader = PdfReader(BytesIO(r.content), strict=False)
            for page in reader.pages:
                writer.add_page(page)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Falha ao ler PDF da conta #{cid}: {str(exc)[:400]}") from exc
    out = BytesIO()
    writer.write(out)
    pdf_bytes = out.getvalue()
    if not pdf_bytes:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="PDF resultante vazio.")
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="boletos-asaas-junto.pdf"'})


@router.post("/enviar-boletos-email-lote", response_model=ContaReceberEnviarBoletosEmailLoteOut)
def enviar_boletos_email_lote(
    body: ContaReceberEnviarBoletosEmailLoteIn,
    db: Session = Depends(get_db),
) -> ContaReceberEnviarBoletosEmailLoteOut:
    res = enviar_boletos_contas_receber_lote_por_email(
        db,
        conta_ids=body.conta_ids,
        destinatario_override=body.destinatario,
        notificar_whatsapp=body.notificar_whatsapp,
    )
    return ContaReceberEnviarBoletosEmailLoteOut(**res)


@router.get("/{conta_id}", response_model=ContaReceberOut)
def buscar(conta_id: int, db: Session = Depends(get_db)) -> ContaReceber:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    return conta


@router.put("/{conta_id}", response_model=ContaReceberOut)
def atualizar(
    conta_id: int,
    payload: ContaReceberUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> ContaReceber:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    antes = snapshot_campos(conta, CAMPOS_CONTA)
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(conta, campo, valor)
    if conta.status == StatusContaReceber.RECEBIDO and not conta.comissao_gerada:
        _gerar_todas_comissoes_recebimento(db, conta)
    depois = snapshot_campos(conta, CAMPOS_CONTA)
    registrar_historico_edicao(
        db,
        request,
        "conta_receber",
        conta_id,
        acao="edicao",
        campos_antes=antes,
        campos_depois=depois,
        campos_tracked=CAMPOS_CONTA,
    )
    db.commit()
    db.refresh(conta)
    return conta


@router.post("/simular-recebimento", response_model=ContaReceberSimularRecebimentoOut)
def simular_recebimento_contas(
    body: ContaReceberSimularRecebimentoIn = Body(...),
    db: Session = Depends(get_db),
) -> ContaReceberSimularRecebimentoOut:
    """Calcula multa/juros de atraso para a data de baixa informada."""
    from sga_financeiro.services.encargos_atraso_service import calcular_encargos_da_conta_receber

    itens: list[ContaReceberSimularRecebimentoItemOut] = []
    tot_p = tot_m = tot_j = tot_d = Decimal("0")
    for cid in body.conta_ids:
        conta = db.get(ContaReceber, int(cid))
        if not conta:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conta a receber {cid} nao encontrada.",
            )
        if conta.status == StatusContaReceber.RECEBIDO:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Conta {cid} ja foi recebida.",
            )
        enc = calcular_encargos_da_conta_receber(
            conta,
            data_recebimento=body.data_recebimento,
            perdoar_multa=bool(body.perdoar_multa),
            perdoar_juros=bool(body.perdoar_juros),
        )
        itens.append(
            ContaReceberSimularRecebimentoItemOut(
                conta_id=int(conta.id),
                valor_principal=enc["valor_principal"],
                dias_atraso=int(enc["dias_atraso"]),
                multa=enc["multa"],
                juros=enc["juros"],
                total_devido=enc["total_devido"],
                vencida=bool(enc["vencida"]),
                multa_percent=enc.get("multa_percent"),
                juros_percent_dia=enc.get("juros_percent_dia"),
                valor_original=enc.get("valor_original"),
                juros_acumulados=enc.get("juros_acumulados"),
                juros_novos=enc.get("juros_novos"),
                multa_fixada=bool(enc.get("multa_fixada")),
            )
        )
        tot_p += enc["valor_principal"]
        tot_m += enc["multa"]
        tot_j += enc["juros"]
        tot_d += enc["total_devido"]
    return ContaReceberSimularRecebimentoOut(
        itens=itens,
        total_principal=tot_p.quantize(Decimal("0.01")),
        total_multa=tot_m.quantize(Decimal("0.01")),
        total_juros=tot_j.quantize(Decimal("0.01")),
        total_devido=tot_d.quantize(Decimal("0.01")),
    )


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
        valor_recebido=payload.valor_recebido,
        perdoar_multa=bool(payload.perdoar_multa),
        perdoar_juros=bool(payload.perdoar_juros),
    )
    if conta.status == StatusContaReceber.RECEBIDO:
        _gerar_todas_comissoes_recebimento(db, conta)
    db.commit()
    db.refresh(conta)
    return conta


@router.post("/{conta_id}/boleto-asaas", response_model=ContaReceberBoletoAsaasOut)
def emitir_boleto_asaas(
    conta_id: int,
    body: ContaReceberBoletoAsaasIn = Body(default_factory=ContaReceberBoletoAsaasIn),
    db: Session = Depends(get_db),
) -> ContaReceberBoletoAsaasOut:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    if not conta.cliente_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conta sem cliente. Associe um cliente com CPF ou CNPJ antes de emitir boleto.")
    cliente = _garantir_cliente(db, int(conta.cliente_id))
    if not cliente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cliente invalido ou nao cadastrado. Verifique o cadastro (marcado como cliente).")
    extra = (body.texto_extra_boleto or "").strip() or None
    if extra:
        extra = extra[:500]
    asaas_service.emitir_ou_atualizar_boleto(db, conta, cliente, texto_extra=extra)
    db.commit()
    db.refresh(conta)
    return ContaReceberBoletoAsaasOut(conta=conta, mensagem="Boleto registrado no Asaas.")


@router.post("/{conta_id}/pix-asaas", response_model=ContaReceberPixAsaasOut)
def emitir_pix_asaas(
    conta_id: int,
    body: ContaReceberPixAsaasIn = Body(default_factory=ContaReceberPixAsaasIn),
    db: Session = Depends(get_db),
) -> ContaReceberPixAsaasOut:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    if not conta.cliente_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conta sem cliente. Associe um cliente com CPF ou CNPJ antes de emitir PIX.")
    cliente = _garantir_cliente(db, int(conta.cliente_id))
    if not cliente:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cliente invalido ou nao cadastrado. Verifique o cadastro (marcado como cliente).")
    extra = (body.texto_extra_pix or "").strip() or None
    if extra:
        extra = extra[:500]
    asaas_service.emitir_ou_atualizar_pix(db, conta, cliente, texto_extra=extra)
    db.commit()
    db.refresh(conta)
    return ContaReceberPixAsaasOut(conta=conta, mensagem="PIX registrado no Asaas.")


@router.post("/{conta_id}/enviar-pix-whatsapp", response_model=ContaReceberEnviarPixWhatsappOut)
def enviar_pix_whatsapp_conta(conta_id: int, db: Session = Depends(get_db)) -> ContaReceberEnviarPixWhatsappOut:
    ret = enviar_pix_conta_receber_whatsapp(db, conta_id=int(conta_id))
    return ContaReceberEnviarPixWhatsappOut(
        conta_id=int(ret.get("conta_id") or conta_id),
        whatsapp_tentado=bool(ret.get("whatsapp_tentado")),
        whatsapp_enviado=bool(ret.get("whatsapp_enviado")),
        whatsapp_detalhe=str(ret.get("whatsapp_detalhe") or ""),
    )


@router.get("/{conta_id}/historico-lembrete-whatsapp")
def historico_lembrete_whatsapp_conta(conta_id: int, db: Session = Depends(get_db)) -> dict:
    itens = listar_historico_lembrete_whatsapp_conta(db, conta_id=int(conta_id))
    return {"conta_id": int(conta_id), "itens": itens}


@router.get("/{conta_id}/extrato-divida")
def extrato_divida_conta_receber(conta_id: int, db: Session = Depends(get_db)) -> dict:
    """Extrato da divida: situacao atual + historico de recebimentos parciais/totais."""
    from sga_financeiro.services.conta_receber_extrato_service import montar_extrato_divida

    return montar_extrato_divida(db, int(conta_id))


@router.post("/{conta_id}/enviar-lembrete-whatsapp", response_model=ContaReceberEnviarPixWhatsappOut)
def enviar_lembrete_whatsapp_conta(conta_id: int, db: Session = Depends(get_db)) -> ContaReceberEnviarPixWhatsappOut:
    ret = enviar_lembrete_pagamento_conta_whatsapp(db, conta_id=int(conta_id))
    return ContaReceberEnviarPixWhatsappOut(
        conta_id=int(ret.get("conta_id") or conta_id),
        whatsapp_tentado=bool(ret.get("whatsapp_tentado")),
        whatsapp_enviado=bool(ret.get("whatsapp_enviado")),
        whatsapp_detalhe=str(ret.get("whatsapp_detalhe") or ""),
    )


@router.post("/{conta_id}/sincronizar-asaas", response_model=ContaReceberBoletoAsaasOut)
def sincronizar_boleto_asaas(conta_id: int, db: Session = Depends(get_db)) -> ContaReceberBoletoAsaasOut:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    pay_id = str(conta.asaas_payment_id or "").strip()
    if not pay_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta conta nao possui ID de pagamento Asaas.")
    if not effective_asaas_runtime().get("enabled"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Integracao Asaas nao esta habilitada.")
    pay = asaas_service.obter_pagamento(pay_id)
    antes = conta.status
    asaas_service.aplicar_webhook_payment(db, pay)
    db.commit()
    db.refresh(conta)
    st_asaas = str(conta.asaas_status or pay.get("status") or "").upper()
    if conta.status == StatusContaReceber.RECEBIDO and antes != StatusContaReceber.RECEBIDO:
        msg = "Pagamento recebido no Asaas e conta baixada automaticamente."
    elif conta.status == StatusContaReceber.RECEBIDO:
        msg = "Pagamento ja estava baixado no sistema."
    elif st_asaas == "RECEIVED":
        msg = "Pagamento esta recebido no Asaas, mas nao foi possivel baixar automaticamente. Verifique a conta corrente configurada no webhook Asaas."
    elif st_asaas == "CONFIRMED":
        msg = "Status Asaas atualizado: CONFIRMED. A baixa automatica sera feita apenas quando o Asaas retornar RECEIVED."
    else:
        msg = f"Status Asaas atualizado: {st_asaas or 'indefinido'}."
    return ContaReceberBoletoAsaasOut(conta=conta, mensagem=msg)


@router.post("/{conta_id}/enviar-boleto-email", response_model=ContaReceberEnviarBoletoEmailOut)
def enviar_boleto_email(
    conta_id: int,
    body: ContaReceberEnviarBoletoEmailIn = Body(default_factory=ContaReceberEnviarBoletoEmailIn),
    db: Session = Depends(get_db),
) -> ContaReceberEnviarBoletoEmailOut:
    res = enviar_boleto_conta_receber_por_email(
        db,
        conta_id=conta_id,
        destinatario_override=body.destinatario,
        notificar_whatsapp=body.notificar_whatsapp,
    )
    return ContaReceberEnviarBoletoEmailOut(**res)


@router.post("/{conta_id}/cancelar-asaas", response_model=ContaReceberCancelarAsaasOut)
def cancelar_asaas(conta_id: int, db: Session = Depends(get_db)) -> ContaReceberCancelarAsaasOut:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    if conta.venda_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conta vinculada a pedido. Use Estornar financeiro no pedido para cancelar cobrancas Asaas.",
        )
    if conta.status == StatusContaReceber.RECEBIDO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Conta ja recebida. Nao e possivel cancelar cobranca Asaas.",
        )
    ret = cancelar_cobranca_asaas_conta(db, conta)
    db.commit()
    db.refresh(conta)
    return ContaReceberCancelarAsaasOut(
        ok=True,
        conta_id=int(conta.id),
        cancelado=bool(ret.get("cancelado")),
        mensagem=str(ret.get("mensagem") or "Cobranca cancelada no Asaas."),
        payment_id=str(ret.get("payment_id") or "") or None,
        status_anterior=str(ret.get("status_anterior") or "") or None,
    )


@router.post("/{conta_id}/estornar", response_model=dict)
def estornar(conta_id: int, db: Session = Depends(get_db)) -> dict:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    estornar_recebimento_conta_receber(db, conta)
    db.commit()
    db.refresh(conta)
    return {
        "ok": True,
        "conta_id": int(conta.id),
        "status": str(conta.status),
        "mensagem": f"Estorno concluido. Conta #{conta.id} voltou para {str(conta.status).lower()}.",
    }


@router.delete("/{conta_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(conta_id: int, db: Session = Depends(get_db)) -> None:
    conta = db.get(ContaReceber, conta_id)
    if not conta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conta a receber nao encontrada.")
    db.delete(conta)
    db.commit()
