"""Parcelas de fatura (vencimento/valor) a partir do pedido ou do financeiro gerado."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from sga_financeiro.models.conta_receber import ContaReceber
from sga_financeiro.models.venda import Venda


@dataclass
class ParcelaFatura:
    numero: str
    vencimento: date
    valor: Decimal


def _parse_data_br(texto: str) -> date | None:
    m = re.match(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$", (texto or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def texto_prazo_condicao_impressao(venda: Venda) -> str:
    """Texto para DANFE/XML: condicao + prazo do pedido (ex.: 10/20/30/40)."""
    partes: list[str] = []
    cond = getattr(venda, "condicao_pag_catalogo", None)
    if cond:
        nome = (getattr(cond, "nome", None) or "").strip()
        if nome:
            partes.append(nome)
    prazo = _texto_prazo_efetivo(venda)
    if prazo and prazo not in partes:
        partes.append(prazo)
    return " | ".join(partes)


def _nome_condicao_pagamento(venda: Venda) -> str:
    cond = getattr(venda, "condicao_pag_catalogo", None)
    return (getattr(cond, "nome", None) or "").strip()


def _normalizar_texto_pag(s: str) -> str:
    mapa = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    out = (s or "").strip().lower()
    for a, b in mapa.items():
        out = out.replace(a, b)
    return out


def pagamento_eh_avista(
    venda: Venda,
    parcelas: list[ParcelaFatura],
    *,
    data_emissao: date | None = None,
) -> bool:
    """
    Pagamento a vista para fins de NF-e:
    - vencimentos todos na data de emissao (ou anteriores); ou
    - condicao tipicamente a vista (Dinheiro, PIX, A vista, Somente Nota, etc.).
    SEFAZ cStat 853: cobr/nDup nao pode ir em pagamento a vista.
    """
    nome = _normalizar_texto_pag(_nome_condicao_pagamento(venda))
    # "contas a receber" / boleto a prazo nao sao a vista so pelo nome
    if "conta" in nome and "receber" in nome:
        pass
    elif "boleto" in nome and "asaas" in nome:
        pass
    else:
        chaves_avista = (
            "a vista",
            "avista",
            "dinheiro",
            "pix",
            "cartao",
            "debito",
            "credito",
            "integral",
            "antecipado",
            "antecipada",
            "outros",
            "somente nota",
            "somente nf",
        )
        if any(k in nome for k in chaves_avista):
            return True

    if not parcelas:
        return True

    base = data_emissao or (venda.data_pedido or date.today())
    # Vencimento no dia da emissao (ou antes) = a vista — SEFAZ rejeita cobr/nDup (cStat 853)
    if all(p.vencimento <= base for p in parcelas):
        return True
    return False


def tpag_nfe_da_venda(venda: Venda, *, t_pag_cfg: str | None = None, avista: bool = False) -> str:
    """Codigo tPag da NF-e com base na condicao do pedido."""
    nome = _normalizar_texto_pag(_nome_condicao_pagamento(venda))
    if "pix" in nome:
        return "17"
    if "dinheiro" in nome:
        return "01"
    if "debito" in nome:
        return "04"
    if "credito" in nome or "cartao" in nome:
        return "03"
    if "boleto" in nome:
        return "15"
    if "cheque" in nome:
        return "02"
    # OUTROS / ANTECIPADO / SOMENTE NOTA / a vista generico
    if "outros" in nome or "antecip" in nome or "somente" in nome or avista:
        return "99"
    cfg = (t_pag_cfg or "").strip()
    if cfg:
        return cfg
    return "99"


def xpag_nfe_da_venda(venda: Venda, *, t_pag: str | None = None) -> str | None:
    """
    Descricao do pagamento (xPag) — obrigatoria na SEFAZ quando tPag=99 (cStat 441).
    Limite tipico do schema: 2 a 60 caracteres.
    """
    if str(t_pag or "").strip() != "99":
        return None
    nome_orig = _nome_condicao_pagamento(venda).strip()
    nome = _normalizar_texto_pag(nome_orig)
    if "antecip" in nome:
        desc = "Pagamento antecipado"
    elif "somente" in nome:
        desc = "Pagamento ja realizado"
    elif nome_orig:
        desc = nome_orig
    else:
        desc = "Pagamento a vista"
    desc = re.sub(r"\s+", " ", desc).strip()
    if len(desc) < 2:
        desc = "Pagamento a vista"
    return desc[:60]


def _texto_prazo_efetivo(venda: Venda) -> str:
    """Prazo do pedido; se vazio, usa nome da condicao quando contiver prazos (ex.: 10/20/30/40)."""
    prazo = (venda.prazo_pagamento or "").strip()
    if prazo:
        return prazo
    cond = getattr(venda, "condicao_pag_catalogo", None)
    if cond:
        nome = (getattr(cond, "nome", None) or "").strip()
        if nome and re.search(r"\d", nome):
            return nome
    return ""


def _parse_prazos_dias(prazo_pagamento: str | None) -> list[int]:
    """Extrai prazos em dias (ex.: 10/20/30/40 ou 30/60). Ignora datas dd/mm/aaaa no texto."""
    if not prazo_pagamento:
        return [0]
    s = prazo_pagamento.strip()
    if re.search(r"\d{1,2}[/\-]\d{1,2}[/\-]\d{4}", s):
        return []
    if "/" in s and not re.search(r"\d{4}", s):
        partes = [p.strip() for p in s.split("/") if p.strip().isdigit()]
        dias_barra = [int(p) for p in partes if 0 <= int(p) <= 365]
        if len(dias_barra) >= 2:
            return dias_barra
    encontrados = re.findall(r"\d+", s)
    dias = [int(v) for v in encontrados if 0 <= int(v) <= 365]
    if not dias:
        return [0]
    return sorted(set(dias))


def _datas_explicitas_no_prazo(prazo_pagamento: str | None) -> list[date]:
    if not prazo_pagamento:
        return []
    out: list[date] = []
    for m in re.finditer(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", prazo_pagamento):
        dt = _parse_data_br(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")
        if dt:
            out.append(dt)
    return out


def _distribuir_valores(parcelas: list[ParcelaFatura], total: Decimal) -> list[ParcelaFatura]:
    if not parcelas:
        return parcelas
    n = len(parcelas)
    valor_parcela = (total / Decimal(n)).quantize(Decimal("0.01"))
    acum = Decimal("0.00")
    for i, p in enumerate(parcelas):
        v = valor_parcela if i < n - 1 else total - acum
        acum += v
        parcelas[i] = ParcelaFatura(numero=p.numero, vencimento=p.vencimento, valor=v)
    return parcelas


def ler_parcelas_valores_venda(venda: Venda) -> list[Decimal]:
    raw = getattr(venda, "parcelas_valores_json", None) or ""
    if not str(raw).strip():
        return []
    try:
        arr = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(arr, list):
        return []
    out: list[Decimal] = []
    for x in arr:
        try:
            out.append(Decimal(str(x)).quantize(Decimal("0.01")))
        except Exception:
            return []
    return out


def serializar_parcelas_valores(valores: list[Decimal] | None) -> str | None:
    if not valores:
        return None
    return json.dumps([float(v) for v in valores])


def parcelas_do_pedido(venda: Venda, *, prazo_dias_padrao: int = 5) -> list[ParcelaFatura]:
    """Vencimentos conforme prazo/datas do pedido (sem ler contas a receber)."""
    total = Decimal(venda.total_liquido or 0)
    base = venda.data_pedido or (
        venda.created_at.date() if getattr(venda, "created_at", None) else date.today()
    )

    texto_prazo = _texto_prazo_efetivo(venda)
    datas = _datas_explicitas_no_prazo(texto_prazo)
    if datas:
        parcelas = [
            ParcelaFatura(numero=f"{i + 1:03d}", vencimento=dt, valor=Decimal("0"))
            for i, dt in enumerate(datas)
        ]
        parcelas = _distribuir_valores(parcelas, total)
        custom = ler_parcelas_valores_venda(venda)
        if custom and len(custom) == len(parcelas):
            return [
                ParcelaFatura(numero=p.numero, vencimento=p.vencimento, valor=custom[i])
                for i, p in enumerate(parcelas)
            ]
        return parcelas

    dias_list = _parse_prazos_dias(texto_prazo)
    if not dias_list:
        dias_list = [max(0, int(prazo_dias_padrao or 5))]

    parcelas = [
        ParcelaFatura(
            numero=f"{i + 1:03d}",
            vencimento=base + timedelta(days=dias),
            valor=Decimal("0"),
        )
        for i, dias in enumerate(dias_list)
    ]
    parcelas = _distribuir_valores(parcelas, total)
    custom = ler_parcelas_valores_venda(venda)
    if custom and len(custom) == len(parcelas):
        return [
            ParcelaFatura(numero=p.numero, vencimento=p.vencimento, valor=custom[i])
            for i, p in enumerate(parcelas)
        ]
    return parcelas


def parcelas_fatura_da_venda(
    db: Session,
    venda: Venda,
    *,
    prazo_dias_padrao: int = 5,
) -> list[ParcelaFatura]:
    """
    Vencimentos para DANFE/XML:
    1) contas a receber do pedido (se financeiro gerado);
    2) senao, prazo/datas do pedido (parcelas_do_pedido).
    """
    parcelas_pedido = parcelas_do_pedido(venda, prazo_dias_padrao=prazo_dias_padrao)
    texto_prazo = _texto_prazo_efetivo(venda)
    dias_prazo = _parse_prazos_dias(texto_prazo) if texto_prazo else [0]
    prazo_multiplo = len(dias_prazo) >= 2 or len(_datas_explicitas_no_prazo(texto_prazo)) >= 2

    if bool(venda.financeiro_gerado):
        contas = (
            db.query(ContaReceber)
            .filter(ContaReceber.venda_id == venda.id)
            .order_by(ContaReceber.data_vencimento.asc(), ContaReceber.id.asc())
            .all()
        )
        if contas:
            parcelas_cr = [
                ParcelaFatura(
                    numero=f"{i + 1:03d}",
                    vencimento=c.data_vencimento,
                    valor=Decimal(c.valor or 0),
                )
                for i, c in enumerate(contas)
            ]
            if prazo_multiplo or len(parcelas_pedido) > len(parcelas_cr):
                return parcelas_pedido
            return parcelas_cr

    return parcelas_pedido
