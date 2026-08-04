"""Pacote ZIP fiscal para contabilidade + link de download + e-mail."""

from __future__ import annotations

import csv
import io
import json
import re
import secrets
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.parse import quote

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.engine import Engine

from sga_financeiro.config import settings
from sga_financeiro.contabilidade_config import load_contabilidade_config, save_contabilidade_config
from sga_financeiro.email_documentos_config import smtp_documentos_configurado
from sga_financeiro.local_config import load_local_config
from sga_financeiro.runtime_paths import runtime_config_dir_raw
from sga_financeiro.services.documentos_email_service import _normalizar_email, _smtp_enviar
from sga_financeiro.fiscal_output_paths import nfe_out_ambiente
from sga_financeiro.services.nfe_distribuicao_dfe_service import modelo_chave_nfe

CATEGORIAS: dict[str, str] = {
    "nfe_xml_entrada": "NF-e - Xml Entrada",
    "nfe_xml_saida": "NF-e - Xml Saida",
    "nfe_rel_entrada": "NF-e Relatorio Entrada",
    "nfe_rel_saida": "NF-e Relatorio Saida",
    "nfse_xml_entrada": "NFS-e - Xml Entrada",
    "nfse_xml_saida": "NFS-e - Xml Saida",
    "nfse_rel_entrada": "NFS-e Relatorio Entrada",
    "nfse_rel_saida": "NFS-e Relatorio Saida",
}

_PASTA_ZIP: dict[str, str] = {
    "nfe_xml_entrada": "NF-e - Xml Entrada",
    "nfe_xml_saida": "NF-e - Xml Saida",
    "nfe_rel_entrada": "NF-e Relatorio Entrada",
    "nfe_rel_saida": "NF-e Relatorio Saida",
    "nfse_xml_entrada": "NFS-e - Xml Entrada",
    "nfse_xml_saida": "NFS-e - Xml Saida",
    "nfse_rel_entrada": "NFS-e Relatorio Entrada",
    "nfse_rel_saida": "NFS-e Relatorio Saida",
}

_TOKEN_DIAS = 14


@dataclass
class ResultadoEnvioContador:
    ok: bool
    mensagem: str
    token: str = ""
    link_download: str = ""
    zip_path: str = ""
    arquivos_total: int = 0
    resumo: dict[str, int] = field(default_factory=dict)
    email_destino: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mensagem": self.mensagem,
            "token": self.token,
            "link_download": self.link_download,
            "zip_path": self.zip_path,
            "arquivos_total": self.arquivos_total,
            "resumo": self.resumo,
            "email_destino": self.email_destino,
        }


def _somente_digitos(v: str) -> str:
    return re.sub(r"\D+", "", v or "")


def competencia_mes_anterior_label(hoje: date | None = None) -> str:
    """Competencia MM/AAAA do mes calendario anterior."""
    hoje = hoje or date.today()
    if hoje.month == 1:
        return f"12/{hoje.year - 1}"
    return f"{hoje.month - 1:02d}/{hoje.year}"


def pacote_enviado_para_competencia(competencia: str) -> bool:
    """True se ja houve envio de pacote (manifest) para a competencia informada."""
    try:
        _, _, label = parse_competencia(competencia)
    except HTTPException:
        return False
    alvo = (label or "").strip()
    if not alvo:
        return False
    for item in _ler_manifest():
        if str(item.get("competencia") or "").strip() == alvo:
            return True
    return False


def status_lembrete_envio_contador() -> dict[str, Any]:
    """
    A partir do dia 1 do mes, exige envio da competencia do mes anterior
    ate que um pacote seja registrado no manifest.
    """
    hoje = date.today()
    comp = competencia_mes_anterior_label(hoje)
    enviado = pacote_enviado_para_competencia(comp)
    exigir = hoje.day >= 1 and not enviado
    return {
        "exigir": exigir,
        "competencia": comp,
        "enviado": enviado,
        "dia_mes": hoje.day,
        "mes_atual": f"{hoje.month:02d}/{hoje.year}",
    }


def parse_competencia(texto: str) -> tuple[date, date, str]:
    s = (texto or "").strip()
    m = re.match(r"^(\d{1,2})\s*[/\-]\s*(\d{4})$", s)
    if not m:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Competencia invalida. Use MM/AAAA (ex.: 05/2026).",
        )
    mes = int(m.group(1))
    ano = int(m.group(2))
    if mes < 1 or mes > 12:
        raise HTTPException(status_code=400, detail="Mes da competencia invalido.")
    inicio = date(ano, mes, 1)
    if mes == 12:
        fim = date(ano, 12, 31)
    else:
        fim = date(ano, mes + 1, 1) - timedelta(days=1)
    label = f"{mes:02d}/{ano}"
    return inicio, fim, label


def _chave_aamm(chave44: str) -> str | None:
    ch = _somente_digitos(chave44)
    if len(ch) < 6:
        return None
    return ch[2:6]


def _chave_no_periodo(chave44: str, inicio: date, fim: date) -> bool:
    """Competencia pela chave NF-e (44 digitos, AAMM nas posicoes 2-5). Chave NFS-e: retorna False."""
    ch = _somente_digitos(chave44)
    if len(ch) != 44:
        return False
    aamm = _chave_aamm(ch)
    if not aamm or len(aamm) != 4:
        return False
    try:
        yy = int(aamm[:2])
        mm = int(aamm[2:4])
        if mm < 1 or mm > 12:
            return False
        ano = 2000 + yy if yy < 70 else 1900 + yy
        d = date(ano, mm, 1)
    except ValueError:
        return False
    return inicio <= d <= fim


def _data_no_periodo(val: Any, inicio: date, fim: date) -> bool:
    if val is None:
        return False
    if isinstance(val, datetime):
        d = val.date()
    elif isinstance(val, date):
        d = val
    else:
        s = str(val).strip()[:10]
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
        else:
            return False
    return inicio <= d <= fim


def pacotes_contador_dir() -> Path:
    raw = runtime_config_dir_raw()
    d = Path(raw).expanduser().resolve() / "contador-pacotes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path() -> Path:
    return pacotes_contador_dir() / "manifest.json"


def _ler_manifest() -> list[dict[str, Any]]:
    p = _manifest_path()
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        return []


def _gravar_manifest(itens: list[dict[str, Any]]) -> None:
    p = _manifest_path()
    p.write_text(json.dumps(itens[-200:], ensure_ascii=False, indent=2), encoding="utf-8")


def _registrar_pacote(
    *,
    token: str,
    zip_path: Path,
    competencia: str,
    email: str,
    resumo: dict[str, int],
) -> None:
    itens = _ler_manifest()
    itens.append(
        {
            "token": token,
            "arquivo": str(zip_path),
            "competencia": competencia,
            "email": email,
            "resumo": resumo,
            "criado_em": datetime.now().isoformat(timespec="seconds"),
            "expira_em": (datetime.now() + timedelta(days=_TOKEN_DIAS)).isoformat(timespec="seconds"),
        }
    )
    _gravar_manifest(itens)


def obter_pacote_por_token(token: str) -> dict[str, Any] | None:
    tok = (token or "").strip()
    if not tok or len(tok) < 16:
        return None
    agora = datetime.now()
    for item in _ler_manifest():
        if str(item.get("token") or "") != tok:
            continue
        exp = str(item.get("expira_em") or "")
        try:
            if exp and datetime.fromisoformat(exp) < agora:
                continue
        except ValueError:
            pass
        path = Path(str(item.get("arquivo") or ""))
        if path.is_file():
            return item
    return None


def _url_publica_base() -> str:
    cfg = load_local_config()
    base = str(cfg.get("mobile_push_public_url") or "").strip().rstrip("/")
    if not base:
        port = int(cfg.get("http_port") or 9014)
        base = f"http://127.0.0.1:{port}"
    return base


def _link_download(token: str) -> str:
    """Rota fora de /api — contador abre o link do e-mail sem login."""
    return f"{_url_publica_base()}/contador/download/{quote(token, safe='')}"


def _ambiente_instalacao() -> str:
    """Ambiente fiscal desta instalação (ver fiscal_ambiente.py)."""
    from sga_financeiro.fiscal_ambiente import ambiente_fiscal_instalacao

    return ambiente_fiscal_instalacao()


def _ambiente_nfe_efetivo(base_dir: Path) -> str:
    """Pasta nfe_out/{ambiente} da instalação; nfe_config.json de outro ambiente é ignorado."""
    return _ambiente_instalacao()


def _ambiente_nfse_efetivo(base_dir: Path) -> str:
    """Pasta nfse_out/{ambiente} da instalação; nfse_config de outro ambiente é ignorado."""
    return _ambiente_instalacao()


def _caminho_xml_nfe_contador(base_dir: Path, chave44: str) -> Path | None:
    """XML de NF-e de saida somente na pasta do ambiente desta instalacao (sem homolog/prod misturado)."""
    ch = _somente_digitos(chave44)
    if len(ch) != 44:
        return None
    amb = _ambiente_nfe_efetivo(base_dir)
    pasta = nfe_out_ambiente(base_dir, amb)
    direto = pasta / f"{ch}-nfe-assinada.xml"
    if direto.is_file():
        return direto
    for path in sorted(pasta.glob(f"*{ch}*.xml"), reverse=True):
        if path.is_file() and "cancel" not in path.name.lower():
            return path
    return None


def _formatar_item_resumo(categoria: str, quantidade: int) -> str:
    label = CATEGORIAS.get(categoria, categoria)
    if "rel_" in categoria:
        return f"{label}: {quantidade} linha(s)"
    return f"{label}: {quantidade} arquivo(s)"


def _resumo_legivel(resumo: dict[str, int]) -> list[str]:
    return [_formatar_item_resumo(k, q) for k, q in resumo.items()]


def _bool_db(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "t", "true", "yes", "sim")


def _dfe_entrada_incluir_contador(chave: str, oculto: Any = False) -> bool:
    """NF-e de entrada no pacote contador: exclui cupom NFC-e (65) e documentos ocultos."""
    if _bool_db(oculto):
        return False
    ch = _somente_digitos(chave)
    if len(ch) == 44 and modelo_chave_nfe(ch) == "65":
        return False
    return True


def _coletar_nfe_xml_entrada(engine: Engine, inicio: date, fim: date) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT chave_nfe, xml_conteudo, data_emissao, created_at, oculto
                FROM nfe_dfe_documentos
                WHERE TRIM(COALESCE(xml_conteudo, '')) <> ''
                  AND COALESCE(oculto, FALSE) = FALSE
                ORDER BY id DESC
                """
            )
        ).mappings().all()
    vistos: set[str] = set()
    for r in rows:
        chave = _somente_digitos(str(r.get("chave_nfe") or ""))
        xml = str(r.get("xml_conteudo") or "").strip()
        if not _dfe_entrada_incluir_contador(chave, r.get("oculto")):
            continue
        if len(chave) != 44 or not xml or chave in vistos:
            continue
        if not _chave_no_periodo(chave, inicio, fim) and not _data_no_periodo(
            r.get("data_emissao") or r.get("created_at"), inicio, fim
        ):
            continue
        vistos.add(chave)
        nome = f"{chave}.xml"
        out.append((nome, xml.encode("utf-8")))
    return out


def _coletar_nfe_xml_saida(base_dir: Path, engine: Engine, inicio: date, fim: date) -> list[tuple[str, bytes]]:
    amb = _ambiente_nfe_efetivo(base_dir)
    out: list[tuple[str, bytes]] = []
    vistos: set[str] = set()
    pasta = nfe_out_ambiente(base_dir, amb)

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT nfe_chave_acesso, data_pedido, created_at,
                       nfe_cancelada, nfe_cancelada_em, nfe_protocolo_cancelamento
                FROM vendas
                WHERE COALESCE(nfe_gerada, FALSE) = TRUE
                  AND TRIM(COALESCE(nfe_chave_acesso, '')) <> ''
                """
            )
        ).mappings().all()

    for r in rows:
        ch = _somente_digitos(str(r.get("nfe_chave_acesso") or ""))
        if len(ch) != 44:
            continue
        if not _chave_no_periodo(ch, inicio, fim) and not _data_no_periodo(
            r.get("data_pedido") or r.get("created_at"), inicio, fim
        ):
            continue
        if ch in vistos:
            continue
        path = _caminho_xml_nfe_contador(base_dir, ch)
        if path and path.is_file():
            vistos.add(ch)
            out.append((path.name, path.read_bytes()))

        if not _venda_nfe_cancelada(dict(r)):
            continue
        if not _data_no_periodo(r.get("nfe_cancelada_em"), inicio, fim):
            continue
        if not pasta.is_dir():
            continue
        for sufixo in ("-cancelamento-envio.xml", "-cancelamento-retorno.xml"):
            path_evt = pasta / f"{ch}{sufixo}"
            if path_evt.is_file() and path_evt.name not in vistos:
                vistos.add(path_evt.name)
                out.append((path_evt.name, path_evt.read_bytes()))
    return out


def _venda_nfe_cancelada(row: dict[str, Any]) -> bool:
    """NF-e cancelada na SEFAZ (flag no pedido ou protocolo/data de cancelamento)."""
    if _bool_db(row.get("nfe_cancelada")):
        return True
    if str(row.get("nfe_protocolo_cancelamento") or "").strip():
        return True
    if row.get("nfe_cancelada_em"):
        return True
    return False


def _formatar_data_csv(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d/%m/%Y")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    if len(s) >= 10 and s[4:5] == "-":
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            pass
    return s


def _formatar_valor_csv(val: Any) -> str:
    if val is None or val == "":
        return ""
    try:
        n = float(val)
        return f"{n:.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(val).strip()


def _formatar_moeda_csv(val: Any) -> str:
    """Valor monetario com mascara R$ (pt-BR), ex.: R$ 1.250,00."""
    if val is None or val == "":
        return ""
    try:
        n = Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        s = str(val).strip()
        return s if s.upper().startswith("R$") else s
    sinal = "-" if n < 0 else ""
    n = abs(n).quantize(Decimal("0.01"))
    inteiro, centavos = f"{n:.2f}".split(".")
    grupos = []
    while inteiro:
        grupos.append(inteiro[-3:])
        inteiro = inteiro[:-3]
    inteiro_fmt = ".".join(reversed(grupos))
    return f"{sinal}R$ {inteiro_fmt},{centavos}"


def _parse_valor_csv(val: Any) -> Decimal:
    if val is None or val == "":
        return Decimal("0")
    if isinstance(val, Decimal):
        return val
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    s = str(val).strip().replace("\t", "").replace(" ", "")
    if not s:
        return Decimal("0")
    s = s.replace("R$", "").replace("r$", "").strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _somar_coluna_valores(linhas: list[list[Any]], indice: int) -> Decimal:
    total = Decimal("0")
    for ln in linhas:
        if not ln or indice >= len(ln):
            continue
        total += _parse_valor_csv(ln[indice])
    return total


def _forcar_texto_excel(val: Any) -> bool:
    """Chaves NF-e, CNPJ e protocolos longos — Excel nao deve virar notacao cientifica."""
    s = str(val if val is not None else "").strip()
    if not s:
        return False
    digitos = _somente_digitos(s)
    if len(digitos) >= 11 and digitos.isdigit():
        return True
    return False


def _celula_csv_excel(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (date, datetime)):
        return _formatar_data_csv(val)
    if _forcar_texto_excel(val):
        # Tab no inicio: Excel abre como texto (evita 4,32E+43 na chave/CNPJ)
        return "\t" + _somente_digitos(str(val))
    s = str(val).strip()
    if re.match(r"^-?\d+(\.\d+)?$", s.replace(",", ".")):
        try:
            if "." in s or "," in s:
                return _formatar_valor_csv(s.replace(",", "."))
        except Exception:
            pass
    return s


def _csv_bytes(cabecalho: list[str], linhas: list[list[Any]]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(cabecalho)
    for ln in linhas:
        w.writerow([_celula_csv_excel(c) for c in ln])
    # BOM + sep=; ajudam o Excel (PT-BR) a abrir chave/CNPJ como texto
    return ("\ufeffsep=;\n" + buf.getvalue()).encode("utf-8")


def _linhas_nfe_rel_entrada(engine: Engine, inicio: date, fim: date) -> list[list[Any]]:
    linhas: list[list[Any]] = []
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT chave_nfe, emit_nome, emit_cnpj, numero_nota, data_emissao, valor_total, manifestacao_tipo, oculto
                FROM nfe_dfe_documentos
                WHERE COALESCE(oculto, FALSE) = FALSE
                ORDER BY COALESCE(created_at, updated_at) DESC NULLS LAST
                """
            )
        ).mappings().all()
    for r in rows:
        chave = _somente_digitos(str(r.get("chave_nfe") or ""))
        if not _dfe_entrada_incluir_contador(chave, r.get("oculto")):
            continue
        if len(chave) == 44 and not _chave_no_periodo(chave, inicio, fim):
            if not _data_no_periodo(r.get("data_emissao"), inicio, fim):
                continue
        elif not _data_no_periodo(r.get("data_emissao"), inicio, fim):
            continue
        linhas.append(
            [
                chave,
                r.get("emit_nome") or "",
                _somente_digitos(str(r.get("emit_cnpj") or "")),
                r.get("numero_nota") or "",
                _formatar_data_csv(r.get("data_emissao")),
                _formatar_valor_csv(r.get("valor_total")),
                r.get("manifestacao_tipo") or "",
            ]
        )
    return linhas


def _coletar_nfe_rel_entrada(engine: Engine, inicio: date, fim: date) -> bytes:
    linhas = _linhas_nfe_rel_entrada(engine, inicio, fim)
    return _csv_bytes(
        ["Chave", "Emitente", "CNPJ emitente", "Numero", "Emissao", "Valor NF", "Manifestacao"],
        linhas,
    )


def _linhas_nfe_rel_saida(engine: Engine, inicio: date, fim: date) -> list[list[Any]]:
    linhas: list[list[Any]] = []
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT v.id, v.numero, v.data_pedido, v.nfe_chave_acesso, v.nfe_protocolo_autorizacao,
                       v.nfe_protocolo_cancelamento, v.nfe_cancelada, v.nfe_cancelada_em,
                       v.total_liquido, cg.razao_social AS cliente_nome
                FROM vendas v
                LEFT JOIN cadastros_gerais cg ON cg.id = v.cliente_id
                WHERE COALESCE(v.nfe_gerada, FALSE) = TRUE
                ORDER BY v.data_pedido DESC NULLS LAST, v.id DESC
                """
            )
        ).mappings().all()
    for r in rows:
        chave = _somente_digitos(str(r.get("nfe_chave_acesso") or ""))
        if len(chave) == 44 and not _chave_no_periodo(chave, inicio, fim):
            if not _data_no_periodo(r.get("data_pedido"), inicio, fim):
                continue
        elif not _data_no_periodo(r.get("data_pedido"), inicio, fim):
            continue
        cancelada = _venda_nfe_cancelada(dict(r))
        linhas.append(
            [
                r.get("id"),
                r.get("numero") or "",
                _formatar_data_csv(r.get("data_pedido")),
                chave,
                str(r.get("nfe_protocolo_autorizacao") or "").strip(),
                "sim" if cancelada else "nao",
                str(r.get("nfe_protocolo_cancelamento") or "").strip(),
                _formatar_data_csv(r.get("nfe_cancelada_em")) if cancelada else "",
                _formatar_moeda_csv(r.get("total_liquido")),
                r.get("cliente_nome") or "",
            ]
        )
    return linhas


def _coletar_nfe_rel_saida(engine: Engine, inicio: date, fim: date) -> bytes:
    linhas = _linhas_nfe_rel_saida(engine, inicio, fim)
    # Soma apenas notas nao canceladas (coluna Cancelada = indice 5; Valor = 8)
    linhas_soma = [ln for ln in linhas if len(ln) > 5 and str(ln[5]).strip().lower() != "sim"]
    total = _somar_coluna_valores(linhas_soma, 8)
    linhas_out = list(linhas)
    if linhas_out:
        linhas_out.append(
            ["TOTAL", "", "", "", "", "", "", "", _formatar_moeda_csv(total), ""]
        )
    return _csv_bytes(
        [
            "Pedido ID",
            "Numero pedido",
            "Data venda",
            "Chave NF-e",
            "Protocolo autorizacao",
            "Cancelada",
            "Protocolo cancelamento",
            "Data cancelamento",
            "Valor nota",
            "Cliente",
        ],
        linhas_out,
    )


def _coletar_nfse_xml_saida(base_dir: Path, engine: Engine, inicio: date, fim: date) -> list[tuple[str, bytes]]:
    from sga_financeiro.services.nfse_emissao_service import resolver_xml_nfse_autorizado

    amb = _ambiente_nfse_efetivo(base_dir)
    out: list[tuple[str, bytes]] = []
    vistos: set[str] = set()

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, nfse_chave_acesso, nfse_id_dps, data_pedido, created_at
                FROM vendas
                WHERE COALESCE(nfse_gerada, FALSE) = TRUE
                """
            )
        ).mappings().all()

    for r in rows:
        ch = _somente_digitos(str(r.get("nfse_chave_acesso") or ""))
        if not _chave_no_periodo(ch, inicio, fim) and not _data_no_periodo(
            r.get("data_pedido") or r.get("created_at"), inicio, fim
        ):
            continue
        path = resolver_xml_nfse_autorizado(
            base_dir,
            amb,
            chave=ch or None,
            id_dps=str(r.get("nfse_id_dps") or "").strip() or None,
        )
        if path and path.is_file():
            nome = path.name
            if nome not in vistos:
                vistos.add(nome)
                out.append((nome, path.read_bytes()))
    return out


def _linhas_nfse_rel_entrada(engine: Engine, inicio: date, fim: date) -> list[list[Any]]:
    """NFS-e recebidas (tomador): sem base integrada ainda."""
    _ = engine, inicio, fim
    return []


def _coletar_nfse_rel_entrada(engine: Engine, inicio: date, fim: date) -> bytes:
    return _csv_bytes(
        [
            "Chave NFS-e",
            "Numero",
            "Prestador",
            "CNPJ prestador",
            "Emissao",
            "Valor",
            "Observacao",
        ],
        _linhas_nfse_rel_entrada(engine, inicio, fim),
    )


def _linhas_nfse_rel_saida(engine: Engine, inicio: date, fim: date) -> list[list[Any]]:
    linhas: list[list[Any]] = []
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT v.id, v.numero, v.data_pedido, v.created_at, v.nfse_chave_acesso,
                       v.nfse_numero, v.nfse_id_dps, v.total_liquido, cg.razao_social AS cliente_nome
                FROM vendas v
                LEFT JOIN cadastros_gerais cg ON cg.id = v.cliente_id
                WHERE COALESCE(v.nfse_gerada, FALSE) = TRUE
                ORDER BY COALESCE(v.data_pedido, v.created_at) DESC NULLS LAST, v.id DESC
                """
            )
        ).mappings().all()
    for r in rows:
        chave = _somente_digitos(str(r.get("nfse_chave_acesso") or ""))
        no_periodo = _data_no_periodo(r.get("data_pedido") or r.get("created_at"), inicio, fim)
        if len(chave) == 44:
            no_periodo = no_periodo or _chave_no_periodo(chave, inicio, fim)
        if not no_periodo:
            continue
        linhas.append(
            [
                chave,
                r.get("nfse_numero") or "",
                r.get("numero") or "",
                _formatar_data_csv(r.get("data_pedido") or r.get("created_at")),
                str(r.get("nfse_id_dps") or "").strip(),
                _formatar_moeda_csv(r.get("total_liquido")),
                r.get("cliente_nome") or "",
            ]
        )
    return linhas


def _coletar_nfse_rel_saida(engine: Engine, inicio: date, fim: date) -> bytes:
    linhas = _linhas_nfse_rel_saida(engine, inicio, fim)
    # Valor pedido = indice 5 — total = soma de todas as notas do periodo
    total = _somar_coluna_valores(linhas, 5)
    linhas_out = list(linhas)
    if linhas_out:
        linhas_out.append(
            ["TOTAL", "", "", "", "", _formatar_moeda_csv(total), ""]
        )
    return _csv_bytes(
        [
            "Chave NFS-e",
            "Numero NFS-e",
            "Numero pedido",
            "Data venda",
            "ID DPS",
            "Valor pedido",
            "Cliente",
        ],
        linhas_out,
    )


def _coletar_nfse_xml_entrada() -> list[tuple[str, bytes]]:
    """Reservado: NFS-e de entrada (tomador) ainda nao integrada — pasta vazia com LEIAME."""
    txt = (
        "NFS-e recebidas como tomador ainda nao possuem coleta automatica neste modulo.\n"
        "Inclua os XMLs manualmente se necessario.\n"
    ).encode("utf-8")
    return [("LEIAME.txt", txt)]


def _montar_resumo_pacote(
    engine: Engine,
    base_dir: Path,
    inicio: date,
    fim: date,
    categorias: list[str],
) -> dict[str, int]:
    cats = [c for c in categorias if c in CATEGORIAS]
    resumo: dict[str, int] = {}
    if "nfe_xml_entrada" in cats:
        resumo["nfe_xml_entrada"] = len(_coletar_nfe_xml_entrada(engine, inicio, fim))
    if "nfe_xml_saida" in cats:
        resumo["nfe_xml_saida"] = len(_coletar_nfe_xml_saida(base_dir, engine, inicio, fim))
    if "nfe_rel_entrada" in cats:
        resumo["nfe_rel_entrada"] = len(_linhas_nfe_rel_entrada(engine, inicio, fim))
    if "nfe_rel_saida" in cats:
        resumo["nfe_rel_saida"] = len(_linhas_nfe_rel_saida(engine, inicio, fim))
    if "nfse_xml_entrada" in cats:
        resumo["nfse_xml_entrada"] = 0
    if "nfse_xml_saida" in cats:
        resumo["nfse_xml_saida"] = len(_coletar_nfse_xml_saida(base_dir, engine, inicio, fim))
    if "nfse_rel_entrada" in cats:
        resumo["nfse_rel_entrada"] = len(_linhas_nfse_rel_entrada(engine, inicio, fim))
    if "nfse_rel_saida" in cats:
        resumo["nfse_rel_saida"] = len(_linhas_nfse_rel_saida(engine, inicio, fim))
    return resumo


def preview_pacote_contador(
    engine: Engine,
    base_dir: Path,
    *,
    competencia: str,
    categorias: list[str],
) -> dict[str, Any]:
    inicio, fim, label = parse_competencia(competencia)
    resumo = _montar_resumo_pacote(engine, base_dir, inicio, fim, categorias)
    return {
        "competencia": label,
        "periodo_inicio": inicio.isoformat(),
        "periodo_fim": fim.isoformat(),
        "ambiente_fiscal": _ambiente_instalacao(),
        "resumo": resumo,
        "resumo_legivel": _resumo_legivel(resumo),
    }


def montar_e_enviar_pacote_contador(
    engine: Engine,
    base_dir: Path,
    *,
    competencia: str,
    categorias: list[str],
    email_destino: str | None = None,
    nome_contabilidade: str | None = None,
    salvar_cadastro: bool = False,
) -> ResultadoEnvioContador:
    if not smtp_documentos_configurado():
        return ResultadoEnvioContador(
            ok=False,
            mensagem="Configure o SMTP em Configuracoes > E-mail documentos (SMTP) antes de enviar.",
        )

    inicio, fim, label = parse_competencia(competencia)
    cats = [c for c in categorias if c in CATEGORIAS]
    if not cats:
        return ResultadoEnvioContador(ok=False, mensagem="Selecione ao menos um tipo de documento.")

    cfg = load_contabilidade_config()
    dest = (email_destino or cfg.get("email") or "").strip()
    if not dest:
        return ResultadoEnvioContador(
            ok=False,
            mensagem="Informe o e-mail da contabilidade ou cadastre-o antes do envio.",
        )
    try:
        dest_norm = _normalizar_email(dest)
    except HTTPException as exc:
        return ResultadoEnvioContador(ok=False, mensagem=str(exc.detail))

    if salvar_cadastro:
        save_contabilidade_config(
            {
                "nome": nome_contabilidade or cfg.get("nome") or "",
                "email": dest_norm,
                "cnpj": cfg.get("cnpj") or "",
                "observacao": cfg.get("observacao") or "",
            }
        )

    arquivos_total = 0
    resumo = _montar_resumo_pacote(engine, base_dir, inicio, fim, cats)
    token = secrets.token_urlsafe(32)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"contador_{label.replace('/', '-')}_{stamp}_{token[:8]}.zip"
    zip_path = pacotes_contador_dir() / zip_name

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if "nfe_xml_entrada" in cats:
                arqs = _coletar_nfe_xml_entrada(engine, inicio, fim)
                pasta = _PASTA_ZIP["nfe_xml_entrada"]
                for nome, blob in arqs:
                    zf.writestr(f"{pasta}/{nome}", blob)
                arquivos_total += len(arqs)

            if "nfe_xml_saida" in cats:
                arqs = _coletar_nfe_xml_saida(base_dir, engine, inicio, fim)
                pasta = _PASTA_ZIP["nfe_xml_saida"]
                for nome, blob in arqs:
                    zf.writestr(f"{pasta}/{nome}", blob)
                arquivos_total += len(arqs)

            if "nfe_rel_entrada" in cats:
                pasta = _PASTA_ZIP["nfe_rel_entrada"]
                zf.writestr(f"{pasta}/relatorio_entrada_{label.replace('/', '-')}.csv", _coletar_nfe_rel_entrada(engine, inicio, fim))
                arquivos_total += 1

            if "nfe_rel_saida" in cats:
                pasta = _PASTA_ZIP["nfe_rel_saida"]
                zf.writestr(f"{pasta}/relatorio_saida_{label.replace('/', '-')}.csv", _coletar_nfe_rel_saida(engine, inicio, fim))
                arquivos_total += 1

            if "nfse_xml_entrada" in cats:
                arqs = _coletar_nfse_xml_entrada()
                pasta = _PASTA_ZIP["nfse_xml_entrada"]
                for nome, blob in arqs:
                    zf.writestr(f"{pasta}/{nome}", blob)
                arquivos_total += len(arqs)

            if "nfse_xml_saida" in cats:
                arqs = _coletar_nfse_xml_saida(base_dir, engine, inicio, fim)
                pasta = _PASTA_ZIP["nfse_xml_saida"]
                for nome, blob in arqs:
                    zf.writestr(f"{pasta}/{nome}", blob)
                arquivos_total += len(arqs)

            if "nfse_rel_entrada" in cats:
                pasta = _PASTA_ZIP["nfse_rel_entrada"]
                zf.writestr(
                    f"{pasta}/relatorio_entrada_{label.replace('/', '-')}.csv",
                    _coletar_nfse_rel_entrada(engine, inicio, fim),
                )
                zf.writestr(
                    f"{pasta}/LEIAME.txt",
                    (
                        "NFS-e recebidas (tomador) ainda nao possuem coleta automatica.\n"
                        "O CSV traz apenas o cabecalho; inclua XMLs manualmente se necessario.\n"
                    ).encode("utf-8"),
                )
                arquivos_total += 2

            if "nfse_rel_saida" in cats:
                pasta = _PASTA_ZIP["nfse_rel_saida"]
                zf.writestr(
                    f"{pasta}/relatorio_saida_{label.replace('/', '-')}.csv",
                    _coletar_nfse_rel_saida(engine, inicio, fim),
                )
                arquivos_total += 1

            readme = (
                f"Pacote fiscal Onix System\nCompetencia: {label}\n"
                f"Ambiente fiscal: {_ambiente_instalacao()}\n"
                f"Periodo: {inicio.isoformat()} a {fim.isoformat()}\n"
                f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                f"Pastas: {', '.join(_PASTA_ZIP[c] for c in cats)}\n"
            )
            zf.writestr("LEIAME.txt", readme.encode("utf-8"))

        if arquivos_total == 0:
            zip_path.unlink(missing_ok=True)
            return ResultadoEnvioContador(
                ok=False,
                mensagem="Nenhum arquivo encontrado para a competencia e categorias selecionadas.",
                resumo=resumo,
            )

        link = _link_download(token)
        _registrar_pacote(
            token=token,
            zip_path=zip_path,
            competencia=label,
            email=dest_norm,
            resumo=resumo,
        )

        nome_esc = nome_contabilidade or cfg.get("nome") or "Contabilidade"
        corpo = (
            f"Ola,\n\n"
            f"Segue o pacote fiscal da competencia {label} ({nome_esc}).\n\n"
            f"Download (valido por {_TOKEN_DIAS} dias):\n{link}\n\n"
            f"Resumo:\n"
        )
        for k, q in resumo.items():
            corpo += f"  - {_formatar_item_resumo(k, q)}\n"
        corpo += "\nAtenciosamente,\nOnix System\n"

        from email.utils import formataddr

        from sga_financeiro.email_documentos_config import effective_smtp_documentos

        smtp_cfg = effective_smtp_documentos()
        from_addr = str(smtp_cfg.get("smtp_from_email") or smtp_cfg.get("smtp_user") or "").strip()
        from_name = str(smtp_cfg.get("smtp_from_name") or "Onix System").strip()
        msg = MIMEMultipart()
        msg["Subject"] = f"Onix System — Documentos contabilidade {label}"
        msg["To"] = dest_norm
        if from_addr:
            msg["From"] = formataddr((from_name, from_addr))
        msg.attach(MIMEText(corpo, "plain", "utf-8"))
        _smtp_enviar(msg, dest_norm)

        return ResultadoEnvioContador(
            ok=True,
            mensagem=f"Pacote enviado para {dest_norm}. Link no e-mail (valido {_TOKEN_DIAS} dias).",
            token=token,
            link_download=link,
            zip_path=str(zip_path),
            arquivos_total=arquivos_total,
            resumo=resumo,
            email_destino=dest_norm,
        )
    except HTTPException:
        raise
    except Exception as exc:
        if zip_path.is_file():
            zip_path.unlink(missing_ok=True)
        return ResultadoEnvioContador(ok=False, mensagem=f"Falha ao montar ou enviar pacote: {exc}")
