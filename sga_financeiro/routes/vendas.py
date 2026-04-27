"""Endpoints de vendas."""

from __future__ import annotations

import re
from io import BytesIO
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from sga_financeiro.database import get_db
from sga_financeiro.models.cadastro_geral import CadastroGeral
from sga_financeiro.models.categoria import Categoria, TipoCategoria
from sga_financeiro.models.centro_custos import CentroCustos
from sga_financeiro.models.cliente import Cliente
from sga_financeiro.models.condicao_pagamento import CondicaoPagamento
from sga_financeiro.models.conta_receber import ContaReceber, StatusContaReceber
from sga_financeiro.models.produto import Produto
from sga_financeiro.models.venda import Venda
from sga_financeiro.models.venda_item import VendaItem
from sga_financeiro.schemas.venda import VendaCreate, VendaItemOut, VendaOut, VendaUpdate
from sga_financeiro.services.nfe_homolog_service import gerar_nfe_xml_assinado
from sga_financeiro.services.nfe_autorizacao_service import autorizar_nfe_sefaz

router = APIRouter(prefix="/vendas", tags=["Vendas"])

NUMERO_INICIAL_PEDIDO = 1007
PASSO_NUMERO_PEDIDO = 9


def _pdf_escape(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _gerar_pdf_venda(db: Session, venda: Venda) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def _txt(valor: str | None) -> str:
        return (valor or "-").strip() or "-"

    cliente = db.get(CadastroGeral, venda.cliente_id) if venda.cliente_id else None
    vendedor = db.get(CadastroGeral, venda.vendedor_id) if venda.vendedor_id else None
    fornecedor = (
        db.query(CadastroGeral)
        .filter(CadastroGeral.contexto != "pessoas")
        .order_by(CadastroGeral.id.desc())
        .first()
    )

    produtos_ids = [i.produto_id for i in venda.itens]
    produtos: dict[int, Produto] = {}
    if produtos_ids:
        for p in db.query(Produto).filter(Produto.id.in_(produtos_ids)).all():
            produtos[p.id] = p

    buff = BytesIO()
    doc = SimpleDocTemplate(
        buff,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"Pedido {venda.numero}",
    )
    styles = getSampleStyleSheet()
    azul_onix = colors.HexColor("#1d2f72")
    azul_tarja = colors.HexColor("#3b82f6")
    st_title_left = ParagraphStyle(
        "title_left",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.white,
        alignment=0,
    )
    st_title_right = ParagraphStyle(
        "title_right",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=colors.white,
        alignment=2,
    )
    st_sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, leading=12, textColor=colors.HexColor("#1e293b"))
    st_card_l = ParagraphStyle("cardl", parent=styles["Normal"], fontSize=8.7, leading=11, textColor=colors.HexColor("#1f2937"))

    elementos = []
    topo = Table(
        [[Paragraph("Pedido de venda", st_title_left), Paragraph(f"Nº {venda.numero}", st_title_right)]],
        colWidths=[130 * mm, 46 * mm],
    )
    topo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), azul_tarja),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elementos.append(topo)
    elementos.append(Spacer(1, 7))

    fornecedor_bloco = [
        Paragraph(f"<b>{_txt((fornecedor.razao_social if fornecedor else None) or 'ONIX BRASIL SYSTEM')}</b>", st_card_l),
        Paragraph(f"CNPJ/CPF: {_txt(fornecedor.cnpj if fornecedor else None)}", st_card_l),
        Paragraph(f"Telefone: {_txt(fornecedor.telefone if fornecedor else None)}", st_card_l),
        Paragraph(f"Endereco: {_txt(fornecedor.endereco if fornecedor else None)}", st_card_l),
        Paragraph(f"<b>Data emissao:</b> {venda.created_at.strftime('%d/%m/%Y')}", st_card_l),
        Paragraph(f"<b>Condicao:</b> {_txt(venda.condicao_pag_catalogo.nome if venda.condicao_pag_catalogo else None)}", st_card_l),
    ]
    cliente_bloco = [
        Paragraph(f"<b>{_txt(cliente.razao_social if cliente else None)}</b>", st_card_l),
        Paragraph(f"CNPJ/CPF: {_txt(cliente.cnpj if cliente else None)}", st_card_l),
        Paragraph(f"Telefone: {_txt(cliente.telefone if cliente else None)}", st_card_l),
        Paragraph(f"Endereco: {_txt(cliente.endereco if cliente else None)}", st_card_l),
        Spacer(1, 5),
        Paragraph(f"<b>Pedido:</b> {_txt(venda.numero)}", st_card_l),
        Paragraph(f"<b>Prazo:</b> {_txt(venda.prazo_pagamento)}", st_card_l),
    ]
    partes = Table(
        [[fornecedor_bloco, cliente_bloco]],
        colWidths=[88 * mm, 88 * mm],
    )
    partes.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, azul_onix),
        ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#dbe4ff")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fbff")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    elementos.append(partes)
    elementos.append(Spacer(1, 6))

    vendedor_tbl = Table(
        [
            [
                Paragraph("<b>Nome</b>", st_sub),
                Paragraph("<b>Fone</b>", st_sub),
            ],
            [
                Paragraph(_txt(vendedor.razao_social if vendedor else None), st_card_l),
                Paragraph(_txt(vendedor.telefone if vendedor else None), st_card_l),
            ],
        ],
        colWidths=[88 * mm, 88 * mm],
    )
    vendedor_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), azul_tarja),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, azul_onix),
        ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#dbe4ff")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elementos.append(vendedor_tbl)
    elementos.append(Spacer(1, 10))

    itens_header = ["Item", "Descricao", "Qtd", "Vlr Unit", "Desc", "Total"]
    itens_data = [itens_header]
    for idx, item in enumerate(venda.itens, start=1):
        produto = produtos.get(item.produto_id)
        itens_data.append([
            str(idx),
            _txt(produto.nome if produto else f"Produto ID {item.produto_id}"),
            f"{Decimal(item.quantidade):.4f}",
            f"R$ {Decimal(item.valor_unitario):.2f}",
            f"R$ {Decimal(item.desconto or 0):.2f}",
            f"R$ {Decimal(item.total_item):.2f}",
        ])
    tabela_itens = Table(itens_data, colWidths=[12 * mm, 84 * mm, 19 * mm, 21 * mm, 19 * mm, 21 * mm], repeatRows=1)
    tabela_itens.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), azul_tarja),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.3),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    elementos.append(tabela_itens)
    elementos.append(Spacer(1, 8))

    resumo = Table(
        [[
            Paragraph(f"<b>Prazo:</b> {_txt(venda.prazo_pagamento)}", st_sub),
            Paragraph(f"<b>Frete:</b> R$ {Decimal(venda.valor_frete or 0):.2f}", st_sub),
            Paragraph(f"<b>Total Bruto:</b> R$ {Decimal(venda.total_bruto or 0):.2f}", st_sub),
            Paragraph(f"<b>Desconto:</b> R$ {Decimal(venda.total_desconto or 0):.2f}", st_sub),
            Paragraph(f"<b>Total Liquido:</b> R$ {Decimal(venda.total_liquido or 0):.2f}", st_sub),
        ]],
        colWidths=[34 * mm, 30 * mm, 34 * mm, 34 * mm, 44 * mm],
    )
    resumo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef4ff")),
        ("BOX", (0, 0), (-1, -1), 0.8, azul_onix),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elementos.append(resumo)

    doc.build(elementos)
    return buff.getvalue()


def _gerar_pdf_nfe_homologacao(db: Session, venda: Venda, chave: str | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.graphics.barcode import code128
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def _txt(valor: str | None) -> str:
        return (valor or "-").strip() or "-"

    def _fmt_chave(valor: str | None) -> str:
        dig = re.sub(r"\D+", "", valor or "")
        if len(dig) != 44:
            return _txt(valor)
        return " ".join(dig[i : i + 4] for i in range(0, 44, 4))

    def _money(valor: Decimal | int | float | None) -> str:
        return f"{Decimal(valor or 0):.2f}"

    cliente = db.get(CadastroGeral, venda.cliente_id) if venda.cliente_id else None
    vendedor = db.get(CadastroGeral, venda.vendedor_id) if venda.vendedor_id else None
    fornecedor = (
        db.query(CadastroGeral)
        .filter(CadastroGeral.contexto != "pessoas")
        .order_by(CadastroGeral.id.desc())
        .first()
    )

    chave_nfe = _txt(chave)
    total_produtos = Decimal(venda.total_bruto or 0)
    total_desconto = Decimal(venda.total_desconto or 0)
    total_nota = Decimal(venda.total_liquido or 0)

    buff = BytesIO()
    doc = SimpleDocTemplate(
        buff,
        pagesize=A4,
        leftMargin=7 * mm,
        rightMargin=7 * mm,
        topMargin=6 * mm,
        bottomMargin=6 * mm,
        title=f"NFe-{venda.numero}",
    )
    styles = getSampleStyleSheet()
    st_tiny = ParagraphStyle("nfe_tiny", parent=styles["Normal"], fontName="Helvetica", fontSize=5.9, leading=6.6)
    st_small = ParagraphStyle("nfe_small", parent=styles["Normal"], fontName="Helvetica", fontSize=6.6, leading=7.2)
    st_small_b = ParagraphStyle("nfe_small_b", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=6.6, leading=7.2)
    st_mid_b = ParagraphStyle(
        "nfe_mid_b",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.4,
        leading=8.8,
        alignment=1,
    )
    st_small_center = ParagraphStyle(
        "nfe_small_center",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=5.4,
        leading=5.4,
        alignment=1,
    )
    st_tiny_key = ParagraphStyle(
        "nfe_tiny_key",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=5.2,
        leading=5.2,
    )
    section_gap = 2.5 * mm

    elementos = []
    largura_util = 196 * mm

    def _add_gap() -> None:
        gap = Table([[""]], colWidths=[largura_util], rowHeights=[section_gap])
        gap.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        elementos.append(gap)

    # Recibo superior
    recibo = Table(
        [
            [Paragraph("RECEBEMOS DE ONIX BRASIL SYSTEM LTDA OS PRODUTOS CONSTANTES DA NOTA FISCAL INDICADA AO LADO", st_tiny), Paragraph("NF-e\nNº 0000281\nSérie 1", st_small_b)],
            [Paragraph("Data de recebimento", st_tiny), Paragraph("Identificacao e assinatura do recebedor", st_tiny)],
        ],
        colWidths=[174 * mm, 22 * mm],
        rowHeights=[9 * mm, 6 * mm],
    )
    recibo.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
        ("SPAN", (0, 0), (0, 0)),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("VALIGN", (1, 0), (1, 0), "MIDDLE"),
    ]))
    elementos.append(recibo)
    _add_gap()

    # Cabecalho DANFE (esquerda emitente, centro titulo, direita chave/barcode)
    emitente_txt = (
        f"<b>{_txt((fornecedor.razao_social if fornecedor else None) or 'ONIX BRASIL SYSTEM LTDA')}</b><br/>"
        f"{_txt(fornecedor.endereco if fornecedor else None)}<br/>"
        f"Fone: {_txt(fornecedor.telefone if fornecedor else None)}<br/>"
        f"CNPJ: {_txt(fornecedor.cnpj if fornecedor else None)}"
    )
    logo_path = Path(
        "/root/.cursor/projects/root-home-projetos-OnixSystem/assets/"
        "c__Users_Rodrigo9_AppData_Roaming_Cursor_User_workspaceStorage_8f3912aa94fb6adb69a786e81e008fd8_images_imagem_zap2-253a778b-9062-45d8-a7c9-d62519325773.png"
    )
    logo_obj = None
    if logo_path.exists():
        try:
            logo_obj = Image(str(logo_path), width=35 * mm, height=16 * mm)
        except Exception:
            logo_obj = None

    emitente_inner_data: list[list[object]] = []
    if logo_obj is not None:
        emitente_inner_data.append([logo_obj, Paragraph(emitente_txt, st_small)])
        emitente_inner = Table(emitente_inner_data, colWidths=[37 * mm, 42 * mm], rowHeights=[22 * mm])
    else:
        emitente_inner_data.append([Paragraph(emitente_txt, st_small)])
        emitente_inner = Table(emitente_inner_data, colWidths=[79 * mm], rowHeights=[22 * mm])
    emitente_inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    box_emitente = Table([[emitente_inner]], colWidths=[79 * mm], rowHeights=[24 * mm])
    box_emitente.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    box_danfe = Table(
        [
            [Paragraph("DANFE", st_mid_b)],
            [Paragraph("Documento Auxiliar", st_small_center)],
            [Paragraph("da Nota Fiscal Eletronica", st_small_center)],
            [Paragraph("0 - ENTRADA", st_small_center)],
            [Paragraph("1 - SAIDA", st_small_center)],
            [Paragraph(f"<b>Nº {venda.numero}</b>", st_small_center)],
            [Paragraph("Série 1", st_small_center)],
            [Paragraph("Página 1 de 1", st_small_center)],
        ],
        colWidths=[40 * mm],
        rowHeights=[4.2 * mm, 2.8 * mm, 2.8 * mm, 2.4 * mm, 2.4 * mm, 2.8 * mm, 2.4 * mm, 2.4 * mm],
    )
    box_danfe.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    barcode = code128.Code128(
        re.sub(r"\D+", "", chave_nfe)[:44] or "00000000000000000000000000000000000000000000",
        barHeight=8.2 * mm,
        barWidth=0.30,
    )
    box_chave = Table(
        [
            [Paragraph("Controle do Fisco", st_tiny_key)],
            [barcode],
            [Paragraph(f"Chave de acesso<br/><b>{_fmt_chave(chave_nfe)}</b>", st_tiny_key)],
            [Paragraph("Consulta de autenticidade no portal nacional da NF-e<br/>www.nfe.fazenda.gov.br/portal", st_tiny_key)],
        ],
        colWidths=[77 * mm],
        rowHeights=[3.0 * mm, 8.8 * mm, 6.1 * mm, 4.1 * mm],
    )
    box_chave.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.2),
        ("ALIGN", (0, 1), (0, 1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    header = Table([[box_emitente, box_danfe, box_chave]], colWidths=[79 * mm, 40 * mm, 77 * mm], rowHeights=[24 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elementos.append(header)
    _add_gap()

    natureza = Table(
        [[Paragraph("Natureza da operacao", st_tiny), Paragraph("Protocolo de autorizacao de uso", st_tiny)],
         [Paragraph("Venda de mercadoria", st_small), Paragraph("HOMOLOGACAO - SEM TRANSMISSAO SEFAZ", st_small)]],
        colWidths=[98 * mm, 98 * mm],
        rowHeights=[4 * mm, 5.5 * mm],
    )
    natureza.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elementos.append(natureza)
    _add_gap()
    elementos.append(Paragraph("<b>Destinatario/Remetente</b>", st_small_b))
    _add_gap()
    dest = Table(
        [
            [
                Paragraph(f"Nome/Razao social<br/><b>{_txt(cliente.razao_social if cliente else None)}</b>", st_tiny),
                Paragraph(f"CNPJ/CPF<br/><b>{_txt(cliente.cnpj if cliente else None)}</b>", st_tiny),
                Paragraph(f"Data emissao<br/><b>{venda.created_at.strftime('%d/%m/%Y')}</b>", st_tiny),
            ],
            [
                Paragraph(f"Endereco<br/><b>{_txt(cliente.endereco if cliente else None)}</b>", st_tiny),
                Paragraph(f"Bairro / Distrito<br/><b>-</b>", st_tiny),
                Paragraph(f"CEP<br/><b>-</b>", st_tiny),
            ],
            [
                Paragraph(f"Municipio<br/><b>-</b>", st_tiny),
                Paragraph("UF<br/><b>PR</b>", st_tiny),
                Paragraph(f"Fone/Fax<br/><b>{_txt(cliente.telefone if cliente else None)}</b>", st_tiny),
            ],
        ],
        colWidths=[104 * mm, 52 * mm, 40 * mm],
        rowHeights=[6 * mm, 6 * mm, 5.5 * mm],
    )
    dest.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elementos.append(dest)
    _add_gap()

    elementos.append(Paragraph("<b>Fatura</b>", st_small_b))
    _add_gap()
    fatura = Table(
        [[
            Paragraph("Numero<br/><b>001</b>", st_tiny),
            Paragraph("Vencimento<br/><b>15/04/2026</b>", st_tiny),
            Paragraph(f"Valor<br/><b>{_money(total_nota)}</b>", st_tiny),
            Paragraph("Numero<br/><b>-</b>", st_tiny),
            Paragraph("Vencimento<br/><b>-</b>", st_tiny),
            Paragraph("Valor<br/><b>-</b>", st_tiny),
        ]],
        colWidths=[24 * mm, 34 * mm, 22 * mm, 24 * mm, 34 * mm, 58 * mm],
        rowHeights=[5.8 * mm],
    )
    fatura.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elementos.append(fatura)
    _add_gap()

    elementos.append(Paragraph("<b>Calculo do imposto</b>", st_small_b))
    _add_gap()
    calculo = Table(
        [
            [
                Paragraph(f"Base de calculo do ICMS<br/><b>0,00</b>", st_tiny),
                Paragraph(f"Valor do ICMS<br/><b>0,00</b>", st_tiny),
                Paragraph(f"Valor total dos produtos<br/><b>{_money(total_produtos)}</b>", st_tiny),
            ],
            [
                Paragraph(f"Valor do frete<br/><b>{_money(venda.valor_frete)}</b>", st_tiny),
                Paragraph(f"Valor do desconto<br/><b>{_money(total_desconto)}</b>", st_tiny),
                Paragraph(f"Valor total da nota<br/><b>{_money(total_nota)}</b>", st_tiny),
            ],
        ],
        colWidths=[65 * mm, 65 * mm, 66 * mm],
        rowHeights=[5.5 * mm, 5.5 * mm],
    )
    calculo.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elementos.append(calculo)
    _add_gap()

    elementos.append(Paragraph("<b>Transportador/Volumes transportados</b>", st_small_b))
    _add_gap()
    transp = Table(
        [
            [
                Paragraph("Nome/Razao social<br/><b>-</b>", st_tiny),
                Paragraph("Frete por conta<br/><b>9 - Sem frete</b>", st_tiny),
                Paragraph("Codigo ANTT<br/><b>-</b>", st_tiny),
                Paragraph("Placa veiculo / UF<br/><b>-</b>", st_tiny),
                Paragraph("CNPJ/CPF<br/><b>-</b>", st_tiny),
            ],
            [
                Paragraph("Endereco<br/><b>-</b>", st_tiny),
                Paragraph("Municipio<br/><b>-</b>", st_tiny),
                Paragraph("UF<br/><b>-</b>", st_tiny),
                Paragraph("Inscricao estadual<br/><b>-</b>", st_tiny),
                Paragraph("", st_tiny),
            ],
            [
                Paragraph("Quantidade<br/><b>0</b>", st_tiny),
                Paragraph("Especie<br/><b>-</b>", st_tiny),
                Paragraph("Marca<br/><b>-</b>", st_tiny),
                Paragraph("Numeracao<br/><b>-</b>", st_tiny),
                Paragraph("Peso liquido<br/><b>0,000</b>", st_tiny),
            ],
        ],
        colWidths=[60 * mm, 35 * mm, 28 * mm, 42 * mm, 31 * mm],
        rowHeights=[5.5 * mm, 5.5 * mm, 5.5 * mm],
    )
    transp.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elementos.append(transp)
    _add_gap()

    itens_data = [[
        Paragraph("Codigo", st_tiny),
        Paragraph("Descricao do produto/servico", st_tiny),
        Paragraph("NCM/SH", st_tiny),
        Paragraph("CFOP", st_tiny),
        Paragraph("UN", st_tiny),
        Paragraph("Qtd", st_tiny),
        Paragraph("Vlr unit", st_tiny),
        Paragraph("Vlr total", st_tiny),
    ]]
    for item in venda.itens:
        itens_data.append([
            Paragraph(str(item.produto_id), st_tiny),
            Paragraph(f"ITEM {item.produto_id}", st_tiny),
            Paragraph("00000000", st_tiny),
            Paragraph("5102", st_tiny),
            Paragraph("UN", st_tiny),
            Paragraph(f"{Decimal(item.quantidade or 0):.4f}", st_tiny),
            Paragraph(_money(item.valor_unitario), st_tiny),
            Paragraph(_money(item.total_item), st_tiny),
        ])
    itens = Table(itens_data, colWidths=[14 * mm, 73 * mm, 18 * mm, 12 * mm, 8 * mm, 16 * mm, 26 * mm, 29 * mm], repeatRows=1)
    itens.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("ALIGN", (5, 1), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 5.9),
    ]))
    _add_gap()
    elementos.append(itens)

    _add_gap()
    elementos.append(Paragraph("<b>Calculo do ISSQN</b>", st_small_b))
    _add_gap()
    issqn = Table(
        [
            [
                Paragraph("Inscricao municipal<br/><b>-</b>", st_tiny),
                Paragraph("Valor total dos servicos<br/><b>0,00</b>", st_tiny),
                Paragraph("Base de calculo do ISSQN<br/><b>0,00</b>", st_tiny),
                Paragraph("Valor do ISSQN<br/><b>0,00</b>", st_tiny),
            ],
        ],
        colWidths=[48 * mm, 50 * mm, 50 * mm, 48 * mm],
        rowHeights=[5.5 * mm],
    )
    issqn.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elementos.append(issqn)

    _add_gap()
    elementos.append(Paragraph("<b>Dados adicionais</b>                              <b>Reservado ao fisco</b>", st_small_b))
    _add_gap()
    obs = Table(
        [[Paragraph("NF-E EMITIDA EM AMBIENTE DE HOMOLOGACAO - SEM VALOR FISCAL", st_tiny), Paragraph("", st_tiny)]],
        colWidths=[98 * mm, 98 * mm],
        rowHeights=[13 * mm],
    )
    obs.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elementos.append(obs)
    elementos.append(Spacer(1, 1.2))
    elementos.append(Paragraph(venda.created_at.strftime("%d/%m/%Y %H:%M:%S"), st_small_b))

    doc.build(elementos)
    return buff.getvalue()


def _venda_para_out(v: Venda) -> VendaOut:
    nome_cond = v.condicao_pag_catalogo.nome if v.condicao_pag_catalogo else None
    return VendaOut(
        id=v.id,
        numero=v.numero,
        cliente_id=v.cliente_id,
        vendedor_id=v.vendedor_id,
        observacao=v.observacao,
        valor_frete=v.valor_frete or Decimal("0"),
        prazo_pagamento=v.prazo_pagamento,
        condicao_pagamento_id=v.condicao_pagamento_id,
        condicao_pagamento_nome=nome_cond,
        total_bruto=v.total_bruto,
        total_desconto=v.total_desconto,
        total_liquido=v.total_liquido,
        financeiro_gerado=bool(v.financeiro_gerado),
        nfse_gerada=bool(v.nfse_gerada),
        nfe_gerada=bool(v.nfe_gerada),
        created_at=v.created_at,
        itens=[VendaItemOut.model_validate(i) for i in v.itens],
    )


def _gerar_numero_venda(db: Session) -> str:
    maior = 0
    for (numero,) in db.query(Venda.numero).all():
        if isinstance(numero, str) and numero.isdigit():
            maior = max(maior, int(numero))
    if maior < NUMERO_INICIAL_PEDIDO:
        return str(NUMERO_INICIAL_PEDIDO)
    return str(maior + PASSO_NUMERO_PEDIDO)


def _validar_cliente_vendedor_frete_condicao(
    db: Session,
    *,
    cliente_id: int | None,
    vendedor_id: int | None,
    valor_frete: Decimal,
    condicao_pagamento_id: int | None,
) -> None:
    if cliente_id:
        cliente = db.get(CadastroGeral, cliente_id)
        if not cliente or not cliente.is_cliente:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente nao encontrado.")
    if vendedor_id:
        vendedor = db.get(CadastroGeral, vendedor_id)
        if not vendedor or not vendedor.is_vendedor:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vendedor nao encontrado.")
    if valor_frete < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Valor de frete invalido.")
    if condicao_pagamento_id is not None:
        cond = db.get(CondicaoPagamento, condicao_pagamento_id)
        if not cond:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Condicao de pagamento nao encontrada.")


def _montar_itens_e_totais(db: Session, venda: Venda, itens_payload: list) -> tuple[Decimal, Decimal]:
    total_bruto = Decimal("0")
    total_desc = Decimal("0")
    for item in itens_payload:
        produto = db.get(Produto, item.produto_id)
        if not produto:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Produto {item.produto_id} nao encontrado.",
            )
        unit = item.valor_unitario if item.valor_unitario is not None else produto.preco_venda
        qtd = Decimal(item.quantidade)
        desconto = Decimal(item.desconto or 0)
        total_item = (qtd * Decimal(unit)) - desconto
        if total_item < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Desconto maior que o total do item.")
        venda_item = VendaItem(
            venda_id=venda.id,
            produto_id=produto.id,
            quantidade=qtd,
            valor_unitario=Decimal(unit),
            desconto=desconto,
            total_item=total_item,
        )
        db.add(venda_item)
        total_bruto += qtd * Decimal(unit)
        total_desc += desconto
    return total_bruto, total_desc


def _categoria_padrao(db: Session, *, tipo: TipoCategoria, nome: str) -> Categoria:
    categoria = db.query(Categoria).filter(Categoria.nome == nome).first()
    if categoria:
        return categoria
    categoria = Categoria(nome=nome, tipo=tipo, descricao="Criada automaticamente.")
    db.add(categoria)
    db.flush()
    return categoria


def _centro_custos_padrao(db: Session) -> CentroCustos:
    centro = db.query(CentroCustos).filter(CentroCustos.codigo == "GERAL").first()
    if centro:
        return centro
    centro = CentroCustos(nome="Geral", codigo="GERAL", descricao="Criado automaticamente.")
    db.add(centro)
    db.flush()
    return centro


def _garantir_cliente(db: Session, cliente_id: int | None) -> Cliente | None:
    if not cliente_id:
        return None
    cliente = db.get(Cliente, cliente_id)
    if cliente:
        return cliente
    cadastro = db.get(CadastroGeral, cliente_id)
    if not cadastro or not cadastro.is_cliente:
        return None
    cliente = Cliente(
        id=cadastro.id,
        nome=cadastro.razao_social,
        cnpj_cpf=cadastro.cnpj,
        telefone=cadastro.telefone,
        endereco=cadastro.endereco,
    )
    db.add(cliente)
    db.flush()
    return cliente


def _parse_prazos_dias(prazo_pagamento: str | None) -> list[int]:
    if not prazo_pagamento:
        return [0]
    encontrados = re.findall(r"\d+", prazo_pagamento)
    dias = [int(v) for v in encontrados if int(v) >= 0]
    if not dias:
        return [0]
    return sorted(set(dias))


def _gerar_financeiro_da_venda(db: Session, venda: Venda) -> None:
    if venda.financeiro_gerado:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Financeiro desta venda ja foi gerado.")
    if not venda.itens:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Venda sem itens para gerar financeiro.")

    categoria_receita = _categoria_padrao(db, tipo=TipoCategoria.RECEITA, nome="Venda de produtos")
    centro = _centro_custos_padrao(db)
    cliente = _garantir_cliente(db, venda.cliente_id)

    prazos = _parse_prazos_dias(venda.prazo_pagamento)
    base_venc = date.today()
    total = Decimal(venda.total_liquido or 0)
    parcelas = len(prazos)
    if parcelas <= 0:
        parcelas = 1
    valor_parcela = (total / Decimal(parcelas)).quantize(Decimal("0.01"))
    acumulado = Decimal("0.00")

    for idx, dias in enumerate(prazos):
        valor = valor_parcela
        if idx == len(prazos) - 1:
            valor = total - acumulado
        acumulado += valor
        conta = ContaReceber(
            descricao=f"Recebimento pedido {venda.numero} ({idx + 1}/{len(prazos)})",
            valor=valor,
            categoria_id=categoria_receita.id,
            centro_custos_id=centro.id,
            cliente_id=cliente.id if cliente else None,
            venda_id=venda.id,
            data_vencimento=base_venc + timedelta(days=dias),
            status=StatusContaReceber.PENDENTE,
            comissao_gerada=False,
        )
        db.add(conta)

    venda.financeiro_gerado = True


@router.get("", response_model=list[VendaOut])
def listar(db: Session = Depends(get_db)) -> list[VendaOut]:
    rows = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .order_by(Venda.id.desc())
        .all()
    )
    return [_venda_para_out(v) for v in rows]


@router.get("/{venda_id}", response_model=VendaOut)
def obter(venda_id: int, db: Session = Depends(get_db)) -> VendaOut:
    v = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    return _venda_para_out(v)


@router.post("", response_model=VendaOut, status_code=status.HTTP_201_CREATED)
def criar(payload: VendaCreate, db: Session = Depends(get_db)) -> VendaOut:
    if not payload.itens:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe ao menos um item.")

    valor_frete = Decimal(payload.valor_frete or 0)
    prazo = (payload.prazo_pagamento or "").strip() or None
    cond_id = payload.condicao_pagamento_id

    _validar_cliente_vendedor_frete_condicao(
        db,
        cliente_id=payload.cliente_id,
        vendedor_id=payload.vendedor_id,
        valor_frete=valor_frete,
        condicao_pagamento_id=cond_id,
    )

    venda = Venda(
        numero=_gerar_numero_venda(db),
        cliente_id=payload.cliente_id,
        vendedor_id=payload.vendedor_id,
        observacao=payload.observacao,
        valor_frete=valor_frete,
        prazo_pagamento=prazo,
        condicao_pagamento_id=cond_id,
        total_bruto=Decimal("0"),
        total_desconto=Decimal("0"),
        total_liquido=Decimal("0"),
        financeiro_gerado=False,
        nfse_gerada=False,
        nfe_gerada=False,
    )
    db.add(venda)

    try:
        db.flush()
        total_bruto, total_desc = _montar_itens_e_totais(db, venda, payload.itens)
        venda.total_bruto = total_bruto
        venda.total_desconto = total_desc
        venda.total_liquido = total_bruto - total_desc + valor_frete
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nao foi possivel salvar a venda por conflito de dados. Tente novamente.",
        )
    v = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda.id)
        .first()
    )
    assert v is not None
    return _venda_para_out(v)


@router.put("/{venda_id}", response_model=VendaOut)
def atualizar(venda_id: int, payload: VendaUpdate, db: Session = Depends(get_db)) -> VendaOut:
    if not payload.itens:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Informe ao menos um item.")

    venda = db.get(Venda, venda_id)
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")

    valor_frete = Decimal(payload.valor_frete or 0)
    prazo = (payload.prazo_pagamento or "").strip() or None
    cond_id = payload.condicao_pagamento_id

    _validar_cliente_vendedor_frete_condicao(
        db,
        cliente_id=payload.cliente_id,
        vendedor_id=payload.vendedor_id,
        valor_frete=valor_frete,
        condicao_pagamento_id=cond_id,
    )

    venda.cliente_id = payload.cliente_id
    venda.vendedor_id = payload.vendedor_id
    venda.observacao = payload.observacao
    venda.valor_frete = valor_frete
    venda.prazo_pagamento = prazo
    venda.condicao_pagamento_id = cond_id

    for vi in list(venda.itens):
        db.delete(vi)
    db.flush()

    total_bruto, total_desc = _montar_itens_e_totais(db, venda, payload.itens)
    venda.total_bruto = total_bruto
    venda.total_desconto = total_desc
    venda.total_liquido = total_bruto - total_desc + valor_frete
    db.commit()

    v = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    assert v is not None
    return _venda_para_out(v)


@router.delete("/{venda_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(venda_id: int, db: Session = Depends(get_db)) -> None:
    venda = db.get(Venda, venda_id)
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    db.delete(venda)
    db.commit()


@router.post("/{venda_id}/gerar-financeiro", response_model=VendaOut)
def gerar_financeiro(venda_id: int, db: Session = Depends(get_db)) -> VendaOut:
    venda = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    try:
        _gerar_financeiro_da_venda(db, venda)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel gerar o financeiro da venda.",
        )
    db.refresh(venda)
    return _venda_para_out(venda)


@router.post("/{venda_id}/estornar-financeiro", response_model=VendaOut)
def estornar_financeiro(venda_id: int, db: Session = Depends(get_db)) -> VendaOut:
    venda = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    if not venda.financeiro_gerado:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Financeiro desta venda ainda nao foi gerado.")

    contas = db.query(ContaReceber).filter(ContaReceber.venda_id == venda.id).all()
    if not contas:
        venda.financeiro_gerado = False
        db.commit()
        db.refresh(venda)
        return _venda_para_out(venda)

    conta_recebida = next((c for c in contas if c.status == StatusContaReceber.RECEBIDO), None)
    if conta_recebida:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nao e possivel estornar: ha parcela ja recebida deste pedido.",
        )

    for conta in contas:
        db.delete(conta)
    venda.financeiro_gerado = False
    db.commit()
    db.refresh(venda)
    return _venda_para_out(venda)


@router.post("/{venda_id}/gerar-nfs-e", response_model=VendaOut)
def gerar_nfse(venda_id: int, db: Session = Depends(get_db)) -> VendaOut:
    venda = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    venda.nfse_gerada = True
    db.commit()
    db.refresh(venda)
    return _venda_para_out(venda)


@router.post("/{venda_id}/gerar-nf-e", response_model=dict[str, Any])
def gerar_nfe(venda_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    venda = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    base_dir = Path(__file__).resolve().parents[1]
    try:
        geracao = gerar_nfe_xml_assinado(venda, base_dir)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha ao gerar XML NF-e: {exc}",
        ) from exc
    autorizacao = autorizar_nfe_sefaz(
        base_dir=base_dir,
        chave=str(geracao.get("chave") or ""),
        xml_path=str(geracao.get("arquivo_xml_assinado") or ""),
    )
    venda.nfe_gerada = bool(autorizacao.autorizado)
    db.commit()
    db.refresh(venda)
    return {
        "venda": _venda_para_out(venda),
        "nfe": geracao,
        "autorizacao": autorizacao.to_dict(),
    }


@router.get("/{venda_id}/pdf")
def visualizar_pdf(venda_id: int, db: Session = Depends(get_db)) -> Response:
    venda = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    pdf_bytes = _gerar_pdf_venda(db, venda)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="pedido-{venda.numero}.pdf"'},
    )


@router.get("/{venda_id}/nfe/pdf")
def visualizar_pdf_nfe(venda_id: int, chave: str = Query(default=""), db: Session = Depends(get_db)) -> Response:
    venda = (
        db.query(Venda)
        .options(joinedload(Venda.itens), joinedload(Venda.condicao_pag_catalogo))
        .filter(Venda.id == venda_id)
        .first()
    )
    if not venda:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda nao encontrada.")
    if not venda.nfe_gerada:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="NF-e ainda nao foi gerada para este pedido.")
    pdf_bytes = _gerar_pdf_nfe_homologacao(db, venda, chave=chave or None)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="nfe-homologacao-{venda.numero}.pdf"'},
    )
