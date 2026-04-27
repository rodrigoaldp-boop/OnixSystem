"""Geracao de XML NF-e assinado por ambiente, sem transmissao SEFAZ."""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import json
import random
import re

from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, pkcs12
from lxml import etree
from signxml import XMLSigner, methods

from sga_financeiro.models.venda import Venda


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D+", "", valor or "")


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


def _load_nfe_config(base_dir: Path) -> dict:
    cfg_path = base_dir / "nfe_config.json"
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
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


def gerar_nfe_xml_assinado(venda: Venda, base_dir: Path) -> dict:
    cfg = _load_nfe_config(base_dir)
    ambiente = str(cfg.get("ambiente", "homologacao")).lower()
    if ambiente not in {"homologacao", "producao"}:
        raise ValueError("Ambiente NF-e invalido. Use homologacao ou producao.")

    cnpj = _somente_digitos(str(cfg.get("cnpj_emitente", "")))
    ie_cfg = str(cfg.get("ie_emitente", "")).strip()
    ie = "ISENTO" if ie_cfg.upper() == "ISENTO" else _somente_digitos(ie_cfg)
    crt = str(cfg.get("crt", "simples")).lower()
    serie = int(cfg.get("serie", 1) or 1)
    cfop = str(cfg.get("cfop_padrao", "5102")).strip() or "5102"
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

    numero_nf = int(_somente_digitos(venda.numero) or venda.id or 1)
    numero_nf = max(1, numero_nf)
    dh_emi = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
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

    ns = "http://www.portalfiscal.inf.br/nfe"
    nfe = etree.Element(f"{{{ns}}}NFe", nsmap={None: ns})
    inf = etree.SubElement(nfe, f"{{{ns}}}infNFe", Id=inf_id, versao="4.00")

    ide = etree.SubElement(inf, f"{{{ns}}}ide")
    etree.SubElement(ide, f"{{{ns}}}cUF").text = cuf
    etree.SubElement(ide, f"{{{ns}}}cNF").text = c_nf
    etree.SubElement(ide, f"{{{ns}}}natOp").text = "Venda"
    etree.SubElement(ide, f"{{{ns}}}mod").text = "55"
    etree.SubElement(ide, f"{{{ns}}}serie").text = str(serie)
    etree.SubElement(ide, f"{{{ns}}}nNF").text = str(numero_nf)
    etree.SubElement(ide, f"{{{ns}}}dhEmi").text = dh_emi
    etree.SubElement(ide, f"{{{ns}}}tpNF").text = "1"
    etree.SubElement(ide, f"{{{ns}}}idDest").text = "1"
    etree.SubElement(ide, f"{{{ns}}}cMunFG").text = "4106902"
    etree.SubElement(ide, f"{{{ns}}}tpImp").text = "1"
    etree.SubElement(ide, f"{{{ns}}}tpEmis").text = "1"
    etree.SubElement(ide, f"{{{ns}}}cDV").text = dv
    etree.SubElement(ide, f"{{{ns}}}tpAmb").text = "2" if ambiente == "homologacao" else "1"
    etree.SubElement(ide, f"{{{ns}}}finNFe").text = "1"
    etree.SubElement(ide, f"{{{ns}}}indFinal").text = "1"
    etree.SubElement(ide, f"{{{ns}}}indPres").text = "1"
    etree.SubElement(ide, f"{{{ns}}}procEmi").text = "0"
    etree.SubElement(ide, f"{{{ns}}}verProc").text = "OnixSystem-1.0"

    emit = etree.SubElement(inf, f"{{{ns}}}emit")
    etree.SubElement(emit, f"{{{ns}}}CNPJ").text = cnpj
    etree.SubElement(emit, f"{{{ns}}}xNome").text = "ONIX BRASIL SYSTEM LTDA"
    ender_emit = etree.SubElement(emit, f"{{{ns}}}enderEmit")
    etree.SubElement(ender_emit, f"{{{ns}}}xLgr").text = "RUA VALADOLID"
    etree.SubElement(ender_emit, f"{{{ns}}}nro").text = "0"
    etree.SubElement(ender_emit, f"{{{ns}}}xBairro").text = "CENTRO"
    etree.SubElement(ender_emit, f"{{{ns}}}cMun").text = "4106902"
    etree.SubElement(ender_emit, f"{{{ns}}}xMun").text = "CURITIBA"
    etree.SubElement(ender_emit, f"{{{ns}}}UF").text = "PR"
    etree.SubElement(ender_emit, f"{{{ns}}}CEP").text = "80000000"
    etree.SubElement(ender_emit, f"{{{ns}}}cPais").text = "1058"
    etree.SubElement(ender_emit, f"{{{ns}}}xPais").text = "BRASIL"
    etree.SubElement(ender_emit, f"{{{ns}}}fone").text = "41900000000"
    etree.SubElement(emit, f"{{{ns}}}IE").text = ie
    etree.SubElement(emit, f"{{{ns}}}CRT").text = "1" if crt == "simples" else ("3" if crt == "real" else "2")

    dest = etree.SubElement(inf, f"{{{ns}}}dest")
    etree.SubElement(dest, f"{{{ns}}}CPF").text = "12345678909"
    etree.SubElement(dest, f"{{{ns}}}xNome").text = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
    ender_dest = etree.SubElement(dest, f"{{{ns}}}enderDest")
    etree.SubElement(ender_dest, f"{{{ns}}}xLgr").text = "RUA TESTE"
    etree.SubElement(ender_dest, f"{{{ns}}}nro").text = "0"
    etree.SubElement(ender_dest, f"{{{ns}}}xBairro").text = "CENTRO"
    etree.SubElement(ender_dest, f"{{{ns}}}cMun").text = "4106902"
    etree.SubElement(ender_dest, f"{{{ns}}}xMun").text = "CURITIBA"
    etree.SubElement(ender_dest, f"{{{ns}}}UF").text = "PR"
    etree.SubElement(ender_dest, f"{{{ns}}}CEP").text = "80000000"
    etree.SubElement(ender_dest, f"{{{ns}}}cPais").text = "1058"
    etree.SubElement(ender_dest, f"{{{ns}}}xPais").text = "BRASIL"
    etree.SubElement(dest, f"{{{ns}}}indIEDest").text = "9"

    for idx, item in enumerate(venda.itens, start=1):
        det = etree.SubElement(inf, f"{{{ns}}}det", nItem=str(idx))
        prod = etree.SubElement(det, f"{{{ns}}}prod")
        etree.SubElement(prod, f"{{{ns}}}cProd").text = str(item.produto_id)
        etree.SubElement(prod, f"{{{ns}}}cEAN").text = "SEM GTIN"
        etree.SubElement(prod, f"{{{ns}}}xProd").text = f"ITEM {item.produto_id}"
        etree.SubElement(prod, f"{{{ns}}}NCM").text = "00000000"
        etree.SubElement(prod, f"{{{ns}}}CFOP").text = cfop
        etree.SubElement(prod, f"{{{ns}}}uCom").text = "UN"
        etree.SubElement(prod, f"{{{ns}}}qCom").text = _fmt_dec(Decimal(item.quantidade or 0), 4)
        etree.SubElement(prod, f"{{{ns}}}vUnCom").text = _fmt_dec(Decimal(item.valor_unitario or 0), 2)
        etree.SubElement(prod, f"{{{ns}}}vProd").text = _fmt_dec(Decimal(item.total_item or 0), 2)
        etree.SubElement(prod, f"{{{ns}}}cEANTrib").text = "SEM GTIN"
        etree.SubElement(prod, f"{{{ns}}}uTrib").text = "UN"
        etree.SubElement(prod, f"{{{ns}}}qTrib").text = _fmt_dec(Decimal(item.quantidade or 0), 4)
        etree.SubElement(prod, f"{{{ns}}}vUnTrib").text = _fmt_dec(Decimal(item.valor_unitario or 0), 2)
        etree.SubElement(prod, f"{{{ns}}}indTot").text = "1"

        imposto = etree.SubElement(det, f"{{{ns}}}imposto")
        icms = etree.SubElement(imposto, f"{{{ns}}}ICMS")
        icmssn = etree.SubElement(icms, f"{{{ns}}}ICMSSN102")
        etree.SubElement(icmssn, f"{{{ns}}}orig").text = "0"
        etree.SubElement(icmssn, f"{{{ns}}}CSOSN").text = csosn

        pis = etree.SubElement(imposto, f"{{{ns}}}PIS")
        pis_outr = etree.SubElement(pis, f"{{{ns}}}PISOutr")
        etree.SubElement(pis_outr, f"{{{ns}}}CST").text = "99"
        etree.SubElement(pis_outr, f"{{{ns}}}vBC").text = _fmt_dec(Decimal(item.total_item or 0), 2)
        etree.SubElement(pis_outr, f"{{{ns}}}pPIS").text = "0.00"
        etree.SubElement(pis_outr, f"{{{ns}}}vPIS").text = "0.00"

        cofins = etree.SubElement(imposto, f"{{{ns}}}COFINS")
        cof_outr = etree.SubElement(cofins, f"{{{ns}}}COFINSOutr")
        etree.SubElement(cof_outr, f"{{{ns}}}CST").text = "99"
        etree.SubElement(cof_outr, f"{{{ns}}}vBC").text = _fmt_dec(Decimal(item.total_item or 0), 2)
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

    transp = etree.SubElement(inf, f"{{{ns}}}transp")
    etree.SubElement(transp, f"{{{ns}}}modFrete").text = "9"

    pag = etree.SubElement(inf, f"{{{ns}}}pag")
    det_pag = etree.SubElement(pag, f"{{{ns}}}detPag")
    etree.SubElement(det_pag, f"{{{ns}}}tPag").text = "90"
    etree.SubElement(det_pag, f"{{{ns}}}vPag").text = "0.00"

    inf_adic = etree.SubElement(inf, f"{{{ns}}}infAdic")
    info_adicional = "DOCUMENTO GERADO PELO ONIX SYSTEM - AGUARDANDO TRANSMISSAO SEFAZ"
    if ambiente == "homologacao":
        info_adicional = "NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL"
    etree.SubElement(inf_adic, f"{{{ns}}}infCpl").text = info_adicional

    resp_tec = etree.SubElement(inf, f"{{{ns}}}infRespTec")
    cnpj_resp_tec_cfg = _somente_digitos(
        str(cfg.get("cnpj_responsavel_tecnico", "") or cfg.get("cnpj_resp_tec", "")).strip()
    )
    etree.SubElement(resp_tec, f"{{{ns}}}CNPJ").text = cnpj_resp_tec_cfg or cnpj
    etree.SubElement(resp_tec, f"{{{ns}}}xContato").text = "ONIX SYSTEM"
    etree.SubElement(resp_tec, f"{{{ns}}}email").text = "suporte@onixsystem.com.br"
    etree.SubElement(resp_tec, f"{{{ns}}}fone").text = "41900000000"
    id_csrt_raw = _somente_digitos(str(cfg.get("id_csrt", "")).strip())
    id_csrt = id_csrt_raw.zfill(2) if id_csrt_raw else ""
    csrt = str(cfg.get("csrt", "")).strip()
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

    out_dir = base_dir / "nfe_out" / ambiente
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


def gerar_nfe_homolog_xml_assinado(venda: Venda, base_dir: Path) -> dict:
    """Compatibilidade retroativa: nome antigo, comportamento novo por ambiente."""
    return gerar_nfe_xml_assinado(venda, base_dir)
