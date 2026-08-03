"""Faturamento automatico de mensalistas (RENT/TENT/MENSALISTA) N dias antes do vencimento."""

from __future__ import annotations

import calendar
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from sga_financeiro.database import SessionLocal
from sga_financeiro.email_documentos_config import smtp_documentos_configurado
from sga_financeiro.models.cadastro_geral import CadastroGeral
from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.routes.cadastros import (
    _criar_venda_de_cadastro_info,
    _proxima_data_por_dia_vencimento,
)
from sga_financeiro.routes.vendas import _gerar_financeiro_da_venda
from sga_financeiro.services import asaas_service
from sga_financeiro.cobrancas_config import effective_asaas_runtime
from sga_financeiro.services.documentos_email_service import (
    enviar_lembrete_pagamento_conta_email,
    enviar_lembrete_pagamento_conta_whatsapp,
)
from sga_financeiro.services.lembrete_automatico_service import (
    _finalizar_envio,
    _reservar_envio,
    lembrete_automatico_habilitado,
    parse_hora_envio,
)

logger = logging.getLogger(__name__)

TZ_BR = ZoneInfo("America/Sao_Paulo")
_INTERVAL_SECONDS = 30
_DIAS_ANTES_PADRAO = int(os.environ.get("ONIX_FATURAMENTO_AUTO_DIAS_ANTES", "3") or "3")
# Inclui MENSALISTA (mensais) sem remover RENT/TENT, que ja funcionam.
_CATEGORIA_RE = re.compile(r"(RENT|TENT|MENSALISTA)", re.IGNORECASE)

_thread: threading.Thread | None = None
_lock = threading.Lock()
_cadastro_processado_em: dict[int, date] = {}


def faturamento_automatico_habilitado() -> bool:
    """Mesma regra do lembrete automatico: so producao."""
    return lembrete_automatico_habilitado()


def _hora_envio_atingida(now_br: datetime, hora_cfg: tuple[int, int]) -> bool:
    return (now_br.hour, now_br.minute) >= hora_cfg


def _marcar_cadastro_processado_hoje(cad_id: int, hoje: date) -> None:
    _cadastro_processado_em[int(cad_id)] = hoje


def _cadastro_ja_processado_hoje(cad_id: int, hoje: date) -> bool:
    return _cadastro_processado_em.get(int(cad_id)) == hoje


def _ids_categorias_elegiveis(db: Session) -> set[int]:
    rows = db.execute(
        text("SELECT id, nome FROM categorias_clientes WHERE nome IS NOT NULL")
    ).mappings().all()
    out: set[int] = set()
    for row in rows:
        nome = str(row.get("nome") or "")
        if _CATEGORIA_RE.search(nome):
            out.add(int(row["id"]))
    return out


def _dias_antes_faturamento_cadastro(cad: CadastroGeral) -> int | None:
    raw = cad.info_dias_antes_faturamento
    if raw is None:
        return _DIAS_ANTES_PADRAO if _DIAS_ANTES_PADRAO >= 0 else None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n < 0 or n > 60:
        return None
    return n


def _vencimento_ciclo_faturamento(info_data_vencimento: date | None, hoje: date) -> date | None:
    """Vencimento do ciclo atual/proximo, incluindo o proprio dia do vencimento.

    O helper global trata igualdade (hoje == dia) como mes seguinte; para catch-up
    do faturamento automatico precisamos ainda faturar no dia do vencimento.
    """
    venc = _proxima_data_por_dia_vencimento(info_data_vencimento, ref=hoje)
    if not venc or not info_data_vencimento:
        return venc
    dia = int(info_data_vencimento.day)
    if dia < 1 or dia > 31:
        return venc
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    venc_este_mes = date(hoje.year, hoje.month, min(dia, ultimo))
    if venc_este_mes == hoje:
        return venc_este_mes
    return venc


def _deve_faturar_hoje(*, hoje: date, alvo: date, venc: date) -> bool:
    """Dispara no dia alvo e faz catch-up ate o vencimento (inclusive).

    Historico (sucesso) continua impedindo duplicidade.
    """
    return alvo <= hoje <= venc


def _cadastro_elegivel_faturamento_auto(cad: CadastroGeral, cat_ids: set[int]) -> bool:
    if not bool(cad.info_faturamento_automatico):
        return False
    if not cad.categoria_cliente_id or int(cad.categoria_cliente_id) not in cat_ids:
        return False
    if not parse_hora_envio(cad.info_hora_faturamento):
        return False
    if _dias_antes_faturamento_cadastro(cad) is None:
        return False
    if Decimal(cad.info_valor_mensalista or 0) <= 0:
        return False
    if not str(cad.info_sku or "").strip():
        return False
    if not cad.info_data_vencimento:
        return False
    if not cad.info_condicao_pagamento_id:
        return False
    return True


def _reservar_faturamento(db: Session, *, cadastro_id: int, data_vencimento: date) -> bool:
    """Reserva vencimento; permite nova tentativa se a anterior falhou."""
    row = db.execute(
        text(
            """
            INSERT INTO faturamento_automatico_historico
                (cadastro_id, data_vencimento, detalhe, sucesso)
            VALUES
                (:cid, :venc, 'processando', FALSE)
            ON CONFLICT (cadastro_id, data_vencimento)
            DO UPDATE SET
                detalhe = EXCLUDED.detalhe,
                sucesso = FALSE,
                venda_id = NULL,
                conta_receber_id = NULL
            WHERE faturamento_automatico_historico.sucesso = FALSE
            RETURNING id
            """
        ),
        {"cid": int(cadastro_id), "venc": data_vencimento},
    ).first()
    if row is None:
        return False
    db.commit()
    return True


def _faturamento_ja_sucesso(db: Session, *, cadastro_id: int, data_vencimento: date) -> bool:
    row = db.execute(
        text(
            """
            SELECT sucesso FROM faturamento_automatico_historico
            WHERE cadastro_id = :cid AND data_vencimento = :venc
            LIMIT 1
            """
        ),
        {"cid": int(cadastro_id), "venc": data_vencimento},
    ).first()
    return bool(row and row[0])


def _finalizar_faturamento(
    db: Session,
    *,
    cadastro_id: int,
    data_vencimento: date,
    sucesso: bool,
    detalhe: str,
    venda_id: int | None = None,
    conta_receber_id: int | None = None,
) -> None:
    db.execute(
        text(
            """
            UPDATE faturamento_automatico_historico
            SET enviado_em = :agora,
                sucesso = :ok,
                detalhe = :det,
                venda_id = :vid,
                conta_receber_id = :crid
            WHERE cadastro_id = :cid AND data_vencimento = :venc
            """
        ),
        {
            "cid": int(cadastro_id),
            "venc": data_vencimento,
            "agora": datetime.utcnow(),
            "ok": bool(sucesso),
            "det": str(detalhe or "")[:500] or None,
            "vid": venda_id,
            "crid": conta_receber_id,
        },
    )


def _conta_principal_venda(db: Session, venda_id: int) -> ContaReceber | None:
    return (
        db.query(ContaReceber)
        .filter(ContaReceber.venda_id == int(venda_id))
        .order_by(ContaReceber.data_vencimento.asc(), ContaReceber.id.asc())
        .first()
    )


def _enviar_lembretes_pos_faturamento(
    db: Session,
    *,
    cad: CadastroGeral,
    conta: ContaReceber,
    dias_antes: int,
) -> list[str]:
    """Envia WhatsApp/e-mail no padrao do lembrete automatico do cadastro."""
    detalhes: list[str] = []
    venc = conta.data_vencimento
    if not venc:
        return detalhes

    if cad.botbot_enviar_whatsapp:
        if _reservar_envio(
            db,
            conta_id=int(conta.id),
            dias_antes=dias_antes,
            venc=venc,
            canal="whatsapp",
        ):
            try:
                ret = enviar_lembrete_pagamento_conta_whatsapp(
                    db,
                    conta_id=int(conta.id),
                    dias_antes=dias_antes,
                )
                ok = bool(ret.get("whatsapp_enviado"))
                det = str(ret.get("whatsapp_detalhe") or ("WhatsApp enviado." if ok else "Falha WhatsApp."))
            except HTTPException as exc:
                ok = False
                det = str(exc.detail) if isinstance(exc.detail, str) else str(exc.detail)
            except Exception as exc:  # noqa: BLE001
                ok = False
                det = f"{type(exc).__name__}: {str(exc)[:450]}"
            _finalizar_envio(
                db,
                conta_id=int(conta.id),
                dias_antes=dias_antes,
                venc=venc,
                canal="whatsapp",
                sucesso=ok,
                detalhe=det,
            )
            db.commit()
            detalhes.append(f"WhatsApp: {det}")
        else:
            detalhes.append("WhatsApp: ja enviado/reservado para este vencimento.")

    if cad.botbot_enviar_email and smtp_documentos_configurado():
        if _reservar_envio(
            db,
            conta_id=int(conta.id),
            dias_antes=dias_antes,
            venc=venc,
            canal="email",
        ):
            try:
                ret = enviar_lembrete_pagamento_conta_email(
                    db,
                    conta_id=int(conta.id),
                    dias_antes=dias_antes,
                )
                ok = bool(ret.get("email_enviado"))
                det = "E-mail enviado." if ok else "Falha e-mail."
            except HTTPException as exc:
                ok = False
                det = str(exc.detail) if isinstance(exc.detail, str) else str(exc.detail)
            except Exception as exc:  # noqa: BLE001
                ok = False
                det = f"{type(exc).__name__}: {str(exc)[:450]}"
            _finalizar_envio(
                db,
                conta_id=int(conta.id),
                dias_antes=dias_antes,
                venc=venc,
                canal="email",
                sucesso=ok,
                detalhe=det,
            )
            db.commit()
            detalhes.append(f"E-mail: {det}")
    return detalhes


def _processar_cadastro_faturamento_auto(
    db: Session,
    *,
    cad: CadastroGeral,
    data_vencimento: date,
    dias_antes: int,
) -> tuple[bool, str, int | None, int | None]:
    if not _reservar_faturamento(db, cadastro_id=int(cad.id), data_vencimento=data_vencimento):
        return False, "Faturamento ja registrado para este vencimento.", None, None

    venda_id: int | None = None
    conta_id: int | None = None
    try:
        venda = _criar_venda_de_cadastro_info(db, cad)
        venda.observacao = (
            f"Gerado automaticamente (faturamento mensalista, venc. "
            f"{data_vencimento.strftime('%d/%m/%Y')})."
        )
        db.flush()
        _gerar_financeiro_da_venda(db, venda)
        db.flush()
        venda_id = int(venda.id)
        conta = _conta_principal_venda(db, venda_id)
        if not conta:
            raise HTTPException(status_code=500, detail="Financeiro gerado sem conta a receber.")
        conta_id = int(conta.id)
        cond = None
        if venda.condicao_pagamento_id:
            from sga_financeiro.models.condicao_pagamento import CondicaoPagamento

            cond = db.get(CondicaoPagamento, int(venda.condicao_pagamento_id))
        tipo_asaas = asaas_service.tipo_emissao_asaas_para_condicao(cond)
        if tipo_asaas and effective_asaas_runtime().get("enabled"):
            asaas_service.sincronizar_dados_cobranca_asaas_conta(db, conta)
            if not asaas_service.conta_tem_meio_pagamento_asaas(conta):
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Cobranca Asaas nao gerada (sem link/PIX). "
                        "Verifique CPF/CNPJ do cliente, condicao de pagamento e integracao Asaas."
                    ),
                )
        db.commit()
        db.refresh(conta)

        envios = _enviar_lembretes_pos_faturamento(
            db,
            cad=cad,
            conta=conta,
            dias_antes=dias_antes,
        )
        det = f"Venda #{venda.numero} (ID {venda_id}), conta #{conta_id}."
        if envios:
            det += " " + " | ".join(envios)
        elif not cad.botbot_enviar_whatsapp and not cad.botbot_enviar_email:
            det += " Envio nao configurado no BotBot Config do cadastro."
        _finalizar_faturamento(
            db,
            cadastro_id=int(cad.id),
            data_vencimento=data_vencimento,
            sucesso=True,
            detalhe=det,
            venda_id=venda_id,
            conta_receber_id=conta_id,
        )
        db.commit()
        return True, det, venda_id, conta_id
    except HTTPException as exc:
        det = str(exc.detail) if isinstance(exc.detail, str) else str(exc.detail)
        db.rollback()
        _finalizar_faturamento(
            db,
            cadastro_id=int(cad.id),
            data_vencimento=data_vencimento,
            sucesso=False,
            detalhe=det[:500],
            venda_id=venda_id,
            conta_receber_id=conta_id,
        )
        db.commit()
        return False, det, venda_id, conta_id
    except Exception as exc:  # noqa: BLE001
        det = f"{type(exc).__name__}: {str(exc)[:450]}"
        db.rollback()
        _finalizar_faturamento(
            db,
            cadastro_id=int(cad.id),
            data_vencimento=data_vencimento,
            sucesso=False,
            detalhe=det,
            venda_id=venda_id,
            conta_receber_id=conta_id,
        )
        db.commit()
        return False, det, venda_id, conta_id


def executar_faturamento_automatico_once(db: Session) -> dict[str, int]:
    """Uma passagem: mensalistas elegiveis com faturamento automatico na hora configurada."""
    now_br = datetime.now(TZ_BR)
    hoje = now_br.date()
    stats = {"cadastros": 0, "faturados": 0, "falhas": 0, "ignorados": 0}

    cat_ids = _ids_categorias_elegiveis(db)
    if not cat_ids:
        return stats

    cadastros = (
        db.query(CadastroGeral)
        .filter(
            CadastroGeral.info_faturamento_automatico.is_(True),
            CadastroGeral.info_hora_faturamento.isnot(None),
            CadastroGeral.info_hora_faturamento != "",
            CadastroGeral.categoria_cliente_id.in_(list(cat_ids)),
        )
        .all()
    )

    for cad in cadastros:
        if not _cadastro_elegivel_faturamento_auto(cad, cat_ids):
            stats["ignorados"] += 1
            continue

        hora_cfg = parse_hora_envio(cad.info_hora_faturamento)
        if not hora_cfg or not _hora_envio_atingida(now_br, hora_cfg):
            continue
        if _cadastro_ja_processado_hoje(int(cad.id), hoje):
            continue

        venc = _vencimento_ciclo_faturamento(cad.info_data_vencimento, hoje)
        if not venc:
            continue
        dias_antes = _dias_antes_faturamento_cadastro(cad)
        if dias_antes is None:
            stats["ignorados"] += 1
            continue
        alvo = venc - timedelta(days=dias_antes)
        # Catch-up: se perdeu o dia alvo (ex.: 5 dias antes), ainda fatura ate o vencimento.
        if not _deve_faturar_hoje(hoje=hoje, alvo=alvo, venc=venc):
            logger.debug(
                "Faturamento auto aguardando cadastro=%s alvo=%s hoje=%s venc=%s dias_antes=%s",
                cad.id,
                alvo.isoformat(),
                hoje.isoformat(),
                venc.isoformat(),
                dias_antes,
            )
            continue

        if _faturamento_ja_sucesso(db, cadastro_id=int(cad.id), data_vencimento=venc):
            _marcar_cadastro_processado_hoje(int(cad.id), hoje)
            continue

        stats["cadastros"] += 1
        logger.info(
            "Faturamento auto cadastro=%s venc=%s dias_antes=%s hora=%s",
            cad.id,
            venc.isoformat(),
            dias_antes,
            cad.info_hora_faturamento,
        )

        ok, det, _, _ = _processar_cadastro_faturamento_auto(
            db,
            cad=cad,
            data_vencimento=venc,
            dias_antes=dias_antes,
        )
        if ok:
            _marcar_cadastro_processado_hoje(int(cad.id), hoje)
            stats["faturados"] += 1
            logger.info("Faturamento auto OK cadastro=%s: %s", cad.id, det)
        else:
            stats["falhas"] += 1
            logger.warning("Faturamento auto falhou cadastro=%s: %s", cad.id, det)

    return stats


def _faturamento_automatico_worker() -> None:
    time.sleep(20)
    while True:
        db = SessionLocal()
        try:
            stats = executar_faturamento_automatico_once(db)
            if stats.get("cadastros") or stats.get("faturados") or stats.get("falhas"):
                logger.info("Faturamento auto tick: %s", stats)
        except Exception:
            logger.exception("Falha no worker de faturamento automatico.")
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()
        now = datetime.now(TZ_BR)
        sec = now.second + now.microsecond / 1_000_000
        if sec < 28:
            time.sleep(max(1.0, 28 - sec))
        else:
            time.sleep(max(1.0, _INTERVAL_SECONDS - (sec - 28)))


def status_worker_faturamento_automatico() -> dict[str, object]:
    habilitado = faturamento_automatico_habilitado()
    return {
        "habilitado": habilitado,
        "worker_ativo": bool(habilitado and _thread and _thread.is_alive()),
        "dias_antes_padrao": _DIAS_ANTES_PADRAO,
        "intervalo_segundos": _INTERVAL_SECONDS,
    }


def iniciar_faturamento_automatico_mensalista() -> None:
    global _thread
    if not faturamento_automatico_habilitado():
        logger.info(
            "Faturamento automatico desabilitado nesta instancia (%s).",
            os.environ.get("SYSTEMD_SERVICE_NAME", "?"),
        )
        return
    with _lock:
        if _thread and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_faturamento_automatico_worker,
            name="onix-faturamento-auto",
            daemon=True,
        )
        _thread.start()
