"""Calculo de multa e juros por atraso em contas a receber (mesmas regras da config Asaas)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from typing import Any

from sga_financeiro.cobrancas_config import load_cobrancas_config


def _q2(v: Decimal) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _easter_sunday(year: int) -> date:
    """Domingo de Pascoa (calendario gregoriano)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=32)
def _feriados_nacionais_ano(ano: int) -> frozenset[date]:
    """Feriados nacionais BR (fixos + moveis bancarios: Carnaval, Sexta Santa, Corpus Christi)."""
    pascoa = _easter_sunday(ano)
    return frozenset(
        {
            date(ano, 1, 1),
            pascoa - timedelta(days=48),
            pascoa - timedelta(days=47),
            pascoa - timedelta(days=2),
            date(ano, 4, 21),
            date(ano, 5, 1),
            pascoa + timedelta(days=60),
            date(ano, 9, 7),
            date(ano, 10, 12),
            date(ano, 11, 2),
            date(ano, 11, 15),
            date(ano, 12, 25),
        }
    )


def _eh_dia_nao_util(d: date) -> bool:
    if d.weekday() >= 5:
        return True
    return d in _feriados_nacionais_ano(d.year)


def _vencimento_efetivo_encargos(data_vencimento: date) -> date:
    """Fim de semana ou feriado nacional: encargos so apos o proximo dia util (regra boleto/Asaas)."""
    d = data_vencimento
    while _eh_dia_nao_util(d):
        d += timedelta(days=1)
    return d


def _pct_cfg(cfg: dict[str, Any], key: str) -> Decimal:
    try:
        return Decimal(str(cfg.get(key) or 0))
    except Exception:
        return Decimal("0")


def calcular_encargos_atraso_conta_receber(
    *,
    valor_principal: Decimal,
    data_vencimento: date,
    data_recebimento: date,
    perdoar_multa: bool = False,
    perdoar_juros: bool = False,
    cobrancas_cfg: dict[str, Any] | None = None,
    valor_original: Decimal | None = None,
    multa_fixada: Decimal | None = None,
    juros_acumulados: Decimal | None = None,
    juros_apos_data: date | None = None,
) -> dict[str, Any]:
    """
    Multa: % unica sobre o principal original (ou multa_fixada apos recebimento parcial).
    Juros: % ao dia sobre o principal em aberto.
    Apos parcial: juros_acumulados (ja corridos) + juros novos sobre o restante desde juros_apos_data.
    Vencimento em fim de semana ou feriado nacional: conta atraso a partir do proximo dia util.
    """
    principal = _q2(Decimal(valor_principal or 0))
    original = _q2(Decimal(valor_original if valor_original is not None else principal))
    cfg = cobrancas_cfg if cobrancas_cfg is not None else load_cobrancas_config()
    venc_efetivo = _vencimento_efetivo_encargos(data_vencimento)
    dias = max(0, (data_recebimento - venc_efetivo).days)
    multa_pct = _pct_cfg(cfg, "asaas_boleto_multa_percent")
    juros_dia_pct = _pct_cfg(cfg, "asaas_boleto_juros_percent_dia")

    multa = Decimal("0")
    juros = Decimal("0")
    juros_novos = Decimal("0")
    acum = _q2(Decimal(juros_acumulados or 0))

    if dias > 0 and (principal > 0 or original > 0 or acum > 0 or multa_fixada is not None):
        if not perdoar_multa:
            if multa_fixada is not None:
                multa = _q2(Decimal(multa_fixada or 0))
            elif multa_pct > 0 and original > 0:
                # Multa integral sempre sobre o principal original da divida.
                multa = _q2(original * multa_pct / Decimal("100"))

        if not perdoar_juros and juros_dia_pct > 0:
            if juros_apos_data is not None:
                dias_novos = max(0, (data_recebimento - juros_apos_data).days)
                if principal > 0 and dias_novos > 0:
                    juros_novos = _q2(
                        principal * juros_dia_pct / Decimal("100") * Decimal(dias_novos)
                    )
                juros = _q2(acum + juros_novos)
            elif principal > 0:
                juros = _q2(principal * juros_dia_pct / Decimal("100") * Decimal(dias))
                juros_novos = juros
            else:
                juros = acum
        elif perdoar_juros:
            juros = Decimal("0")
            juros_novos = Decimal("0")
            acum = Decimal("0")

    total = _q2(principal + multa + juros)
    return {
        "valor_principal": principal,
        "valor_original": original,
        "dias_atraso": dias,
        "multa": multa,
        "juros": juros,
        "juros_acumulados": acum if not perdoar_juros else Decimal("0"),
        "juros_novos": juros_novos if not perdoar_juros else Decimal("0"),
        "total_devido": total,
        "vencida": dias > 0,
        "multa_percent": float(multa_pct) if multa_pct > 0 else None,
        "juros_percent_dia": float(juros_dia_pct) if juros_dia_pct > 0 else None,
        "multa_fixada": True if multa_fixada is not None else False,
    }


def calcular_encargos_da_conta_receber(
    conta: Any,
    *,
    data_recebimento: date,
    perdoar_multa: bool = False,
    perdoar_juros: bool = False,
    cobrancas_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atalho: le campos de parcial/congelamento da conta a receber."""
    valor_original = getattr(conta, "valor_original", None)
    multa_fixada = getattr(conta, "multa_fixada", None)
    juros_acumulados = getattr(conta, "juros_acumulados", None)
    juros_apos_data = getattr(conta, "juros_apos_data", None)
    return calcular_encargos_atraso_conta_receber(
        valor_principal=Decimal(conta.valor or 0),
        data_vencimento=conta.data_vencimento,
        data_recebimento=data_recebimento,
        perdoar_multa=perdoar_multa,
        perdoar_juros=perdoar_juros,
        cobrancas_cfg=cobrancas_cfg,
        valor_original=Decimal(valor_original) if valor_original is not None else None,
        multa_fixada=Decimal(multa_fixada) if multa_fixada is not None else None,
        juros_acumulados=Decimal(juros_acumulados or 0),
        juros_apos_data=juros_apos_data,
    )
