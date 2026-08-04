"""Geracao de XML NF-e assinado por ambiente, sem transmissao SEFAZ."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime

from sga_financeiro.fiscal_output_paths import nfe_out_ambiente
from sga_financeiro.services.datetime_br import agora_brasil
from decimal import Decimal
from pathlib import Path
import json
import random
import re
from typing import Optional

from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, pkcs12
from lxml import etree
from signxml import XMLSigner, methods

from sga_financeiro.models.venda import Venda
from sga_financeiro.models.cadastro_geral import CadastroGeral
from sga_financeiro.models.venda_item import VendaItem
from sga_financeiro.services.venda_parcelas_fatura import (
    pagamento_eh_avista,
    parcelas_fatura_da_venda,
    texto_prazo_condicao_impressao,
    tpag_nfe_da_venda,
    xpag_nfe_da_venda,
)


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D+", "", valor or "")


CSRT_HOMOLOG_PADRAO = "LJP0Z0L3S5115996F9P0HFGXH4G53TFSP22O"


def resolver_csrt_nfe_cfg(cfg: dict, ambiente: str) -> tuple[str, str]:
    """
    ID e token CSRT efetivos para o ambiente (mesma regra da geracao do XML).
    Em producao aceita id_csrt/csrt quando nao houver id_csrt_producao/csrt_producao
    e o token generico nao for o CSRT padrao de homologacao.
    """
    if cfg.get("incluir_hash_csrt") is False:
        return "", ""
    ambiente = (ambiente or "homologacao").lower()
    csrt_homolog_padrao = str(cfg.get("csrt_homologacao", CSRT_HOMOLOG_PADRAO) or CSRT_HOMOLOG_PADRAO).strip().upper()
    if ambiente == "producao":
        id_csrt_raw = _somente_digitos(str(cfg.get("id_csrt_producao", "") or "").strip())
        csrt_amb = str(cfg.get("csrt_producao", "") or "").strip()
        if not id_csrt_raw or not csrt_amb:
            id_gen = _somente_digitos(str(cfg.get("id_csrt", "")).strip())
            csrt_gen = str(cfg.get("csrt", "")).strip()
            if csrt_gen and csrt_gen.strip().upper() != csrt_homolog_padrao:
                id_csrt_raw = id_csrt_raw or id_gen
                csrt_amb = csrt_amb or csrt_gen
    else:
        id_csrt_raw = _somente_digitos(
            str(cfg.get("id_csrt_homologacao", "") or cfg.get("id_csrt", "")).strip()
        )
        csrt_amb = str(cfg.get("csrt_homologacao", "") or cfg.get("csrt", "")).strip()
    id_csrt = id_csrt_raw.zfill(2) if id_csrt_raw else ""
    return id_csrt, csrt_amb


_RE_CHAVE_NFE_44 = re.compile(r"\b(\d{44})\b")


def _nnf_serie_da_chave(chave: str) -> tuple[int, int] | None:
    ch = _somente_digitos(chave)
    if len(ch) != 44 or ch[20:22] != "55":
        return None
    try:
        return int(ch[22:25]), int(ch[25:34])
    except ValueError:
        return None


def _max_nnf_arquivos_local(out_dir: Path, serie: int, cnpj_emitente: str) -> int:
    """Maior nNF ja usado em XMLs assinados locais (mesma serie e CNPJ)."""
    cnpj = _somente_digitos(cnpj_emitente)
    if not cnpj:
        return 0
    max_n = 0
    for arq in out_dir.glob("*-nfe-assinada.xml"):
        parsed = _nnf_serie_da_chave(arq.name[:44])
        if not parsed:
            continue
        ser, nnf = parsed
        ch_cnpj = _somente_digitos(arq.name[6:20])
        if ser == serie and ch_cnpj == cnpj and nnf > max_n:
            max_n = nnf
    return max_n


def ajustar_sequencia_nnf_apos_rejeicao_539(
    base_dir: Path,
    ambiente: str,
    xmotivo: str,
    *,
    serie: int,
    cnpj_emitente: str,
) -> int | None:
    """
    cStat 539: SEFAZ ja tem o nNF com outra chave. Avanca nnf-seq.txt acima do nNF citado.
    """
    cnpj = _somente_digitos(cnpj_emitente)
    max_n = 0
    for match in _RE_CHAVE_NFE_44.finditer(xmotivo or ""):
        ch = match.group(1)
        if _somente_digitos(ch[6:20]) != cnpj:
            continue
        parsed = _nnf_serie_da_chave(ch)
        if not parsed:
            continue
        ser, nnf = parsed
        if ser == serie:
            max_n = max(max_n, nnf)
    if max_n < 1:
        return None

    out_dir = nfe_out_ambiente(base_dir, ambiente)
    out_dir.mkdir(parents=True, exist_ok=True)
    seq_path = out_dir / "nnf-seq.txt"
    atual = 0
    if seq_path.exists():
        try:
            atual = int(_somente_digitos(seq_path.read_text(encoding="utf-8").strip()) or "0")
        except Exception:
            atual = 0
    # Proximo nNF a alocar deve ser estritamente maior que qualquer nNF ja usado na SEFAZ.
    alvo = max_n + 1
    if atual > alvo:
        alvo = atual
    seq_path.write_text(str(alvo), encoding="utf-8")

    cfg_path = base_dir / "nfe_config.json"
    if cfg_path.exists() and max_n > 0:
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                piso_atual = int(raw.get("piso_nnf", 0) or 0)
                if max_n > piso_atual:
                    raw["piso_nnf"] = max_n
                    cfg_path.write_text(
                        json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
        except Exception:
            pass
    return alvo


def peek_proximo_nnf(base_dir: Path, ambiente: str, fallback: int) -> tuple[int, int]:
    """Serie e nNF da proxima emissao, sem alterar nnf-seq.txt (para previa PDF)."""
    cfg = _load_nfe_config(base_dir)
    serie = int(cfg.get("serie", 1) or 1)
    cnpj = _somente_digitos(str(cfg.get("cnpj_emitente", "")))

    out_dir = nfe_out_ambiente(base_dir, ambiente)
    seq_path = out_dir / "nnf-seq.txt"

    current: int | None = None
    if seq_path.exists():
        try:
            current = int(_somente_digitos(seq_path.read_text(encoding="utf-8").strip()) or "0")
        except Exception:
            current = None

    max_local = _max_nnf_arquivos_local(out_dir, serie, cnpj) if cnpj else 0
    piso_cfg = int(cfg.get("piso_nnf", 0) or 0)
    minimo = max(1, int(fallback) + 1, max_local + 1, piso_cfg + 1)

    if not current or current < 1:
        nnf = minimo
    elif current < minimo:
        nnf = minimo
    elif current <= int(fallback):
        nnf = max(int(fallback) + 1, minimo)
    else:
        nnf = current
    return serie, nnf


def _next_nnf(base_dir: Path, ambiente: str, fallback: int) -> int:
    """
    Gera um nNF sequencial e persistente por ambiente.
    Evita rejeição 539 quando tenta emitir novamente a mesma venda.
    """
    cfg = _load_nfe_config(base_dir)
    serie = int(cfg.get("serie", 1) or 1)
    cnpj = _somente_digitos(str(cfg.get("cnpj_emitente", "")))

    out_dir = nfe_out_ambiente(base_dir, ambiente)
    out_dir.mkdir(parents=True, exist_ok=True)
    seq_path = out_dir / "nnf-seq.txt"

    current: int | None = None
    if seq_path.exists():
        try:
            current = int(_somente_digitos(seq_path.read_text(encoding="utf-8").strip()) or "0")
        except Exception:
            current = None

    max_local = _max_nnf_arquivos_local(out_dir, serie, cnpj) if cnpj else 0
    piso_cfg = int(cfg.get("piso_nnf", 0) or 0)
    minimo = max(1, int(fallback) + 1, max_local + 1, piso_cfg + 1)

    if not current or current < 1:
        current = minimo
    elif current < minimo:
        current = minimo
    elif current <= int(fallback):
        current = int(fallback) + 1
        if current < minimo:
            current = minimo

    nnf = current
    seq_path.write_text(str(nnf + 1), encoding="utf-8")
    return nnf


def _mod11_dv(chave43: str) -> str:
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = 0
    idx = 0
    for ch in reversed(chave43):
        soma += int(ch) * pesos[idx]
        idx = (idx + 1) % len(pesos)
    resto = soma % 11
    dv = 11 - resto
    if dv >= 10:
        dv = 0
    return str(dv)


def _fmt_dec(v: Decimal, casas: int = 2) -> str:
    q = Decimal("1." + ("0" * casas))
    return format(v.quantize(q), f".{casas}f")


def _distribuir_frete_por_itens(itens: list, frete: Decimal) -> list[Decimal]:
    """Rateia valor_frete do pedido nos itens (SEFAZ soma vFrete dos det = ICMSTot/vFrete)."""
    frete = Decimal(frete or 0).quantize(Decimal("0.01"))
    n = len(itens)
    if frete <= 0 or n == 0:
        return [Decimal("0.00")] * n
    bases = [Decimal(getattr(it, "total_item", None) or 0) for it in itens]
    total_base = sum(bases)
    if total_base <= 0:
        parte = (frete / n).quantize(Decimal("0.01"))
        partes = [parte] * n
        partes[-1] = (frete - sum(partes[:-1])).quantize(Decimal("0.01"))
        return partes
    partes: list[Decimal] = []
    acum = Decimal("0.00")
    for i, base in enumerate(bases):
        if i == n - 1:
            partes.append((frete - acum).quantize(Decimal("0.01")))
        else:
            p = (frete * base / total_base).quantize(Decimal("0.01"))
            partes.append(p)
            acum += p
    return partes


def _sanitizar_inf_cpl(texto: str, max_len: int = 5000) -> str:
    """Ajusta texto do infCpl ao facet da NF-e (evita cStat 225 por caracteres Unicode nao previstos no pattern)."""
    s = str(texto or "")
    for old, new in (
        ("\u2014", "-"),  # em dash
        ("\u2013", "-"),  # en dash
        ("\u2212", "-"),  # minus sign
        ("\u00A0", " "),  # nbsp
        ("\u200B", ""),
        ("\u200C", ""),
        ("\u200D", ""),
        ("\uFEFF", ""),
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2026", "..."),
        ("\u00ba", "o"),  # ordinal: Nº -> No
        ("\u00aa", "a"),
    ):
        s = s.replace(old, new)
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)
    out: list[str] = []
    for ch in s:
        o = ord(ch)
        if o <= 0xFF:
            out.append(ch)
        else:
            out.append(" ")
    s = "".join(out)
    s = re.sub(r" +", " ", s).strip()
    return s[:max_len]


def _load_nfe_config(base_dir: Path) -> dict:
    from sga_financeiro.fiscal_ambiente import aplicar_trava_ambiente_fiscal

    cfg_path = base_dir / "nfe_config.json"
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return aplicar_trava_ambiente_fiscal(raw)
    except Exception:
        return {}


def _uf_codigo(uf: str) -> str:
    tabela = {
        "PR": "41",
    }
    return tabela.get((uf or "").upper(), "41")


class _NFeXMLSigner(XMLSigner):
    def check_deprecated_methods(self):
        return


def gerar_nfe_xml_assinado(
    db,
    venda: Venda,
    base_dir: Path,
    observacao_complementar: Optional[str] = None,
) -> dict:
    cfg = _load_nfe_config(base_dir)
    ambiente = str(cfg.get("ambiente", "homologacao")).lower()
    if ambiente not in {"homologacao", "producao"}:
        raise ValueError("Ambiente NF-e invalido. Use homologacao ou producao.")

    cnpj = _somente_digitos(str(cfg.get("cnpj_emitente", "")))
    ie_cfg = str(cfg.get("ie_emitente", "")).strip()
    ie = "ISENTO" if ie_cfg.upper() == "ISENTO" else _somente_digitos(ie_cfg)
    crt = str(cfg.get("crt", "simples")).lower()
    serie = int(cfg.get("serie", 1) or 1)
    cfop_padrao = str(cfg.get("cfop_padrao", "5102")).strip() or "5102"
    nat_op = str(cfg.get("nat_op", "")).strip() or "Venda de mercadoria a nao contribuinte"
    cfop_natureza: str | None = None
    nat_rel = getattr(venda, "natureza_operacao_catalogo", None)
    if nat_rel is None and getattr(venda, "natureza_operacao_id", None):
        from sga_financeiro.models.natureza_operacao import NaturezaOperacao

        nat_rel = db.get(NaturezaOperacao, int(venda.natureza_operacao_id))
    if nat_rel is not None:
        desc_nat = str(getattr(nat_rel, "descricao", "") or "").strip()
        if desc_nat:
            nat_op = desc_nat
        cfop_raw = str(getattr(nat_rel, "cfop", "") or "").strip()
        if cfop_raw:
            cfop_natureza = cfop_raw
    csosn_raw = str(cfg.get("csosn_padrao", "0102")).strip() or "0102"
    csosn = _somente_digitos(csosn_raw)[-3:] or "102"
    cert_path = Path(str(cfg.get("cert_path", "")).strip())
    cert_password = str(cfg.get("cert_password", "")).strip()

    if len(cnpj) != 14:
        raise ValueError("CNPJ emitente invalido na configuracao NF-e.")
    if not ie:
        raise ValueError("IE emitente nao configurada.")
    if not cert_path.exists():
        raise ValueError("Arquivo de certificado nao encontrado.")
    if not cert_password:
        raise ValueError("Senha do certificado nao configurada.")

    fallback_nnf = int(_somente_digitos(venda.numero) or venda.id or 1)
    fallback_nnf = max(1, fallback_nnf)
    numero_nf = _next_nnf(base_dir, ambiente, fallback=fallback_nnf)
    dh_emi_dt = agora_brasil()
    dh_emi = dh_emi_dt.strftime("%Y-%m-%dT%H:%M:%S") + dh_emi_dt.strftime("%z")
    dh_emi = dh_emi[:-2] + ":" + dh_emi[-2:]
    aa_mm = datetime.now().strftime("%y%m")
    cuf = _uf_codigo(str(cfg.get("uf", "PR")))
    c_nf = f"{random.randint(0, 99999999):08d}"
    chave43 = f"{cuf}{aa_mm}{cnpj}55{serie:03d}{numero_nf:09d}1{c_nf}"
    dv = _mod11_dv(chave43)
    chave = chave43 + dv
    inf_id = f"NFe{chave}"

    total_prod = Decimal("0.00")
    for it in venda.itens:
        total_prod += Decimal(it.total_item or 0)
    frete = Decimal(venda.valor_frete or 0)
    total_nf = total_prod + frete
    frete_por_item = _distribuir_frete_por_itens(list(venda.itens), frete)

    ns = "http://www.portalfiscal.inf.br/nfe"
    nfe = etree.Element(f"{{{ns}}}NFe", nsmap={None: ns})
    inf = etree.SubElement(nfe, f"{{{ns}}}infNFe", Id=inf_id, versao="4.00")

    ide = etree.SubElement(inf, f"{{{ns}}}ide")
    etree.SubElement(ide, f"{{{ns}}}cUF").text = cuf
    etree.SubElement(ide, f"{{{ns}}}cNF").text = c_nf
    etree.SubElement(ide, f"{{{ns}}}natOp").text = nat_op
    etree.SubElement(ide, f"{{{ns}}}mod").text = "55"
    etree.SubElement(ide, f"{{{ns}}}serie").text = str(serie)
    etree.SubElement(ide, f"{{{ns}}}nNF").text = str(numero_nf)
    etree.SubElement(ide, f"{{{ns}}}dhEmi").text = dh_emi
    etree.SubElement(ide, f"{{{ns}}}dhSaiEnt").text = dh_emi
    etree.SubElement(ide, f"{{{ns}}}tpNF").text = "1"
    # idDest: 1=interna, 2=interestadual, 3=exterior (deve bater com CFOP 5xxx/6xxx/7xxx)
    uf_emit = (str(cfg.get("uf", "PR")).strip().upper() or "PR")[:2]
    cad: CadastroGeral | None = db.get(CadastroGeral, int(venda.cliente_id)) if venda.cliente_id else None
    uf_dest = (str((cad.uf if cad else "") or "").strip().upper() or uf_emit)[:2]
    if uf_dest in {"EX", "XX"}:
        id_dest = "3"
    elif uf_emit != uf_dest:
        id_dest = "2"
    else:
        id_dest = "1"
    etree.SubElement(ide, f"{{{ns}}}idDest").text = id_dest
    etree.SubElement(ide, f"{{{ns}}}cMunFG").text = _somente_digitos(str(cfg.get("cmun_fg", "")).strip()) or "4115200"
    etree.SubElement(ide, f"{{{ns}}}tpImp").text = "1"
    etree.SubElement(ide, f"{{{ns}}}tpEmis").text = "1"
    etree.SubElement(ide, f"{{{ns}}}cDV").text = dv
    etree.SubElement(ide, f"{{{ns}}}tpAmb").text = "2" if ambiente == "homologacao" else "1"
    etree.SubElement(ide, f"{{{ns}}}finNFe").text = "1"
    etree.SubElement(ide, f"{{{ns}}}indFinal").text = "1"
    etree.SubElement(ide, f"{{{ns}}}indPres").text = str(int(cfg.get("ind_pres", 9) or 9))
    etree.SubElement(ide, f"{{{ns}}}indIntermed").text = "0"
    etree.SubElement(ide, f"{{{ns}}}procEmi").text = "0"
    etree.SubElement(ide, f"{{{ns}}}verProc").text = str(cfg.get("ver_proc", "")).strip() or "OnixSystem-1.0"

    emit = etree.SubElement(inf, f"{{{ns}}}emit")
    etree.SubElement(emit, f"{{{ns}}}CNPJ").text = cnpj
    etree.SubElement(emit, f"{{{ns}}}xNome").text = str(cfg.get("xnome_emitente", "")).strip() or "ONIX BRASIL SYSTEM LTDA"
    xfant = str(cfg.get("xfant_emitente", "")).strip()
    if xfant:
        etree.SubElement(emit, f"{{{ns}}}xFant").text = xfant
    ender_emit = etree.SubElement(emit, f"{{{ns}}}enderEmit")
    etree.SubElement(ender_emit, f"{{{ns}}}xLgr").text = str(cfg.get("xlgr_emitente", "")).strip() or "RUA VALADOLID"
    etree.SubElement(ender_emit, f"{{{ns}}}nro").text = str(cfg.get("nro_emitente", "")).strip() or "0"
    etree.SubElement(ender_emit, f"{{{ns}}}xBairro").text = str(cfg.get("xbairro_emitente", "")).strip() or "CENTRO"
    etree.SubElement(ender_emit, f"{{{ns}}}cMun").text = _somente_digitos(str(cfg.get("cmun_emitente", "")).strip()) or (_somente_digitos(str(cfg.get("cmun_fg", "")).strip()) or "4115200")
    etree.SubElement(ender_emit, f"{{{ns}}}xMun").text = str(cfg.get("xmun_emitente", "")).strip() or "MARINGA"
    etree.SubElement(ender_emit, f"{{{ns}}}UF").text = uf_emit
    etree.SubElement(ender_emit, f"{{{ns}}}CEP").text = _somente_digitos(str(cfg.get("cep_emitente", "")).strip()) or "87053536"
    etree.SubElement(ender_emit, f"{{{ns}}}cPais").text = "1058"
    etree.SubElement(ender_emit, f"{{{ns}}}xPais").text = "Brasil"
    fone_emit = _somente_digitos(str(cfg.get("fone_emitente", "")).strip())
    if fone_emit:
        etree.SubElement(ender_emit, f"{{{ns}}}fone").text = fone_emit
    etree.SubElement(emit, f"{{{ns}}}IE").text = ie
    im = str(cfg.get("im_emitente", "")).strip()
    if im:
        etree.SubElement(emit, f"{{{ns}}}IM").text = im
    cnae = _somente_digitos(str(cfg.get("cnae_emitente", "")).strip() or str(cfg.get("cnae_principal", "")).strip())
    # Ordem do schema: CNAE vem depois de IM. Se não houver IM, não emitimos CNAE (evita erro de schema).
    if cnae and im:
        etree.SubElement(emit, f"{{{ns}}}CNAE").text = cnae
    etree.SubElement(emit, f"{{{ns}}}CRT").text = "1" if crt == "simples" else ("3" if crt == "real" else "2")

    dest = etree.SubElement(inf, f"{{{ns}}}dest")
    doc_dest = _somente_digitos((cad.cnpj if cad else "") or "")
    if len(doc_dest) == 11:
        etree.SubElement(dest, f"{{{ns}}}CPF").text = doc_dest
    elif len(doc_dest) == 14:
        etree.SubElement(dest, f"{{{ns}}}CNPJ").text = doc_dest
    else:
        etree.SubElement(dest, f"{{{ns}}}CPF").text = "12345678909"
    if ambiente == "homologacao":
        etree.SubElement(dest, f"{{{ns}}}xNome").text = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
    else:
        etree.SubElement(dest, f"{{{ns}}}xNome").text = (cad.razao_social if cad else "") or "CONSUMIDOR"
    ender_dest = etree.SubElement(dest, f"{{{ns}}}enderDest")
    etree.SubElement(ender_dest, f"{{{ns}}}xLgr").text = str((cad.endereco if cad else "") or "RUA TESTE").strip() or "RUA TESTE"
    etree.SubElement(ender_dest, f"{{{ns}}}nro").text = str((cad.numero_endereco if cad else "") or "0").strip() or "0"
    etree.SubElement(ender_dest, f"{{{ns}}}xBairro").text = str((cad.bairro if cad else "") or "CENTRO").strip() or "CENTRO"
    cmun_dest = _somente_digitos(str(getattr(cad, "codigo_municipio", "") or "").strip()) if cad else ""
    if len(cmun_dest) != 7:
        cmun_dest = _somente_digitos(str(cfg.get("cmun_dest_padrao", "")).strip()) or (
            _somente_digitos(str(cfg.get("cmun_fg", "")).strip()) or "4115200"
        )
    etree.SubElement(ender_dest, f"{{{ns}}}cMun").text = cmun_dest
    etree.SubElement(ender_dest, f"{{{ns}}}xMun").text = (str((cad.cidade if cad else "") or "").strip() or str(cfg.get("xmun_dest_padrao", "")).strip() or "MARINGA")
    etree.SubElement(ender_dest, f"{{{ns}}}UF").text = uf_dest
    etree.SubElement(ender_dest, f"{{{ns}}}CEP").text = _somente_digitos(str((cad.cep if cad else "") or "80000000"))
    etree.SubElement(ender_dest, f"{{{ns}}}cPais").text = "1058"
    etree.SubElement(ender_dest, f"{{{ns}}}xPais").text = "Brasil"
    ie_dest = _somente_digitos(str((cad.cnpj if False else "") or ""))  # placeholder
    ie_dest_raw = str(getattr(cad, "ie", "") if cad else "").strip()
    ie_dest = "ISENTO" if ie_dest_raw.upper() == "ISENTO" else _somente_digitos(ie_dest_raw)
    if ie_dest:
        etree.SubElement(dest, f"{{{ns}}}indIEDest").text = "1"
        etree.SubElement(dest, f"{{{ns}}}IE").text = ie_dest
    else:
        etree.SubElement(dest, f"{{{ns}}}indIEDest").text = "9"

    for idx, item in enumerate(venda.itens, start=1):
        det = etree.SubElement(inf, f"{{{ns}}}det", nItem=str(idx))
        prod = etree.SubElement(det, f"{{{ns}}}prod")
        produto = getattr(item, "produto", None)
        cprod = str(getattr(produto, "sku", "") or "").strip() or str(item.produto_id)
        etree.SubElement(prod, f"{{{ns}}}cProd").text = cprod
        etree.SubElement(prod, f"{{{ns}}}cEAN").text = "SEM GTIN"
        etree.SubElement(prod, f"{{{ns}}}xProd").text = str(getattr(produto, "nome", "") or f"ITEM {item.produto_id}")
        ncm = _somente_digitos(str(getattr(produto, "ncm", "") or "")) or "00000000"
        etree.SubElement(prod, f"{{{ns}}}NCM").text = ncm
        cest = _somente_digitos(str(getattr(produto, "cest", "") or ""))
        if cest:
            etree.SubElement(prod, f"{{{ns}}}CEST").text = cest
            # indEscala vem depois de CEST no schema
            etree.SubElement(prod, f"{{{ns}}}indEscala").text = "S"
        cfop_item = cfop_natureza or str(getattr(produto, "cfop_venda", "") or "").strip() or cfop_padrao
        etree.SubElement(prod, f"{{{ns}}}CFOP").text = cfop_item
        un = str(getattr(produto, "unidade", "") or "UN").strip() or "UN"
        etree.SubElement(prod, f"{{{ns}}}uCom").text = un
        etree.SubElement(prod, f"{{{ns}}}qCom").text = _fmt_dec(Decimal(item.quantidade or 0), 4)
        etree.SubElement(prod, f"{{{ns}}}vUnCom").text = _fmt_dec(Decimal(item.valor_unitario or 0), 2)
        etree.SubElement(prod, f"{{{ns}}}vProd").text = _fmt_dec(Decimal(item.total_item or 0), 2)
        etree.SubElement(prod, f"{{{ns}}}cEANTrib").text = "SEM GTIN"
        etree.SubElement(prod, f"{{{ns}}}uTrib").text = un
        etree.SubElement(prod, f"{{{ns}}}qTrib").text = _fmt_dec(Decimal(item.quantidade or 0), 4)
        etree.SubElement(prod, f"{{{ns}}}vUnTrib").text = _fmt_dec(Decimal(item.valor_unitario or 0), 2)
        v_frete_item = frete_por_item[idx - 1] if idx - 1 < len(frete_por_item) else Decimal("0.00")
        if v_frete_item > 0:
            etree.SubElement(prod, f"{{{ns}}}vFrete").text = _fmt_dec(v_frete_item, 2)
        etree.SubElement(prod, f"{{{ns}}}indTot").text = "1"
        etree.SubElement(prod, f"{{{ns}}}nItemPed").text = str(idx)

        imposto = etree.SubElement(det, f"{{{ns}}}imposto")
        etree.SubElement(imposto, f"{{{ns}}}vTotTrib").text = "0.00"
        icms = etree.SubElement(imposto, f"{{{ns}}}ICMS")
        icmssn = etree.SubElement(icms, f"{{{ns}}}ICMSSN102")
        etree.SubElement(icmssn, f"{{{ns}}}orig").text = "0"
        csosn_item = _somente_digitos(str(getattr(produto, "csosn", "") or ""))[-3:] or csosn
        etree.SubElement(icmssn, f"{{{ns}}}CSOSN").text = csosn_item

        pis = etree.SubElement(imposto, f"{{{ns}}}PIS")
        pis_outr = etree.SubElement(pis, f"{{{ns}}}PISOutr")
        etree.SubElement(pis_outr, f"{{{ns}}}CST").text = "49"
        etree.SubElement(pis_outr, f"{{{ns}}}vBC").text = "0.00"
        etree.SubElement(pis_outr, f"{{{ns}}}pPIS").text = "0.00"
        etree.SubElement(pis_outr, f"{{{ns}}}vPIS").text = "0.00"

        cofins = etree.SubElement(imposto, f"{{{ns}}}COFINS")
        cof_outr = etree.SubElement(cofins, f"{{{ns}}}COFINSOutr")
        etree.SubElement(cof_outr, f"{{{ns}}}CST").text = "49"
        etree.SubElement(cof_outr, f"{{{ns}}}vBC").text = "0.00"
        etree.SubElement(cof_outr, f"{{{ns}}}pCOFINS").text = "0.00"
        etree.SubElement(cof_outr, f"{{{ns}}}vCOFINS").text = "0.00"

    total = etree.SubElement(inf, f"{{{ns}}}total")
    icmstot = etree.SubElement(total, f"{{{ns}}}ICMSTot")
    etree.SubElement(icmstot, f"{{{ns}}}vBC").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vICMS").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vICMSDeson").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vFCP").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vBCST").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vST").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vFCPST").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vFCPSTRet").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vProd").text = _fmt_dec(total_prod, 2)
    etree.SubElement(icmstot, f"{{{ns}}}vFrete").text = _fmt_dec(frete, 2)
    etree.SubElement(icmstot, f"{{{ns}}}vSeg").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vDesc").text = _fmt_dec(Decimal(venda.total_desconto or 0), 2)
    etree.SubElement(icmstot, f"{{{ns}}}vII").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vIPI").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vIPIDevol").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vPIS").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vCOFINS").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vOutro").text = "0.00"
    etree.SubElement(icmstot, f"{{{ns}}}vNF").text = _fmt_dec(total_nf, 2)
    etree.SubElement(icmstot, f"{{{ns}}}vTotTrib").text = "0.00"

    transp = etree.SubElement(inf, f"{{{ns}}}transp")
    etree.SubElement(transp, f"{{{ns}}}modFrete").text = str(int(cfg.get("mod_frete", 0) or 0))
    vol = etree.SubElement(transp, f"{{{ns}}}vol")
    etree.SubElement(vol, f"{{{ns}}}pesoL").text = "0.000"
    etree.SubElement(vol, f"{{{ns}}}pesoB").text = "0.000"

    # Cobranca (fat/dup) — so para pagamento a prazo.
    # Pagamento a vista (cStat 853): nao informar cobr/nDup.
    prazo_dias_cfg = int(cfg.get("prazo_dias_padrao", 5) or 5)
    parcelas_xml = parcelas_fatura_da_venda(db, venda, prazo_dias_padrao=prazo_dias_cfg)
    data_emissao_nfe = (
        venda.data_pedido
        or (venda.created_at.date() if getattr(venda, "created_at", None) else None)
        or agora_brasil().date()
    )
    avista = pagamento_eh_avista(venda, parcelas_xml, data_emissao=data_emissao_nfe)
    if not avista and parcelas_xml:
        cobr = etree.SubElement(inf, f"{{{ns}}}cobr")
        fat = etree.SubElement(cobr, f"{{{ns}}}fat")
        etree.SubElement(fat, f"{{{ns}}}nFat").text = str(numero_nf).zfill(6)
        etree.SubElement(fat, f"{{{ns}}}vOrig").text = _fmt_dec(total_nf, 2)
        etree.SubElement(fat, f"{{{ns}}}vDesc").text = "0"
        etree.SubElement(fat, f"{{{ns}}}vLiq").text = _fmt_dec(total_nf, 2)
        for parc in parcelas_xml:
            dup = etree.SubElement(cobr, f"{{{ns}}}dup")
            etree.SubElement(dup, f"{{{ns}}}nDup").text = parc.numero
            etree.SubElement(dup, f"{{{ns}}}dVenc").text = parc.vencimento.strftime("%Y-%m-%d")
            etree.SubElement(dup, f"{{{ns}}}vDup").text = _fmt_dec(parc.valor, 2)

    pag = etree.SubElement(inf, f"{{{ns}}}pag")
    det_pag = etree.SubElement(pag, f"{{{ns}}}detPag")
    etree.SubElement(det_pag, f"{{{ns}}}indPag").text = "0" if avista else "1"
    t_pag = tpag_nfe_da_venda(
        venda,
        t_pag_cfg=str(cfg.get("t_pag", "")).strip() or None,
        avista=avista,
    )
    etree.SubElement(det_pag, f"{{{ns}}}tPag").text = t_pag
    # cStat 441: tPag=99 exige xPag (descricao do meio de pagamento)
    x_pag = xpag_nfe_da_venda(venda, t_pag=t_pag)
    if x_pag:
        etree.SubElement(det_pag, f"{{{ns}}}xPag").text = x_pag
    etree.SubElement(det_pag, f"{{{ns}}}vPag").text = _fmt_dec(total_nf, 2)

    inf_adic = etree.SubElement(inf, f"{{{ns}}}infAdic")
    info_adicional = str(cfg.get("inf_cpl", "")).strip()
    if not info_adicional:
        info_adicional = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL" if ambiente == "homologacao" else "DOCUMENTO GERADO PELO ONIX SYSTEM"
    extra = ""
    if observacao_complementar:
        extra = re.sub(r"[\r\n\t]+", " ", str(observacao_complementar).strip())
        extra = extra[:4500] if extra else ""
    if extra:
        sep = " - " if info_adicional else ""
        merged = f"{info_adicional}{sep}{extra}"
        info_adicional = merged
    prazo_imp = texto_prazo_condicao_impressao(venda).strip()
    if prazo_imp and prazo_imp not in info_adicional:
        sep = " - " if info_adicional else ""
        info_adicional = f"{info_adicional}{sep}Prazo pagamento: {prazo_imp}"
    info_adicional = _sanitizar_inf_cpl(info_adicional)
    etree.SubElement(inf_adic, f"{{{ns}}}infCpl").text = info_adicional

    resp_tec = etree.SubElement(inf, f"{{{ns}}}infRespTec")
    cnpj_resp_tec_cfg = _somente_digitos(
        str(
            cfg.get(f"cnpj_responsavel_tecnico_{ambiente}", "")
            or cfg.get("cnpj_responsavel_tecnico", "")
            or cfg.get("cnpj_resp_tec", "")
        ).strip()
    )
    etree.SubElement(resp_tec, f"{{{ns}}}CNPJ").text = cnpj_resp_tec_cfg or cnpj
    etree.SubElement(resp_tec, f"{{{ns}}}xContato").text = "ONIX SYSTEM"
    etree.SubElement(resp_tec, f"{{{ns}}}email").text = "suporte@onixsystem.com.br"
    etree.SubElement(resp_tec, f"{{{ns}}}fone").text = "41900000000"
    id_csrt, csrt = resolver_csrt_nfe_cfg(cfg, ambiente)
    if id_csrt and csrt:
        hash_csrt = base64.b64encode(hashlib.sha1(f"{csrt}{chave}".encode("utf-8")).digest()).decode("ascii")
        etree.SubElement(resp_tec, f"{{{ns}}}idCSRT").text = id_csrt
        etree.SubElement(resp_tec, f"{{{ns}}}hashCSRT").text = hash_csrt

    pfx_bytes = cert_path.read_bytes()
    key, cert, _ = pkcs12.load_key_and_certificates(pfx_bytes, cert_password.encode("utf-8"))
    if not key or not cert:
        raise ValueError("Falha ao ler certificado A1 para assinatura.")
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    cert_pem = cert.public_bytes(Encoding.PEM)

    signer = _NFeXMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha1",
        digest_algorithm="sha1",
        c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315",
    )
    # Evita prefixo "ds:" na assinatura para aderir ao parser mais estrito da SEFAZ/PR.
    signer.namespaces = {None: "http://www.w3.org/2000/09/xmldsig#"}
    signed = signer.sign(
        nfe,
        key=key_pem,
        cert=cert_pem,
        reference_uri=f"#{inf_id}",
        id_attribute="Id",
    )

    out_dir = nfe_out_ambiente(base_dir, ambiente)
    out_dir.mkdir(parents=True, exist_ok=True)
    xml_assinado_path = out_dir / f"{chave}-nfe-assinada.xml"
    xml_assinado = etree.tostring(signed, xml_declaration=True, encoding="utf-8", pretty_print=True)
    xml_assinado_path.write_bytes(xml_assinado)

    return {
        "chave": chave,
        "arquivo_xml_assinado": str(xml_assinado_path),
        "ambiente": ambiente,
        "autorizado": False,
        "mensagem": "XML NF-e assinado gerado com sucesso (transmissao/autorizacao SEFAZ ainda nao implementada).",
    }


def gerar_nfe_homolog_xml_assinado(db, venda: Venda, base_dir: Path) -> dict:
    """Compatibilidade retroativa: nome antigo, comportamento novo por ambiente."""
    return gerar_nfe_xml_assinado(db, venda, base_dir)
