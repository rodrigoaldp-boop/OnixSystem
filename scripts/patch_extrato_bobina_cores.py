#!/usr/bin/env python3
"""Cores no extrato bobina 80mm: empresa azul, cliente preto, valores +/-."""
from __future__ import annotations

from pathlib import Path

MARKER_START = "    function _fmtMoneyExtrato(v) {"
MARKER_END = "    async function abrirModalBaixaContaFinanceira(contaId = null) {"

# raw string: \\n no Python vira \n no JS; usamos fromCharCode para join seguro
NEW_BLOCK = r"""    function _fmtMoneyExtrato(v) {
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
    function _escHtmlExtrato(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }
    function _moneySpanExtrato(v, force) {
      const n = Number(v || 0);
      let cls = 'v-black';
      if (force === 'blue') cls = 'v-blue';
      else if (force === 'red') cls = 'v-red';
      else if (force === 'black') cls = 'v-black';
      else if (n > 0.0001) cls = 'v-blue';
      else if (n < -0.0001) cls = 'v-red';
      return '<span class="' + cls + '">' + _escHtmlExtrato(_fmtMoneyExtrato(v)) + '</span>';
    }
    function _rowExtrato(label, valueHtml) {
      return '<div class="row"><span class="lab">' + _escHtmlExtrato(label) + '</span><span class="val">' + valueHtml + '</span></div>';
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
        const statusTxt = String(c.status || '--').toUpperCase();
        const atrasada = Number(atual.dias_atraso || 0) > 0 || statusTxt.indexOf('ATRAS') >= 0;
        const saldoAberto = Number(atual.total || 0) > 0.009;
        const situCls = atrasada ? 'v-red' : (saldoAberto ? 'v-red' : 'v-blue');
        const saldoCls = (atrasada || saldoAberto) ? 'v-red' : 'v-blue';
        const jurosCls = Number(atual.juros || 0) > 0.0001 ? 'v-red' : 'v-black';
        const multaCls = Number(atual.multa || 0) > 0.0001 ? 'v-red' : 'v-black';

        let histHtml = '';
        if (!eventos.length) {
          histHtml = '<div class="ev muted">Sem recebimentos ainda.</div>';
        } else {
          eventos.forEach(function(ev, idx) {
            const tipo = String(ev.rotulo || ev.tipo || '').toUpperCase();
            const tipoCls = tipo.indexOf('TOTAL') >= 0 ? 'v-blue' : 'v-black';
            const totalDepois = Number(ev.total_depois || 0);
            histHtml += '<div class="ev">';
            histHtml += '<div class="ev-h"><span>#' + (idx + 1) + ' ' + _escHtmlExtrato(tipo) + '</span><span class="' + tipoCls + '">' + _escHtmlExtrato(_fmtDataExtrato(ev.data_evento)) + '</span></div>';
            histHtml += _rowExtrato('Recebido', _moneySpanExtrato(ev.valor_recebido, 'blue'));
            histHtml += _rowExtrato('Abate princ.', _moneySpanExtrato(ev.abate_principal, 'blue'));
            if (Number(ev.abate_juros || 0) > 0) histHtml += _rowExtrato('Abate juros', _moneySpanExtrato(ev.abate_juros, 'red'));
            if (Number(ev.abate_multa || 0) > 0) histHtml += _rowExtrato('Abate multa', _moneySpanExtrato(ev.abate_multa, 'red'));
            histHtml += _rowExtrato('Princ.', '<span class="v-black">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.principal_antes)) + '</span> <span class="muted">-&gt;</span> <span class="' + (Number(ev.principal_depois||0) > 0.009 ? 'v-red' : 'v-blue') + '">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.principal_depois)) + '</span>');
            histHtml += _rowExtrato('Multa', '<span class="v-black">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.multa_antes)) + '</span> <span class="muted">-&gt;</span> <span class="' + (Number(ev.multa_depois||0) > 0.0001 ? 'v-red' : 'v-black') + '">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.multa_depois)) + '</span>');
            histHtml += _rowExtrato('Juros', '<span class="v-black">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.juros_antes)) + '</span> <span class="muted">-&gt;</span> <span class="' + (Number(ev.juros_depois||0) > 0.0001 ? 'v-red' : 'v-black') + '">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.juros_depois)) + '</span>');
            histHtml += _rowExtrato('TOTAL', '<span class="v-black">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.total_antes)) + '</span> <span class="muted">-&gt;</span> <span class="' + (totalDepois > 0.009 ? 'v-red' : 'v-blue') + '">' + _escHtmlExtrato(_fmtMoneyExtrato(ev.total_depois)) + '</span>');
            histHtml += '</div>';
          });
        }

        const html = [
          '<!doctype html><html><head><meta charset="utf-8"/>',
          '<title>Extrato bobina 80mm #' + id + '</title>',
          '<style>',
          '@page{size:80mm auto;margin:2mm;}',
          'html,body{margin:0;padding:0;background:#fff;}',
          'body{width:72mm;max-width:72mm;margin:0 auto;color:#000;',
          'font-family:"Courier New",Courier,monospace;font-size:11px;line-height:1.25;',
          '-webkit-print-color-adjust:exact;print-color-adjust:exact;}',
          '.ticket{width:72mm;padding:2mm 1.5mm 6mm;box-sizing:border-box;}',
          '.brand{text-align:center;font-weight:900;font-size:13px;color:#0056b3;letter-spacing:0.3px;}',
          '.subtitle{text-align:center;font-weight:800;color:#000;margin:2px 0 4px;}',
          '.cliente{font-weight:900;font-size:12px;color:#000;margin:3px 0 5px;word-break:break-word;}',
          '.line{border-top:1px dashed #000;margin:5px 0;}',
          '.line2{border-top:2px solid #000;margin:5px 0;}',
          '.row{display:flex;justify-content:space-between;gap:4px;margin:1px 0;}',
          '.row .lab{color:#000;}',
          '.row .val{text-align:right;white-space:nowrap;}',
          '.title{font-weight:800;text-align:center;margin:3px 0;color:#000;}',
          '.muted{color:#444;font-size:10px;}',
          '.ev{margin:5px 0;padding-top:3px;border-top:1px dotted #666;}',
          '.ev-h{display:flex;justify-content:space-between;font-weight:800;margin-bottom:2px;color:#000;}',
          '.v-blue{color:#0056b3;font-weight:800;}',
          '.v-red{color:#c62828;font-weight:800;}',
          '.v-black{color:#000;font-weight:700;}',
          '.center{text-align:center;}',
          '.no-print{font-family:Arial,sans-serif;font-size:12px;margin:8px 8px 4px;max-width:320px;}',
          '.no-print button{margin:0 6px 6px 0;padding:6px 10px;}',
          '@media print{.no-print{display:none!important;} body{width:72mm;}}',
          '</style></head><body>',
          '<div class="no-print">',
          '<button type="button" onclick="window.print()">Imprimir</button>',
          '<button type="button" onclick="window.close()">Fechar</button>',
          '<button type="button" id="btnSalvarExtrato">Salvar</button>',
          '</div>',
          '<script>',
          '(function(){',
          'var btn=document.getElementById("btnSalvarExtrato");',
          'if(!btn) return;',
          'btn.onclick=function(){',
          'try{',
          'var ticket=document.querySelector(".ticket");',
          'var styles="";',
          'document.querySelectorAll("style").forEach(function(s){ styles+=s.outerHTML; });',
          'var bodyHtml=ticket?ticket.outerHTML:document.body.innerHTML;',
          "var doc='<!doctype html><html><head><meta charset=\"utf-8\"/><title>Extrato #" + id + "</title>'+styles+'</head><body>'+bodyHtml+'</body></html>';",
          'var blob=new Blob([doc],{type:"text/html;charset=utf-8"});',
          'var url=URL.createObjectURL(blob);',
          'var a=document.createElement("a");',
          'a.href=url; a.download="extrato-divida-' + id + '.html";',
          'document.body.appendChild(a); a.click(); a.remove();',
          'setTimeout(function(){URL.revokeObjectURL(url);},1000);',
          '}catch(e){alert("Nao foi possivel salvar o extrato.");}',
          '};',
          '})();',
          '</script>',
          '<div class="ticket">',
          '<div class="brand">ONIX BRASIL SYSTEM</div>',
          '<div class="subtitle">EXTRATO DA DIVIDA</div>',
          '<div class="center muted">Conta a Receber #' + id + '</div>',
          '<div class="line2"></div>',
          '<div class="muted">Cliente</div>',
          '<div class="cliente">' + _escHtmlExtrato(c.cliente_nome || ('#' + (c.cliente_id || '--'))) + '</div>',
          '<div class="muted">Descricao</div>',
          '<div class="v-black" style="margin-bottom:4px;word-break:break-word;">' + _escHtmlExtrato(c.descricao || '--') + '</div>',
          _rowExtrato('Vencimento', '<span class="' + (atrasada ? 'v-red' : 'v-black') + '">' + _escHtmlExtrato(_fmtDataExtrato(c.data_vencimento)) + '</span>'),
          _rowExtrato('Status', '<span class="' + situCls + '">' + _escHtmlExtrato(statusTxt) + '</span>'),
          _rowExtrato('Princ. original', '<span class="v-black">' + _escHtmlExtrato(_fmtMoneyExtrato(c.valor_original)) + '</span>'),
          _rowExtrato('Ja recebido', _moneySpanExtrato(data.total_recebido, 'blue')),
          _rowExtrato('Gerado em', '<span class="v-black">' + _escHtmlExtrato(String(data.gerado_em || '').slice(0, 16)) + '</span>'),
          '<div class="line2"></div>',
          '<div class="title">HISTORICO</div>',
          histHtml,
          '<div class="line2"></div>',
          '<div class="title">SITUACAO ATUAL</div>',
          _rowExtrato('Ref.', '<span class="v-black">' + _escHtmlExtrato(_fmtDataExtrato(atual.data_referencia)) + '</span>'),
          _rowExtrato('Principal', '<span class="' + (Number(atual.principal||0) > 0.009 ? 'v-red' : 'v-black') + '">' + _escHtmlExtrato(_fmtMoneyExtrato(atual.principal)) + '</span>'),
          _rowExtrato('Multa', '<span class="' + multaCls + '">' + _escHtmlExtrato(_fmtMoneyExtrato(atual.multa)) + '</span>'),
          _rowExtrato('Juros', '<span class="' + jurosCls + '">' + _escHtmlExtrato(_fmtMoneyExtrato(atual.juros)) + '</span>'),
          _rowExtrato('TOTAL DEVIDO', '<span class="' + saldoCls + '">' + _escHtmlExtrato(_fmtMoneyExtrato(atual.total)) + '</span>'),
          (atual.dias_atraso ? _rowExtrato('Dias atraso', '<span class="v-red">' + _escHtmlExtrato(String(atual.dias_atraso)) + '</span>') : ''),
          '<div class="line"></div>',
          '<div class="muted center">Parcial: abate principal.</div>',
          '<div class="muted center">Multa integral permanece.</div>',
          '<div class="muted center">Juros novos no restante.</div>',
          '<div class="line2"></div>',
          '<div class="center v-black">Obrigado</div>',
          '</div></body></html>'
        ].join(String.fromCharCode(10));

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


"""

TARGETS = [
    Path("/opt/onixsystem-prod/sga_financeiro/main.py"),
    Path("/opt/onixsystem-homolog/sga_financeiro/main.py"),
]


def patch_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    i0 = text.find(MARKER_START)
    if i0 < 0:
        raise RuntimeError(f"MARKER_START nao encontrado em {path}")
    i1 = text.find(MARKER_END, i0)
    if i1 < 0:
        raise RuntimeError(f"MARKER_END nao encontrado em {path}")
    path.write_text(text[:i0] + NEW_BLOCK + text[i1:], encoding="utf-8")
    print(f"OK cores bobina: {path}")


def main() -> None:
    for path in TARGETS:
        patch_file(path)


if __name__ == "__main__":
    main()
