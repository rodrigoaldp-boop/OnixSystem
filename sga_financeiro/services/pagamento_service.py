"""Regras de negocio para baixa de contas e pagamento de fatura."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, delete, extract, func, or_, select
from sqlalchemy.orm import Session

from sga_financeiro.models.comissao_lancamento import ComissaoLancamento
from sga_financeiro.models.cartao_credito import CartaoCredito
from sga_financeiro.models.conta_corrente import ContaCorrente
from sga_financeiro.models.conta_pagar import ContaPagar, StatusContaPagar
from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.models.fatura_cartao import FaturaCartao, StatusFatura
from sga_financeiro.services.conta_service import creditar_conta, debitar_conta
from sga_financeiro.services.exclusao_historico_service import remover_movimentacoes_por_referencias


def _status_aberto_apos_estorno(data_vencimento: date) -> StatusContaPagar:
    if data_vencimento < date.today():
        return StatusContaPagar.VENCIDO
    return StatusContaPagar.PENDENTE


def _status_receber_aberto_apos_estorno(data_vencimento: date) -> StatusContaReceber:
    if data_vencimento < date.today():
        return StatusContaReceber.VENCIDO
    return StatusContaReceber.PENDENTE


def _ultimo_dia_mes(year: int, month: int) -> int:
    if month == 12:
        primeiro_proximo_mes = date(year + 1, 1, 1)
    else:
        primeiro_proximo_mes = date(year, month + 1, 1)
    return (primeiro_proximo_mes - timedelta(days=1)).day


def _data_com_dia_seguro(year: int, month: int, dia: int) -> date:
    ultimo = _ultimo_dia_mes(year, month)
    return date(year, month, min(dia, ultimo))


def referencia_fatura_para_compra(data_compra: date, dia_fechamento: int) -> tuple[str, date]:
    """
    Mes de referencia = mes em que a fatura FECHA.
    Compra apos o dia de fechamento entra no ciclo que fecha no mes seguinte.
    """
    y, m = data_compra.year, data_compra.month
    if data_compra.day > dia_fechamento:
        if m == 12:
            m, y = 1, y + 1
        else:
            m += 1
    dia_f = min(dia_fechamento, _ultimo_dia_mes(y, m))
    return f"{m:02d}/{y}", date(y, m, dia_f)


def data_vencimento_prevista_fatura(
    mes_referencia: str,
    dia_vencimento_cartao: int,
    dia_fechamento_cartao: int | None = None,
) -> date:
    """
    Vencimento previsto da fatura.
    Se o dia de vencimento for menor que o de fechamento (ex.: vence dia 7, fecha dia 28),
    o pagamento cai no mes seguinte ao mes de referencia (fechamento).
    """
    parts = mes_referencia.strip().split("/")
    if len(parts) != 2:
        raise ValueError("mes_referencia invalido")
    m, y = int(parts[0]), int(parts[1])
    dv = int(dia_vencimento_cartao or 10)
    df = int(dia_fechamento_cartao or 0)
    if df and dv < df:
        if m == 12:
            m, y = 1, y + 1
        else:
            m += 1
    return _data_com_dia_seguro(y, m, dv)


def primeiro_vencimento_fatura_cartao(data_compra: date, dia_fechamento: int, dia_vencimento: int) -> date:
    """
    Vencimento da fatura que recebera a compra.

    Ex.: fechamento 10, vencimento 18, compra 13/05 -> fecha 10/06 -> vence 18/06.
    Ex.: fechamento 28, vencimento 7, compra 15/05 -> fecha 28/05 -> vence 07/06.
    """
    mes_ref, data_fech = referencia_fatura_para_compra(data_compra, dia_fechamento)
    return data_vencimento_prevista_fatura(
        mes_ref,
        int(dia_vencimento),
        int(dia_fechamento),
    )


def baixar_conta_pagar(
    db: Session,
    conta_pagar: ContaPagar,
    conta_corrente: ContaCorrente,
    data_pagamento: Optional[date] = None,
    comprovante_url: Optional[str] = None,
) -> ContaPagar:
    """Marca conta a pagar como paga e registra debito pendente de conciliacao."""
    if conta_pagar.status == StatusContaPagar.PAGO:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conta ja esta paga.")
    if conta_pagar.cartao_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Lancamento no cartao de credito nao pode ser baixado manualmente. "
                "Quite pela fatura em Faturas — ao pagar a fatura, as contas vinculadas sao baixadas automaticamente."
            ),
        )

    debitar_conta(
        db=db,
        conta=conta_corrente,
        valor=conta_pagar.valor,
        descricao=f"Pagamento: {conta_pagar.descricao}",
        referencia=f"conta_pagar:{conta_pagar.id}",
        conciliar_imediatamente=False,
    )
    conta_pagar.status = StatusContaPagar.PAGO
    conta_pagar.data_pagamento = data_pagamento or date.today()
    conta_pagar.conta_destino_id = conta_corrente.id
    if comprovante_url is not None:
        conta_pagar.comprovante_url = comprovante_url
    return conta_pagar


def receber_conta_receber(
    db: Session,
    conta_receber: ContaReceber,
    conta_corrente: ContaCorrente,
    data_recebimento: Optional[date] = None,
    comprovante_url: Optional[str] = None,
    taxa_gateway_recebimento: Optional[Decimal] = None,
    valor_recebido: Optional[Decimal] = None,
    perdoar_multa: bool = False,
    perdoar_juros: bool = False,
    data_encargos: Optional[date] = None,
) -> ContaReceber:
    """Marca conta a receber como recebida e registra credito pendente de conciliacao.

    taxa_gateway_recebimento: quando informado (>0), registra um debito na mesma conta corrente
    (ex.: taxa Asaas por boleto/PIX), referenciado junto ao credito, para o saldo liquido bater com o Asaas.

    valor_recebido: credito na conta corrente; se menor que o total devido, baixa parcial:
      - abate primeiro o principal;
      - multa integral permanece congelada (sobre o principal original);
      - juros ja corridos ficam acumulados; da data da baixa em diante, juros so sobre o restante.
    perdoar_multa / perdoar_juros: nao soma o encargo correspondente ao total devido.
    """
    from sga_financeiro.models.movimentacao import Movimentacao, TipoMovimentacao
    from sga_financeiro.services.conta_receber_extrato_service import registrar_evento_recebimento
    from sga_financeiro.services.encargos_atraso_service import calcular_encargos_da_conta_receber

    if conta_receber.status == StatusContaReceber.RECEBIDO:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Conta ja foi recebida.")

    data_rec = data_recebimento or date.today()
    data_calc_encargos = data_encargos or data_rec
    enc = calcular_encargos_da_conta_receber(
        conta_receber,
        data_recebimento=data_calc_encargos,
        perdoar_multa=bool(perdoar_multa),
        perdoar_juros=bool(perdoar_juros),
    )
    total_devido = Decimal(enc["total_devido"])
    principal = Decimal(enc["valor_principal"])
    multa = Decimal(enc.get("multa") or 0)
    juros = Decimal(enc.get("juros") or 0)
    principal_antes = principal
    multa_antes = multa
    juros_antes = juros
    total_antes = total_devido
    abate_prin = Decimal("0.00")
    abate_juros = Decimal("0.00")
    abate_multa = Decimal("0.00")
    principal_depois = principal
    multa_depois = multa
    juros_depois = juros
    total_depois = total_devido
    tipo_evento = "total"
    try:
        vr = (
            Decimal(str(valor_recebido)).quantize(Decimal("0.01"))
            if valor_recebido is not None
            else total_devido
        )
    except Exception:
        vr = total_devido
    if vr <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valor recebido deve ser maior que zero.",
        )
    if vr > total_devido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Valor recebido ({vr}) nao pode ser maior que o total devido ({total_devido}).",
        )

    tol = Decimal("0.01")
    recebimento_total = vr + tol >= total_devido

    # Referencia unica por credito: parcial pode ocorrer varias vezes na mesma conta.
    n_creds = db.execute(
        select(Movimentacao.id).where(
            Movimentacao.referencia.like(f"conta_receber:{conta_receber.id}%"),
            Movimentacao.tipo == TipoMovimentacao.CREDITO,
        )
    ).all()
    seq = len(n_creds) + 1
    if recebimento_total and seq == 1:
        ref = f"conta_receber:{conta_receber.id}"
    else:
        ref = f"conta_receber:{conta_receber.id}:rec:{seq}"

    # Idempotencia so para recebimento total "simples" (mesmo ref classico).
    if ref == f"conta_receber:{conta_receber.id}":
        ja_credito = db.execute(
            select(Movimentacao.id).where(
                Movimentacao.referencia == ref,
                Movimentacao.tipo == TipoMovimentacao.CREDITO,
            ).limit(1)
        ).scalar_one_or_none()
        if ja_credito:
            conta_receber.status = StatusContaReceber.RECEBIDO
            if not conta_receber.data_recebimento:
                conta_receber.data_recebimento = data_rec
            if not conta_receber.conta_destino_id:
                conta_receber.conta_destino_id = conta_corrente.id
            return conta_receber

    creditar_conta(
        db=db,
        conta=conta_corrente,
        valor=vr,
        descricao=f"Recebimento: {conta_receber.descricao}",
        referencia=ref,
        conciliar_imediatamente=False,
    )
    if taxa_gateway_recebimento is not None:
        try:
            taxa = Decimal(str(taxa_gateway_recebimento)).quantize(Decimal("0.01"))
        except Exception:
            taxa = Decimal("0")
        bruto = vr.quantize(Decimal("0.01"))
        if taxa > 0 and bruto > 0:
            taxa = min(taxa, bruto)
            base_desc = (conta_receber.descricao or "").strip()
            if len(base_desc) > 180:
                base_desc = base_desc[:177] + "..."
            taxa_txt = "Taxa Asaas (boleto/PIX)"
            desc_taxa = f"{taxa_txt} — {base_desc}" if base_desc else taxa_txt
            if len(desc_taxa) > 255:
                desc_taxa = desc_taxa[:252] + "..."
            debitar_conta(
                db=db,
                conta=conta_corrente,
                valor=taxa,
                descricao=desc_taxa,
                referencia=ref,
                conciliar_imediatamente=False,
            )

    obs_extra = ""
    if not recebimento_total:
        tipo_evento = "parcial"
        # Abate principal primeiro; sobra vai para juros e depois multa.
        resto = vr
        abate_prin = min(resto, principal)
        resto = (resto - abate_prin).quantize(Decimal("0.01"))
        abate_juros = min(resto, juros)
        resto = (resto - abate_juros).quantize(Decimal("0.01"))
        abate_multa = min(resto, multa)

        novo_principal = (principal - abate_prin).quantize(Decimal("0.01"))
        juros_restantes = (juros - abate_juros).quantize(Decimal("0.01"))
        multa_restante = (multa - abate_multa).quantize(Decimal("0.01"))

        if getattr(conta_receber, "valor_original", None) is None:
            conta_receber.valor_original = principal
        # Multa integral congelada (nao recalcula % sobre o restante).
        if not perdoar_multa:
            conta_receber.multa_fixada = multa_restante
        else:
            conta_receber.multa_fixada = Decimal("0.00")

        conta_receber.valor = novo_principal
        conta_receber.juros_acumulados = juros_restantes if not perdoar_juros else Decimal("0.00")
        conta_receber.juros_apos_data = data_rec
        conta_receber.status = (
            StatusContaReceber.VENCIDO
            if conta_receber.data_vencimento < date.today()
            else StatusContaReceber.PENDENTE
        )
        conta_receber.data_recebimento = None
        conta_receber.conta_destino_id = None
        saldo_total = (novo_principal + Decimal(conta_receber.multa_fixada or 0) + juros_restantes).quantize(
            Decimal("0.01")
        )
        principal_depois = novo_principal
        multa_depois = Decimal(conta_receber.multa_fixada or 0)
        juros_depois = juros_restantes if not perdoar_juros else Decimal("0.00")
        total_depois = saldo_total
        obs_extra = (
            f"Recebimento parcial R$ {vr} em {data_rec.isoformat()} "
            f"(principal R$ {abate_prin}"
            f"{f', juros R$ {abate_juros}' if abate_juros else ''}"
            f"{f', multa R$ {abate_multa}' if abate_multa else ''}). "
            f"Restante: principal R$ {novo_principal}, multa R$ {conta_receber.multa_fixada or 0}, "
            f"juros R$ {juros_restantes} (total R$ {saldo_total})."
        )
    else:
        tipo_evento = "total"
        abate_prin = principal
        abate_juros = juros
        abate_multa = multa
        principal_depois = Decimal("0.00")
        multa_depois = Decimal("0.00")
        juros_depois = Decimal("0.00")
        total_depois = Decimal("0.00")
        conta_receber.status = StatusContaReceber.RECEBIDO
        conta_receber.data_recebimento = data_rec
        conta_receber.conta_destino_id = conta_corrente.id
        conta_receber.juros_acumulados = Decimal("0.00")
        partes_obs = []
        if enc.get("dias_atraso", 0) > 0:
            dias_atraso = enc.get("dias_atraso")
            if perdoar_multa and perdoar_juros:
                partes_obs.append("Multa e juros perdoados.")
            elif perdoar_multa:
                if juros > 0:
                    partes_obs.append(f"Multa perdoada. Juros R$ {juros} ({dias_atraso} dia(s) atraso).")
                else:
                    partes_obs.append("Multa perdoada.")
            elif perdoar_juros:
                if multa > 0:
                    partes_obs.append(f"Multa R$ {multa}. Juros perdoados.")
                else:
                    partes_obs.append("Juros perdoados.")
            elif multa > 0 or juros > 0:
                partes_obs.append(
                    f"Multa R$ {multa} + juros R$ {juros} ({dias_atraso} dia(s) atraso)."
                )
        if partes_obs:
            obs_extra = " ".join(partes_obs)

    if comprovante_url is not None or obs_extra:
        base = str(comprovante_url or conta_receber.comprovante_url or "").strip()
        if obs_extra:
            conta_receber.comprovante_url = f"{base} | {obs_extra}".strip(" |") if base else obs_extra
        elif comprovante_url is not None:
            conta_receber.comprovante_url = comprovante_url

    try:
        registrar_evento_recebimento(
            db,
            conta=conta_receber,
            tipo=tipo_evento,
            data_evento=data_rec,
            valor_recebido=vr,
            abate_principal=abate_prin,
            abate_juros=abate_juros,
            abate_multa=abate_multa,
            principal_antes=principal_antes,
            principal_depois=principal_depois,
            multa_antes=multa_antes,
            multa_depois=multa_depois,
            juros_antes=juros_antes,
            juros_depois=juros_depois,
            total_antes=total_antes,
            total_depois=total_depois,
            dias_atraso=int(enc.get("dias_atraso") or 0),
            conta_destino_id=int(conta_corrente.id),
            movimentacao_ref=ref,
            observacao=obs_extra or None,
        )
    except Exception:
        # Nao impede o recebimento se o historico falhar; log fica no worker/app.
        import logging

        logging.getLogger(__name__).exception(
            "Falha ao registrar evento de recebimento da conta %s", getattr(conta_receber, "id", "?")
        )

    _notificar_whatsapp_recebimento_conta(db, conta_receber, conta_corrente, vr, data_rec)
    return conta_receber


def _notificar_whatsapp_recebimento_conta(
    db: Session,
    conta_receber: ContaReceber,
    conta_corrente,
    valor: Decimal,
    data_rec: date,
) -> None:
    import logging

    log = logging.getLogger(__name__)
    try:
        from sga_financeiro.services.documentos_email_service import _nome_cliente_documento
        from sga_financeiro.services.mobile_despesa_whatsapp_alerta_service import notificar_alerta_recebimento

        cliente_nome = ""
        if conta_receber.cliente_id:
            cliente_nome = _nome_cliente_documento(db, int(conta_receber.cliente_id))
        conta_nome = str(
            getattr(conta_corrente, "nome", None)
            or getattr(conta_corrente, "banco", None)
            or f"Conta #{conta_corrente.id}"
        ).strip()
        ret = notificar_alerta_recebimento(
            gatilho="ao_receber_conta",
            conta_nome=conta_nome,
            descricao=str(conta_receber.descricao or ""),
            valor=valor,
            cliente=cliente_nome,
            data=data_rec.isoformat(),
            referencia=f"conta_receber:{conta_receber.id}",
            item_id=int(conta_receber.id),
        )
        if not ret.get("enviado"):
            log.warning(
                "Alerta WhatsApp recebimento nao enviado conta #%s: %s",
                conta_receber.id,
                ret.get("detalhe") or "sem detalhe",
            )
    except Exception:
        log.exception(
            "Falha alerta WhatsApp recebimento conta #%s",
            getattr(conta_receber, "id", "?"),
        )


def estornar_baixa_conta_pagar(db: Session, conta_pagar: ContaPagar) -> dict[str, int]:
    """Desfaz pagamento: remove movimentacoes bancarias e volta conta para pendente/vencido."""
    if conta_pagar.status != StatusContaPagar.PAGO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="So e possivel estornar conta com status pago.",
        )
    if conta_pagar.cartao_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Lancamento de cartao de credito quitado pela fatura nao pode ser estornado aqui. "
                "Use Faturas para desfazer o pagamento da fatura, se aplicavel."
            ),
        )

    ref = f"conta_pagar:{conta_pagar.id}"
    mov_rem, saldo_rev = remover_movimentacoes_por_referencias(db, [ref])
    conta_pagar.status = _status_aberto_apos_estorno(conta_pagar.data_vencimento)
    conta_pagar.data_pagamento = None
    conta_pagar.conta_destino_id = None
    return {"movimentacoes_removidas": mov_rem, "movimentacoes_saldo_revertido": saldo_rev}


def estornar_recebimento_conta_receber(db: Session, conta_receber: ContaReceber) -> dict[str, int]:
    """Desfaz recebimento: remove movimentacoes bancarias e volta conta para pendente/vencido."""
    if conta_receber.status != StatusContaReceber.RECEBIDO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="So e possivel estornar conta com status recebido.",
        )

    ref = f"conta_receber:{conta_receber.id}"
    mov_rem, saldo_rev = remover_movimentacoes_por_referencias(db, [ref])
    db.execute(delete(ComissaoLancamento).where(ComissaoLancamento.conta_receber_id == conta_receber.id))
    conta_receber.status = _status_receber_aberto_apos_estorno(conta_receber.data_vencimento)
    conta_receber.data_recebimento = None
    conta_receber.conta_destino_id = None
    conta_receber.comissao_gerada = False
    return {"movimentacoes_removidas": mov_rem, "movimentacoes_saldo_revertido": saldo_rev}


def referencia_fatura_para_vencimento(
    data_vencimento: date,
    dia_fechamento: int,
    dia_vencimento: int,
) -> tuple[str, date]:
    """
    Mes de referencia (fechamento) da fatura cujo vencimento previsto e data_vencimento.
    Inverso de data_vencimento_prevista_fatura.
    """
    y, m = data_vencimento.year, data_vencimento.month
    dv = int(dia_vencimento or 10)
    df = int(dia_fechamento or 10)
    if df and dv < df:
        if m == 1:
            m, y = 12, y - 1
        else:
            m -= 1
    mes_referencia = f"{m:02d}/{y}"
    data_fechamento = _data_com_dia_seguro(y, m, df)
    return mes_referencia, data_fechamento


def obter_ou_criar_fatura_por_vencimento(
    db: Session,
    cartao: CartaoCredito,
    data_vencimento: date,
) -> FaturaCartao:
    """Localiza ou cria fatura pelo vencimento previsto do lancamento (parcelas em meses distintos)."""
    mes_referencia, data_fechamento = referencia_fatura_para_vencimento(
        data_vencimento,
        int(cartao.data_fechamento),
        int(cartao.data_vencimento or 10),
    )
    fatura = db.execute(
        select(FaturaCartao).where(
            FaturaCartao.cartao_id == cartao.id,
            FaturaCartao.mes_referencia == mes_referencia,
        )
    ).scalar_one_or_none()
    if fatura:
        return fatura
    fatura = FaturaCartao(
        cartao_id=cartao.id,
        mes_referencia=mes_referencia,
        data_fechamento=data_fechamento,
        valor_total=0,
        status=StatusFatura.ABERTA,
    )
    db.add(fatura)
    db.flush()
    return fatura


def obter_ou_criar_fatura(db: Session, cartao: CartaoCredito, data_compra: date) -> FaturaCartao:
    """Cria uma fatura aberta do ciclo (mes de fechamento) se ela nao existir."""
    mes_referencia, data_fechamento = referencia_fatura_para_compra(
        data_compra, int(cartao.data_fechamento)
    )
    fatura = db.execute(
        select(FaturaCartao).where(
            FaturaCartao.cartao_id == cartao.id,
            FaturaCartao.mes_referencia == mes_referencia,
        )
    ).scalar_one_or_none()
    if fatura:
        return fatura

    fatura = FaturaCartao(
        cartao_id=cartao.id,
        mes_referencia=mes_referencia,
        data_fechamento=data_fechamento,
        valor_total=0,
        status=StatusFatura.ABERTA,
    )
    db.add(fatura)
    db.flush()
    return fatura


def vencimento_conta_na_fatura(
    fatura: FaturaCartao,
    cartao: CartaoCredito,
) -> date:
    """Vencimento do lancamento alinhado ao mes de referencia da fatura."""
    return data_vencimento_prevista_fatura(
        fatura.mes_referencia,
        int(cartao.data_vencimento or 10),
        int(cartao.data_fechamento or 10),
    )


def reassociar_lancamento_cartao_por_compra(
    db: Session,
    conta_pagar: ContaPagar,
    data_compra: date,
) -> None:
    """Atualiza data_compra, move para a fatura correta e recalcula o vencimento."""
    if not conta_pagar.cartao_id:
        return
    if conta_pagar.status == StatusContaPagar.PAGO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel alterar fatura de lancamento ja pago no cartao.",
        )
    cartao = db.get(CartaoCredito, int(conta_pagar.cartao_id))
    if not cartao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartao nao encontrado.")
    conta_pagar.data_compra = data_compra
    if conta_pagar.fatura_id:
        remover_lancamento_no_cartao(db, conta_pagar)
    adicionar_lancamento_no_cartao(db, conta_pagar, cartao)


def adicionar_lancamento_no_cartao(db: Session, conta_pagar: ContaPagar, cartao: CartaoCredito) -> None:
    """Acumula saldo usado do cartao e valor da fatura."""
    data_compra = conta_pagar.data_compra or conta_pagar.data_vencimento
    if not data_compra:
        data_compra = date.today()
    venc_informado = conta_pagar.data_vencimento
    usar_vencimento = bool(conta_pagar.data_compra and venc_informado)
    if usar_vencimento:
        fatura = obter_ou_criar_fatura_por_vencimento(db, cartao, venc_informado)
    else:
        fatura = obter_ou_criar_fatura(db, cartao, data_compra)
    adicionar_lancamento_na_fatura_fixa(
        db,
        conta_pagar,
        cartao,
        fatura,
        preservar_vencimento=usar_vencimento,
    )


def adicionar_lancamento_na_fatura_fixa(
    db: Session,
    conta_pagar: ContaPagar,
    cartao: CartaoCredito,
    fatura: FaturaCartao,
    *,
    preservar_vencimento: bool = False,
) -> None:
    """Vincula lancamento a uma fatura especifica (ex.: importacao OFX)."""
    conta_pagar.fatura_id = fatura.id
    conta_pagar.cartao_id = cartao.id
    if not preservar_vencimento:
        conta_pagar.data_vencimento = vencimento_conta_na_fatura(fatura, cartao)
    cartao.saldo_usado += conta_pagar.valor
    fatura.valor_total += conta_pagar.valor


def sincronizar_fatura_aberta(db: Session, fatura: FaturaCartao) -> bool:
    """
    Alinha valor_total aos lancamentos. Remove fatura aberta/fechada sem nenhum lancamento.
    Retorna True se a fatura foi excluida.
    """
    if fatura.status == StatusFatura.PAGA:
        return False
    total = db.execute(
        select(func.coalesce(func.sum(ContaPagar.valor), 0)).where(ContaPagar.fatura_id == fatura.id)
    ).scalar_one()
    qtd = db.execute(
        select(func.count()).select_from(ContaPagar).where(ContaPagar.fatura_id == fatura.id)
    ).scalar_one()
    if int(qtd or 0) == 0:
        db.delete(fatura)
        return True
    fatura.valor_total = Decimal(str(total or 0))
    return False


def limpar_faturas_abertas_inconsistentes(db: Session) -> int:
    """Remove ou recalcula faturas abertas sem lancamentos ou com valor desatualizado."""
    faturas = db.query(FaturaCartao).filter(FaturaCartao.status != StatusFatura.PAGA).all()
    removidas = 0
    for fatura in faturas:
        if sincronizar_fatura_aberta(db, fatura):
            removidas += 1
    return removidas


def remover_lancamento_no_cartao(db: Session, conta_pagar: ContaPagar) -> None:
    """Estorna um lançamento do cartão (ao excluir/alterar) e mantém fatura consistente."""
    if not conta_pagar.cartao_id:
        return
    cartao = db.get(CartaoCredito, conta_pagar.cartao_id)
    if cartao:
        cartao.saldo_usado -= conta_pagar.valor
        if cartao.saldo_usado < 0:
            cartao.saldo_usado = 0

    fatura: FaturaCartao | None = None
    if conta_pagar.fatura_id:
        fatura = db.get(FaturaCartao, conta_pagar.fatura_id)
    if fatura:
        sincronizar_fatura_aberta(db, fatura)


def pagar_fatura(
    db: Session,
    fatura: FaturaCartao,
    conta_corrente: ContaCorrente,
    data_pagamento: Optional[date] = None,
) -> FaturaCartao:
    """Paga fatura do cartao, debita conta e baixa contas vinculadas do mesmo mes."""
    if fatura.status == StatusFatura.PAGA:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fatura ja esta paga.")

    debitar_conta(
        db=db,
        conta=conta_corrente,
        valor=fatura.valor_total,
        descricao=f"Pagamento fatura cartao {fatura.cartao_id} - {fatura.mes_referencia}",
        referencia=f"fatura:{fatura.id}",
        conciliar_imediatamente=False,
    )

    month, year = fatura.mes_referencia.split("/")
    contas = db.execute(
        select(ContaPagar).where(
            ContaPagar.cartao_id == fatura.cartao_id,
            ContaPagar.status.in_([StatusContaPagar.PENDENTE, StatusContaPagar.VENCIDO]),
            or_(
                ContaPagar.fatura_id == fatura.id,
                and_(
                    ContaPagar.fatura_id.is_(None),
                    extract("month", ContaPagar.data_vencimento) == int(month),
                    extract("year", ContaPagar.data_vencimento) == int(year),
                ),
            ),
        )
    ).scalars()
    for conta in contas:
        conta.status = StatusContaPagar.PAGO
        conta.data_pagamento = data_pagamento or date.today()
        conta.conta_destino_id = conta_corrente.id

    cartao = db.get(CartaoCredito, fatura.cartao_id)
    if cartao:
        cartao.saldo_usado -= fatura.valor_total
        if cartao.saldo_usado < 0:
            cartao.saldo_usado = 0

    fatura.status = StatusFatura.PAGA
    fatura.data_pagamento = data_pagamento or date.today()
    return fatura


def transferir_lancamento_para_fatura(
    db: Session,
    conta_pagar: ContaPagar,
    fatura_destino: FaturaCartao,
) -> ContaPagar:
    """Move um lancamento de uma fatura aberta para outra do mesmo cartao."""
    if not conta_pagar.cartao_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Lancamento nao esta vinculado a cartao de credito.",
        )
    if int(fatura_destino.cartao_id) != int(conta_pagar.cartao_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A fatura de destino deve ser do mesmo cartao.",
        )
    if fatura_destino.status == StatusFatura.PAGA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel mover lancamento para fatura ja paga.",
        )
    if conta_pagar.status == StatusContaPagar.PAGO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel mover lancamento ja pago.",
        )
    if conta_pagar.fatura_id == fatura_destino.id:
        return conta_pagar

    cartao = db.get(CartaoCredito, int(conta_pagar.cartao_id))
    if not cartao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cartao nao encontrado.")

    remover_lancamento_no_cartao(db, conta_pagar)
    conta_pagar.fatura_id = fatura_destino.id
    fatura_destino.valor_total += conta_pagar.valor
    conta_pagar.data_vencimento = vencimento_conta_na_fatura(fatura_destino, cartao)
    return conta_pagar


def listar_contas_vinculadas_fatura(db: Session, fatura: FaturaCartao) -> list[ContaPagar]:
    """Todos os lancamentos no cartao ligados a esta fatura (por fatura_id ou mes de vencimento)."""
    month, year = fatura.mes_referencia.split("/")
    rows = db.execute(
        select(ContaPagar)
        .where(
            ContaPagar.cartao_id == fatura.cartao_id,
            or_(
                ContaPagar.fatura_id == fatura.id,
                and_(
                    ContaPagar.fatura_id.is_(None),
                    extract("month", ContaPagar.data_vencimento) == int(month),
                    extract("year", ContaPagar.data_vencimento) == int(year),
                ),
            ),
        )
        .order_by(ContaPagar.data_vencimento.asc(), ContaPagar.id.asc())
    ).scalars()
    return list(rows)
