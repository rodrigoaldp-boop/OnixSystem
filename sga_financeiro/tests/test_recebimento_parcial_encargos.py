"""Regras de recebimento parcial: principal, multa integral, juros no restante."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace


def _calc(**kwargs):
    # Import tardio evita dependencias pesadas no collect; em CI/servidor o modulo existe.
    from sga_financeiro.services.encargos_atraso_service import calcular_encargos_atraso_conta_receber

    return calcular_encargos_atraso_conta_receber(**kwargs)


def test_multa_sobre_original_apos_parcial():
    cfg = {
        "asaas_boleto_multa_percent": "2",
        "asaas_boleto_juros_percent_dia": "0.033",
    }
    venc = date(2026, 7, 1)
    hoje = date(2026, 7, 11)  # 10 dias uteis aproximados se Jul/1 foi util
    # Simula apos parcial: principal restante 600, original 1000, multa fixada 20
    enc = _calc(
        valor_principal=Decimal("600.00"),
        data_vencimento=venc,
        data_recebimento=hoje,
        cobrancas_cfg=cfg,
        valor_original=Decimal("1000.00"),
        multa_fixada=Decimal("20.00"),
        juros_acumulados=Decimal("3.30"),
        juros_apos_data=hoje,  # no mesmo dia, juros novos = 0
    )
    assert enc["multa"] == Decimal("20.00")
    assert enc["juros"] == Decimal("3.30")
    assert enc["juros_novos"] == Decimal("0.00")
    assert enc["total_devido"] == Decimal("623.30")


def test_juros_novos_sobre_restante():
    cfg = {
        "asaas_boleto_multa_percent": "2",
        "asaas_boleto_juros_percent_dia": "0.1",  # 0,1%/dia para conta facil
    }
    venc = date(2026, 7, 1)
    parcial_em = date(2026, 7, 10)
    hoje = date(2026, 7, 12)  # 2 dias apos parcial
    enc = _calc(
        valor_principal=Decimal("500.00"),
        data_vencimento=venc,
        data_recebimento=hoje,
        cobrancas_cfg=cfg,
        valor_original=Decimal("1000.00"),
        multa_fixada=Decimal("20.00"),
        juros_acumulados=Decimal("9.00"),
        juros_apos_data=parcial_em,
    )
    # 500 * 0.1% * 2 = 1.00
    assert enc["juros_novos"] == Decimal("1.00")
    assert enc["juros"] == Decimal("10.00")
    assert enc["multa"] == Decimal("20.00")
    assert enc["total_devido"] == Decimal("530.00")


def test_sem_parcial_usa_principal_atual():
    cfg = {
        "asaas_boleto_multa_percent": "2",
        "asaas_boleto_juros_percent_dia": "0",
    }
    enc = _calc(
        valor_principal=Decimal("1000.00"),
        data_vencimento=date(2026, 7, 1),
        data_recebimento=date(2026, 7, 5),
        cobrancas_cfg=cfg,
    )
    assert enc["multa"] == Decimal("20.00")
    assert enc["total_devido"] == Decimal("1020.00")


def test_atalho_conta():
    from sga_financeiro.services.encargos_atraso_service import calcular_encargos_da_conta_receber

    cfg = {
        "asaas_boleto_multa_percent": "2",
        "asaas_boleto_juros_percent_dia": "0",
    }
    conta = SimpleNamespace(
        valor=Decimal("800.00"),
        data_vencimento=date(2026, 6, 1),
        valor_original=Decimal("1000.00"),
        multa_fixada=Decimal("20.00"),
        juros_acumulados=Decimal("5.00"),
        juros_apos_data=date(2026, 7, 1),
    )
    enc = calcular_encargos_da_conta_receber(
        conta,
        data_recebimento=date(2026, 7, 1),
        cobrancas_cfg=cfg,
    )
    assert enc["multa"] == Decimal("20.00")
    assert enc["juros"] == Decimal("5.00")
    assert enc["valor_principal"] == Decimal("800.00")
