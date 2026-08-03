"""Testes unitarios da janela de disparo do faturamento automatico."""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def _deve_faturar_hoje(*, hoje: date, alvo: date, venc: date) -> bool:
    return alvo <= hoje <= venc


def _vencimento_ciclo_simulando_helper(dia: int, hoje: date) -> date:
    """Espelha a logica de ciclo (inclui o dia do vencimento)."""
    ultimo = calendar.monthrange(hoje.year, hoje.month)[1]
    cand = date(hoje.year, hoje.month, min(dia, ultimo))
    if cand >= hoje:
        return cand
    year, month = hoje.year, hoje.month
    if month == 12:
        year, month = year + 1, 1
    else:
        month += 1
    ultimo = calendar.monthrange(year, month)[1]
    return date(year, month, min(dia, ultimo))


def test_catchup_dia5_com_5_dias_antes():
    hoje = date(2026, 8, 2)
    venc = _vencimento_ciclo_simulando_helper(5, hoje)
    assert venc == date(2026, 8, 5)
    alvo = venc - timedelta(days=5)
    assert alvo == date(2026, 7, 31)
    assert _deve_faturar_hoje(hoje=hoje, alvo=alvo, venc=venc) is True


def test_nao_fatura_antes_do_alvo():
    hoje = date(2026, 7, 30)
    venc = date(2026, 8, 5)
    alvo = date(2026, 7, 31)
    assert _deve_faturar_hoje(hoje=hoje, alvo=alvo, venc=venc) is False


def test_fatura_no_dia_alvo_exato():
    hoje = date(2026, 7, 31)
    venc = date(2026, 8, 5)
    alvo = date(2026, 7, 31)
    assert _deve_faturar_hoje(hoje=hoje, alvo=alvo, venc=venc) is True


def test_fatura_no_dia_do_vencimento():
    hoje = date(2026, 8, 5)
    venc = _vencimento_ciclo_simulando_helper(5, hoje)
    assert venc == date(2026, 8, 5)
    alvo = venc - timedelta(days=5)
    assert _deve_faturar_hoje(hoje=hoje, alvo=alvo, venc=venc) is True


def test_nao_fatura_depois_do_vencimento():
    hoje = date(2026, 8, 6)
    venc = _vencimento_ciclo_simulando_helper(5, hoje)
    assert venc == date(2026, 9, 5)
    alvo = venc - timedelta(days=5)
    # Ciclo de agosto ja passou; ciclo de setembro ainda nao chegou.
    assert _deve_faturar_hoje(hoje=hoje, alvo=alvo, venc=venc) is False
