#!/usr/bin/env python3
"""Troca o extrato da divida para layout de bobina termica 80mm (Bematec MP-4200 etc.)."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOTS = [
    Path("/opt/onixsystem-prod/sga_financeiro/main.py"),
    Path("/opt/onixsystem-homolog/sga_financeiro/main.py"),
]

NEW_FN = r'''
    function _fmtMoneyExtrato(v) {
      try { return moeda(Number(v || 0)); } catch (e) {
        return 'R$ ' + Number(v || 0).toFixed(2).replace('.', ',');
      }
    }
    function _fmtDataExtrato(iso) {
      if (!iso) return '--';
      try { return formatDataBr(String(iso).slice(0, 10)); } catch (e2) {
        const p = String(iso).slice(0, 10).split('-');
        if (p.length === 3) return p[2] + '/' + p[1] + '/' + p[0];
        return String(iso);
      }
    }
    function _linhaCupom(esq, dir, largura) {
      const w = largura || 32;
      const a = String(esq == null ? '' : esq);
      const b = String(dir == null ? '' : dir);
      if (!b) return a.length > w ? a.slice(0, w) : a;
      const esp = w - a.length - b.length;
      if (esp >= 1) return a + ' '.repeat(esp) + b;
      const maxA = Math.max(0, w - b.length - 1);
      return a.slice(0, maxA) + ' ' + b;
    }
    async function imprimirExtratoDividaContaReceber(contaId) {
      const id = Number(contaId);
      if (!id) return;
      try {
        setMsg('statusFinanceiro', 'Montando extrato da divida (bobina 80mm)...', true);
        const data = await api('/contas-receber/' + encodeURIComponent(String(id)) + '/extrato-divida');
        const c = data.conta || {};
        const atual = data.situacao_atual || {};
        const eventos = Array.isArray(data.eventos) ? data.eventos : [];
        const L = 32;
        const sep = '-'.repeat(L);
        const sep2 = '='.repeat(L);
        let linhas = [];
        linhas.push('ONIX BRASIL SYSTEM');
        linhas.push('EXTRATO DA DIVIDA');
        linhas.push('Conta a Receber #' + id);
        linhas.push(sep2);
        linhas.push(_linhaCupom('Cliente', '', L));
        linhas.push(String(c.cliente_nome || ('#' + (c.cliente_id || '--'))).slice(0, L));
        linhas.push(_linhaCupom('Descricao', '', L));
        linhas.push(String(c.descricao || '--').slice(0, L));
        linhas.push(_linhaCupom('Vencimento', _fmtDataExtrato(c.data_vencimento), L));
        linhas.push(_linhaCupom('Status', String(c.status || '--').toUpperCase(), L));
        linhas.push(_linhaCupom('Princ. original', _fmtMoneyExtrato(c.valor_original), L));
        linhas.push(_linhaCupom('Ja recebido', _fmtMoneyExtrato(data.total_recebido), L));
        linhas.push(_linhaCupom('Gerado em', String(data.gerado_em || '').slice(0, 16), L));
        linhas.push(sep2);
        linhas.push('HISTORICO');
        if (!eventos.length) {
          linhas.push(sep);
          linhas.push('Sem recebimentos ainda.');
        } else {
          eventos.forEach(function(ev, idx) {
            linhas.push(sep);
            linhas.push((idx + 1) + '. ' + String(ev.rotulo || ev.tipo).toUpperCase());
            linhas.push(_linhaCupom('Data', _fmtDataExtrato(ev.data_evento), L));
            linhas.push(_linhaCupom('Recebido', _fmtMoneyExtrato(ev.valor_recebido), L));
            linhas.push(_linhaCupom('Abate princ.', _fmtMoneyExtrato(ev.abate_principal), L));
            if (Number(ev.abate_juros || 0) > 0) linhas.push(_linhaCupom('Abate juros', _fmtMoneyExtrato(ev.abate_juros), L));
            if (Number(ev.abate_multa || 0) > 0) linhas.push(_linhaCupom('Abate multa', _fmtMoneyExtrato(ev.abate_multa), L));
            linhas.push(_linhaCupom('Princ.', _fmtMoneyExtrato(ev.principal_antes) + '->' + _fmtMoneyExtrato(ev.principal_depois), L));
            linhas.push(_linhaCupom('Multa', _fmtMoneyExtrato(ev.multa_antes) + '->' + _fmtMoneyExtrato(ev.multa_depois), L));
            linhas.push(_linhaCupom('Juros', _fmtMoneyExtrato(ev.juros_antes) + '->' + _fmtMoneyExtrato(ev.juros_depois), L));
            linhas.push(_linhaCupom('TOTAL', _fmtMoneyExtrato(ev.total_antes) + '->' + _fmtMoneyExtrato(ev.total_depois), L));
          });
        }
        linhas.push(sep2);
        linhas.push('SITUACAO ATUAL');
        linhas.push(_linhaCupom('Ref.', _fmtDataExtrato(atual.data_referencia), L));
        linhas.push(_linhaCupom('Principal', _fmtMoneyExtrato(atual.principal), L));
        linhas.push(_linhaCupom('Multa', _fmtMoneyExtrato(atual.multa), L));
        linhas.push(_linhaCupom('Juros', _fmtMoneyExtrato(atual.juros), L));
        linhas.push(_linhaCupom('TOTAL DEVIDO', _fmtMoneyExtrato(atual.total), L));
        if (atual.dias_atraso) linhas.push(_linhaCupom('Dias atraso', String(atual.dias_atraso), L));
        linhas.push(sep);
        linhas.push('Parcial: abate principal.');
        linhas.push('Multa integral permanece.');
        linhas.push('Juros novos no restante.');
        linhas.push(sep2);
        linhas.push('Obrigado');
        linhas.push('');
        const pre = linhas.map(function(x) { return escapeHtml(x); }).join(String.fromCharCode(10));
        const html = '<!doctype html><html><head><meta charset="utf-8"/>' +
          '<title>Extrato bobina 80mm #' + id + '</title>' +
          '<style>' +
          '@page{size:80mm auto;margin:2mm;}' +
          'html,body{margin:0;padding:0;background:#fff;}' +
          'body{width:72mm;max-width:72mm;margin:0 auto;color:#000;' +
          'font-family:"Courier New",Courier,monospace;font-size:11px;line-height:1.25;}' +
          '.ticket{width:72mm;padding:2mm 1.5mm 6mm;box-sizing:border-box;}' +
          'pre{margin:0;white-space:pre-wrap;word-break:break-word;font:inherit;}' +
          '.no-print{font-family:Arial,sans-serif;font-size:12px;margin:8px;max-width:320px;}' +
          '.no-print button{margin:0 6px 6px 0;padding:6px 10px;}' +
          '.hint{color:#444;font-size:11px;line-height:1.35;margin:6px 0 10px;}' +
          '@media print{.no-print{display:none!important;} body{width:72mm;}}' +
          '</style></head><body>' +
          '<div class="no-print">' +
          '<div><strong>Layout bobina 80mm</strong> (Bematec MP-4200 / similares)</div>' +
          '<p class="hint">Na impressao, escolha a impressora termica, papel/tamanho <b>80mm</b> (ou "Receipt"), margens minimas e desmarque cabecalhos/rodapes do navegador.</p>' +
          '<button onclick="window.print()">Imprimir bobina</button>' +
          '<button onclick="window.close()">Fechar</button>' +
          '</div>' +
          '<div class="ticket"><pre>' + pre + '</pre></div>' +
          '</body></html>';
        const w = window.open('', '_blank', 'width=360,height=720');
        if (!w) {
          setMsg('statusFinanceiro', 'Pop-up bloqueado. Permita janelas para imprimir o extrato.', false);
          return;
        }
        w.document.open();
        w.document.write(html);
        w.document.close();
        setMsg('statusFinanceiro', 'Extrato bobina 80mm #' + id + ' aberto.', true);
      } catch (err) {
        setMsg('statusFinanceiro', 'Falha no extrato: ' + (err.message || err), false);
      }
    }
'''


def patch_one(main_py: Path, stamp: str) -> None:
    if not main_py.is_file():
        print(f"SKIP {main_py}")
        return
    text = main_py.read_text(encoding="utf-8")
    # remove bloco antigo desde _fmtMoneyExtrato ate fim de imprimirExtrato...
    pat = re.compile(
        r"\n    function _fmtMoneyExtrato\(v\) \{.*?\n    async function imprimirExtratoDividaContaReceber\(contaId\) \{.*?\n    \}\n",
        re.S,
    )
    if not pat.search(text):
        # tentar so a funcao principal
        pat = re.compile(
            r"\n    async function imprimirExtratoDividaContaReceber\(contaId\) \{.*?\n    \}\n",
            re.S,
        )
        if not pat.search(text):
            print(f"ERRO: funcao nao encontrada em {main_py}", file=sys.stderr)
            sys.exit(1)
        text2 = pat.sub("\n" + NEW_FN + "\n", text, count=1)
    else:
        text2 = pat.sub("\n" + NEW_FN + "\n", text, count=1)

    broot = main_py.parent.parent / "restore-points" / f"extrato-bobina80-{stamp}"
    broot.mkdir(parents=True, exist_ok=True)
    shutil.copy2(main_py, broot / "main.py")
    main_py.write_text(text2, encoding="utf-8")
    print(f"OK {main_py} (bobina 80mm)")


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for p in ROOTS:
        patch_one(p, stamp)
    for unit in ("onix-prod", "onix-homolog"):
        r = subprocess.run(["systemctl", "restart", unit], check=False)
        print(f"restart {unit}: rc={r.returncode}")


if __name__ == "__main__":
    main()
