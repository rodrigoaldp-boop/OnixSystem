"""Fluxo basico de autorizacao NF-e na SEFAZ (envio e consulta de recibo)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
from datetime import datetime
import re
import ssl
import tempfile
import time
from urllib import request
from typing import Any
from lxml import etree
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, pkcs12
from requests import Session
from zeep import Client
from zeep import Settings as ZeepSettings
from zeep.plugins import HistoryPlugin
from zeep.transports import Transport


@dataclass
class ResultadoAutorizacaoNfe:
    autorizado: bool
    ambiente: str
    status: str
    mensagem: str
    lote_id: str | None = None
    protocolo: str | None = None
    recibo: str | None = None
    cstat: str | None = None
    xmotivo: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "autorizado": self.autorizado,
            "ambiente": self.ambiente,
            "status": self.status,
            "mensagem": self.mensagem,
            "lote_id": self.lote_id,
            "protocolo": self.protocolo,
            "recibo": self.recibo,
            "cstat": self.cstat,
            "xmotivo": self.xmotivo,
        }


def _load_nfe_config(base_dir: Path) -> dict[str, Any]:
    cfg_path = base_dir / "nfe_config.json"
    if not cfg_path.exists():
        return {}
    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _somente_digitos(valor: str) -> str:
    return re.sub(r"\D+", "", valor or "")


def _uf_codigo(uf: str) -> str:
    tabela = {
        "PR": "41",
    }
    return tabela.get((uf or "").upper(), "41")


def _sefaz_urls(uf: str, ambiente: str) -> tuple[str, str]:
    uf = (uf or "PR").upper()
    ambiente = (ambiente or "homologacao").lower()
    if uf != "PR":
        raise ValueError("UF ainda nao suportada para autorizacao automatica neste passo.")
    if ambiente == "producao":
        return (
            "https://nfe.sefa.pr.gov.br/nfe/NFeAutorizacao4",
            "https://nfe.sefa.pr.gov.br/nfe/NFeRetAutorizacao4",
        )
    return (
        "https://homologacao.nfe.sefa.pr.gov.br/nfe/NFeAutorizacao4",
        "https://homologacao.nfe.sefa.pr.gov.br/nfe/NFeRetAutorizacao4",
    )


def _build_envi_nfe(xml_nfe: bytes, lote_id: str) -> etree._Element:
    ns = "http://www.portalfiscal.inf.br/nfe"
    envi = etree.Element(f"{{{ns}}}enviNFe", nsmap={None: ns}, versao="4.00")
    etree.SubElement(envi, f"{{{ns}}}idLote").text = lote_id
    etree.SubElement(envi, f"{{{ns}}}indSinc").text = "1"
    parser = etree.XMLParser(remove_blank_text=True)
    nfe_node = etree.fromstring(xml_nfe, parser=parser)
    for e in nfe_node.iter():
        if e.text is not None and isinstance(e.text, str):
            if not e.text.strip():
                e.text = None
        if e.tail is not None and isinstance(e.tail, str):
            if not e.tail.strip():
                e.tail = None
    _forcar_namespace_nfe(nfe_node, ns)
    envi.append(nfe_node)
    return envi


def _forcar_namespace_nfe(node: etree._Element, ns: str) -> None:
    """Garante namespace padrao da NF-e em toda a arvore."""
    if isinstance(node.tag, str) and not node.tag.startswith("{"):
        node.tag = f"{{{ns}}}{node.tag}"
    for child in list(node):
        _forcar_namespace_nfe(child, ns)


def _soap_envelope_autorizacao(uf: str, envi_nfe: etree._Element) -> bytes:
    soap_ns = "http://www.w3.org/2003/05/soap-envelope"
    ws_ns = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4"
    env = etree.Element(f"{{{soap_ns}}}Envelope", nsmap={"soap": soap_ns})
    body = etree.SubElement(env, f"{{{soap_ns}}}Body")
    dados = etree.SubElement(body, f"{{{ws_ns}}}nfeDadosMsg", nsmap={None: ws_ns})
    dados.append(envi_nfe)
    _ = uf
    return etree.tostring(env, encoding="utf-8", xml_declaration=True)


def _soap_envelope_retorno(uf: str, ambiente: str, recibo: str) -> bytes:
    soap_ns = "http://www.w3.org/2003/05/soap-envelope"
    ws_ns = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRetAutorizacao4"
    nfe_ns = "http://www.portalfiscal.inf.br/nfe"
    env = etree.Element(f"{{{soap_ns}}}Envelope", nsmap={"soap": soap_ns})
    body = etree.SubElement(env, f"{{{soap_ns}}}Body")
    dados = etree.SubElement(body, f"{{{ws_ns}}}nfeDadosMsg", nsmap={None: ws_ns})
    cons = etree.SubElement(dados, f"{{{nfe_ns}}}consReciNFe", versao="4.00", nsmap={None: nfe_ns})
    etree.SubElement(cons, f"{{{nfe_ns}}}tpAmb").text = "1" if ambiente == "producao" else "2"
    etree.SubElement(cons, f"{{{nfe_ns}}}nRec").text = recibo
    _ = uf
    return etree.tostring(env, encoding="utf-8", xml_declaration=True)


def _post_soap(url: str, payload: bytes, context: ssl.SSLContext, action: str) -> bytes:
    req = request.Request(
        url=url,
        data=payload,
        headers={
            "Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"',
            "Accept": "application/soap+xml, application/xml, text/xml",
        },
        method="POST",
    )
    with request.urlopen(req, context=context, timeout=45) as resp:
        return resp.read()


def _extrair_ret_nfe_zeep(history: HistoryPlugin) -> etree._Element | None:
    if not history.last_received:
        return None
    envelope = history.last_received.get("envelope")
    if envelope is None:
        return None
    node = envelope.xpath("//*[local-name()='retEnviNFe']")
    if node:
        return node[0]
    node = envelope.xpath("//*[local-name()='retConsReciNFe']")
    if node:
        return node[0]
    return None


def _extract_ret_envi_nfe(xml_bytes: bytes) -> etree._Element | None:
    doc = etree.fromstring(xml_bytes)
    ns = {"n": "http://www.portalfiscal.inf.br/nfe"}
    node = doc.xpath("//*[local-name()='retEnviNFe']")
    if node:
        return node[0]
    node = doc.xpath("//*[local-name()='retConsReciNFe']")
    if node:
        return node[0]
    node = doc.xpath("//*[local-name()='protNFe']")
    if node:
        return node[0]
    _ = ns
    return None


def _txt(node: etree._Element | None, tag_name: str) -> str | None:
    if node is None:
        return None
    match = node.xpath(f".//*[local-name()='{tag_name}']")
    if not match:
        return None
    txt = match[0].text
    return txt.strip() if txt else None


def _build_ssl_context_from_pfx(cert_path: Path, cert_password: str, ssl_verify: bool = False) -> tuple[ssl.SSLContext, list[Path]]:
    blob = cert_path.read_bytes()
    key, cert, extras = pkcs12.load_key_and_certificates(blob, cert_password.encode("utf-8"))
    if not key or not cert:
        raise ValueError("Certificado A1 invalido ou sem chave privada.")
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    cert_chain = cert.public_bytes(Encoding.PEM)
    for item in extras or []:
        cert_chain += item.public_bytes(Encoding.PEM)

    tmp_key = tempfile.NamedTemporaryFile(delete=False, suffix=".key.pem")
    tmp_crt = tempfile.NamedTemporaryFile(delete=False, suffix=".crt.pem")
    tmp_key.write(key_pem)
    tmp_crt.write(cert_chain)
    tmp_key.close()
    tmp_crt.close()
    tmp_paths = [Path(tmp_key.name), Path(tmp_crt.name)]
    ctx = ssl.create_default_context()
    if not ssl_verify:
        # Alguns endpoints SEFAZ podem apresentar cadeia SSL nao padrao no ambiente.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(certfile=str(tmp_paths[1]), keyfile=str(tmp_paths[0]))
    return ctx, tmp_paths


def autorizar_nfe_sefaz(base_dir: Path, chave: str, xml_path: str) -> ResultadoAutorizacaoNfe:
    """Envia XML assinado para autorizacao e consulta retorno de recibo."""
    cfg = _load_nfe_config(base_dir)
    ambiente = str(cfg.get("ambiente", "homologacao")).lower()
    uf = str(cfg.get("uf", "PR")).upper()
    cert_path = Path(str(cfg.get("cert_path", "")).strip())
    cert_password = str(cfg.get("cert_password", "")).strip()
    ssl_verify = bool(cfg.get("ssl_verify", False))
    lote_id = datetime.now().strftime("%Y%m%d%H%M%S")
    if ambiente not in {"homologacao", "producao"}:
        return ResultadoAutorizacaoNfe(
            autorizado=False,
            ambiente=ambiente,
            status="erro_config",
            mensagem="Ambiente NF-e invalido.",
            lote_id=lote_id,
        )
    if not cert_path.exists() or not cert_password:
        return ResultadoAutorizacaoNfe(
            autorizado=False,
            ambiente=ambiente,
            status="erro_config",
            mensagem="Certificado A1 ou senha nao configurados.",
            lote_id=lote_id,
        )
    xml_file = Path(xml_path)
    if not xml_file.exists():
        return ResultadoAutorizacaoNfe(
            autorizado=False,
            ambiente=ambiente,
            status="erro_xml",
            mensagem="Arquivo XML assinado nao encontrado.",
            lote_id=lote_id,
        )

    try:
        url_envio, url_retorno = _sefaz_urls(uf=uf, ambiente=ambiente)
        xml_nfe = xml_file.read_bytes()
        envi_nfe = _build_envi_nfe(xml_nfe=xml_nfe, lote_id=lote_id)
        payload_envio = _soap_envelope_autorizacao(uf=uf, envi_nfe=envi_nfe)
        ssl_ctx, tmp_paths = _build_ssl_context_from_pfx(
            cert_path=cert_path,
            cert_password=cert_password,
            ssl_verify=ssl_verify,
        )
        try:
            ret_envio = None
            try:
                session = Session()
                session.verify = ssl_verify
                session.cert = (str(tmp_paths[1]), str(tmp_paths[0]))
                history_envio = HistoryPlugin()
                client_envio = Client(
                    wsdl=f"{url_envio}?wsdl",
                    transport=Transport(session=session, timeout=45, operation_timeout=45),
                    settings=ZeepSettings(strict=False, xml_huge_tree=True),
                    plugins=[history_envio],
                )
                client_envio.service.nfeAutorizacaoLote(nfeDadosMsg=envi_nfe)
                ret_envio = _extrair_ret_nfe_zeep(history_envio)
            except Exception:
                resp_envio = _post_soap(
                    url_envio,
                    payload_envio,
                    ssl_ctx,
                    action="http://www.portalfiscal.inf.br/nfe/wsdl/NFeAutorizacao4/nfeAutorizacaoLote",
                )
                ret_envio = _extract_ret_envi_nfe(resp_envio)
            cstat = _txt(ret_envio, "cStat")
            xmotivo = _txt(ret_envio, "xMotivo")
            recibo = _txt(ret_envio, "nRec")
            if cstat == "100":
                protocolo = _txt(ret_envio, "nProt")
                return ResultadoAutorizacaoNfe(
                    autorizado=True,
                    ambiente=ambiente,
                    status="autorizado",
                    mensagem="NF-e autorizada com sucesso.",
                    lote_id=lote_id,
                    protocolo=protocolo,
                    recibo=recibo,
                    cstat=cstat,
                    xmotivo=xmotivo,
                )
            if cstat != "103" or not recibo:
                return ResultadoAutorizacaoNfe(
                    autorizado=False,
                    ambiente=ambiente,
                    status="retorno_imediato",
                    mensagem="SEFAZ retornou status sem recibo para consulta.",
                    lote_id=lote_id,
                    recibo=recibo,
                    cstat=cstat,
                    xmotivo=xmotivo,
                )

            for _ in range(8):
                time.sleep(2.0)
                payload_ret = _soap_envelope_retorno(uf=uf, ambiente=ambiente, recibo=recibo)
                ret_cons = None
                try:
                    session_ret = Session()
                    session_ret.verify = ssl_verify
                    session_ret.cert = (str(tmp_paths[1]), str(tmp_paths[0]))
                    history_ret = HistoryPlugin()
                    client_ret = Client(
                        wsdl=f"{url_retorno}?wsdl",
                        transport=Transport(session=session_ret, timeout=45, operation_timeout=45),
                        settings=ZeepSettings(strict=False, xml_huge_tree=True),
                        plugins=[history_ret],
                    )
                    cons = etree.fromstring(payload_ret).xpath("//*[local-name()='consReciNFe']")
                    client_ret.service.nfeRetAutorizacaoLote(nfeDadosMsg=cons[0] if cons else None)
                    ret_cons = _extrair_ret_nfe_zeep(history_ret)
                except Exception:
                    resp_ret = _post_soap(
                        url_retorno,
                        payload_ret,
                        ssl_ctx,
                        action="http://www.portalfiscal.inf.br/nfe/wsdl/NFeRetAutorizacao4/NFeRetAutorizacaoLote",
                    )
                    ret_cons = _extract_ret_envi_nfe(resp_ret)
                cstat_ret = _txt(ret_cons, "cStat")
                xmotivo_ret = _txt(ret_cons, "xMotivo")
                if cstat_ret == "104":
                    inf_prot = ret_cons.xpath(".//*[local-name()='infProt']")
                    cstat_final = _txt(inf_prot[0], "cStat") if inf_prot else None
                    xmotivo_final = _txt(inf_prot[0], "xMotivo") if inf_prot else None
                    protocolo = _txt(inf_prot[0], "nProt") if inf_prot else None
                    autorizado = cstat_final in {"100", "150"}
                    return ResultadoAutorizacaoNfe(
                        autorizado=autorizado,
                        ambiente=ambiente,
                        status="autorizado" if autorizado else "rejeitado",
                        mensagem="NF-e autorizada." if autorizado else "NF-e rejeitada pela SEFAZ.",
                        lote_id=lote_id,
                        protocolo=protocolo,
                        recibo=recibo,
                        cstat=cstat_final,
                        xmotivo=xmotivo_final,
                    )
                if cstat_ret not in {"105"}:
                    return ResultadoAutorizacaoNfe(
                        autorizado=False,
                        ambiente=ambiente,
                        status="retorno_consulta",
                        mensagem="Consulta de recibo retornou status inesperado.",
                        lote_id=lote_id,
                        recibo=recibo,
                        cstat=cstat_ret,
                        xmotivo=xmotivo_ret,
                    )
            return ResultadoAutorizacaoNfe(
                autorizado=False,
                ambiente=ambiente,
                status="timeout_consulta",
                mensagem="Tempo de espera excedido ao consultar recibo na SEFAZ.",
                lote_id=lote_id,
                recibo=recibo,
                cstat="105",
                xmotivo="Lote em processamento por muito tempo.",
            )
        finally:
            for p in tmp_paths:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception as exc:
        return ResultadoAutorizacaoNfe(
            autorizado=False,
            ambiente=ambiente,
            status="erro_transmissao",
            mensagem=f"Falha na comunicacao com SEFAZ: {exc}",
            lote_id=lote_id,
            cstat=None,
            xmotivo=f"Chave {chave}",
        )
