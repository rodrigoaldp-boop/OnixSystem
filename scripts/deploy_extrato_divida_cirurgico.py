#!/usr/bin/env python3
"""Deploy CIRURGICO do extrato/relatorio de divida (recebimento parcial/total).

Arquivos:
- services/conta_receber_extrato_service.py (novo)
- services/pagamento_service.py
- routes/contas_receber.py
- patch main.py (botao + impressao)

Uso:
  python3 scripts/deploy_extrato_divida_cirurgico.py --restart
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOTS = [
    Path("/opt/onixsystem-prod/sga_financeiro"),
    Path("/opt/onixsystem-homolog/sga_financeiro"),
]
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_SGA = SCRIPT_DIR.parent / "sga_financeiro"

FILES = [
    "services/conta_receber_extrato_service.py",
    "services/pagamento_service.py",
    "services/encargos_atraso_service.py",
    "routes/contas_receber.py",
]


def die(msg: str) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def backup(path: Path, broot: Path) -> None:
    broot.mkdir(parents=True, exist_ok=True)
    dest = broot / f"{path.parent.name}__{path.name}"
    if path.exists():
        shutil.copy2(path, dest)
        print(f"  backup: {path} -> {dest}")


PRINT_JS = r'''
    function _fmtMoneyExtrato(v) {
      try { return moeda(Number(v || 0)); } catch (e) {
        return 'R$ ' + Number(v || 0).toFixed(2).replace('.', ',');
      }
    }
    function _fmtDataExtrato(iso) {
      if (!iso) return '—';
      try { return formatDataBr(String(iso).slice(0, 10)); } catch (e2) {
        const p = String(iso).slice(0, 10).split('-');
        if (p.length === 3) return p[2] + '/' + p[1] + '/' + p[0];
        return String(iso);
      }
    }
    async function imprimirExtratoDividaContaReceber(contaId) {
      const id = Number(contaId);
      if (!id) return;
      try {
        setMsg('statusFinanceiro', 'Montando extrato da divida...', true);
        const data = await api('/contas-receber/' + encodeURIComponent(String(id)) + '/extrato-divida');
        const c = data.conta || {};
        const atual = data.situacao_atual || {};
        const eventos = Array.isArray(data.eventos) ? data.eventos : [];
        let evHtml = '';
        if (!eventos.length) {
          evHtml = '<p class="muted">Nenhum recebimento registrado ainda. Abaixo esta a situacao atual da divida.</p>';
        } else {
          evHtml = eventos.map(function(ev, idx) {
            return (
              '<section class="blk">' +
              '<h3>' + (idx + 1) + '. ' + escapeHtml(ev.rotulo || ev.tipo) + ' — ' + escapeHtml(_fmtDataExtrato(ev.data_evento)) + '</h3>' +
              '<table><tbody>' +
              '<tr><td>Valor recebido</td><td class="r"><strong>' + _fmtMoneyExtrato(ev.valor_recebido) + '</strong></td></tr>' +
              '<tr><td>Abate principal</td><td class="r">' + _fmtMoneyExtrato(ev.abate_principal) + '</td></tr>' +
              '<tr><td>Abate juros</td><td class="r">' + _fmtMoneyExtrato(ev.abate_juros) + '</td></tr>' +
              '<tr><td>Abate multa</td><td class="r">' + _fmtMoneyExtrato(ev.abate_multa) + '</td></tr>' +
              '<tr><td>Principal</td><td class="r">' + _fmtMoneyExtrato(ev.principal_antes) + ' → ' + _fmtMoneyExtrato(ev.principal_depois) + '</td></tr>' +
              '<tr><td>Multa</td><td class="r">' + _fmtMoneyExtrato(ev.multa_antes) + ' → ' + _fmtMoneyExtrato(ev.multa_depois) + '</td></tr>' +
              '<tr><td>Juros</td><td class="r">' + _fmtMoneyExtrato(ev.juros_antes) + ' → ' + _fmtMoneyExtrato(ev.juros_depois) + '</td></tr>' +
              '<tr><td>Total da divida</td><td class="r"><strong>' + _fmtMoneyExtrato(ev.total_antes) + ' → ' + _fmtMoneyExtrato(ev.total_depois) + '</strong></td></tr>' +
              (ev.observacao ? ('<tr><td colspan="2" class="obs">' + escapeHtml(ev.observacao) + '</td></tr>') : '') +
              '</tbody></table></section>'
            );
          }).join('');
        }
        const html = '<!doctype html><html><head><meta charset="utf-8"/>' +
          '<title>Extrato da divida #' + id + '</title>' +
          '<style>' +
          'body{font-family:Arial,Helvetica,sans-serif;color:#111;margin:18px;}' +
          'h1{font-size:18px;margin:0 0 4px;} h2{font-size:14px;margin:16px 0 8px;} h3{font-size:13px;margin:0 0 6px;}' +
          '.meta{font-size:12px;line-height:1.45;margin-bottom:12px;}' +
          'table{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:8px;}' +
          'td{border:1px solid #ccc;padding:5px 7px;} td.r{text-align:right;white-space:nowrap;}' +
          'td.obs{font-size:11px;color:#333;background:#fafafa;}' +
          '.blk{margin:0 0 14px;page-break-inside:avoid;}' +
          '.box{border:1px solid #000;padding:8px 10px;margin:8px 0 14px;}' +
          '.muted{color:#555;} .no-print{margin:10px 0;}' +
          '@media print{.no-print{display:none!important;}}' +
          '</style></head><body>' +
          '<div class="no-print"><button onclick="window.print()">Imprimir / Salvar PDF</button></div>' +
          '<h1>Extrato da divida — Conta a Receber #' + id + '</h1>' +
          '<div class="meta">' +
          '<div><strong>Cliente:</strong> ' + escapeHtml(c.cliente_nome || ('#' + (c.cliente_id || '—'))) + '</div>' +
          '<div><strong>Descricao:</strong> ' + escapeHtml(c.descricao || '—') + '</div>' +
          '<div><strong>Vencimento:</strong> ' + escapeHtml(_fmtDataExtrato(c.data_vencimento)) +
          ' &nbsp;|&nbsp; <strong>Status:</strong> ' + escapeHtml(c.status || '—') + '</div>' +
          '<div><strong>Principal original:</strong> ' + _fmtMoneyExtrato(c.valor_original) +
          ' &nbsp;|&nbsp; <strong>Total ja recebido:</strong> ' + _fmtMoneyExtrato(data.total_recebido) + '</div>' +
          '<div class="muted">Gerado em ' + escapeHtml(data.gerado_em || '') + '</div>' +
          '</div>' +
          '<h2>Historico de recebimentos</h2>' + evHtml +
          '<h2>Situacao atual</h2>' +
          '<div class="box"><table><tbody>' +
          '<tr><td>Referencia</td><td class="r">' + escapeHtml(_fmtDataExtrato(atual.data_referencia)) + '</td></tr>' +
          '<tr><td>Principal em aberto</td><td class="r">' + _fmtMoneyExtrato(atual.principal) + '</td></tr>' +
          '<tr><td>Multa</td><td class="r">' + _fmtMoneyExtrato(atual.multa) + '</td></tr>' +
          '<tr><td>Juros</td><td class="r">' + _fmtMoneyExtrato(atual.juros) + '</td></tr>' +
          '<tr><td><strong>Total devido agora</strong></td><td class="r"><strong>' + _fmtMoneyExtrato(atual.total) + '</strong></td></tr>' +
          (atual.dias_atraso ? ('<tr><td>Dias em atraso</td><td class="r">' + atual.dias_atraso + '</td></tr>') : '') +
          '</tbody></table></div>' +
          '<p class="muted" style="font-size:11px;">Regra: recebimento parcial abate o principal; multa integral permanece; juros ja corridos ficam e, a partir da baixa, correm sobre o restante.</p>' +
          '</body></html>';
        const w = window.open('', '_blank', 'width=900,height=720');
        if (!w) {
          setMsg('statusFinanceiro', 'Pop-up bloqueado. Permita janelas para imprimir o extrato.', false);
          return;
        }
        w.document.open();
        w.document.write(html);
        w.document.close();
        setMsg('statusFinanceiro', 'Extrato da divida #' + id + ' aberto para impressao.', true);
      } catch (err) {
        setMsg('statusFinanceiro', 'Falha no extrato: ' + (err.message || err), false);
      }
    }
'''


def patch_main(main_py: Path) -> None:
    text = main_py.read_text(encoding="utf-8")
    original = text

    # Botao no menu de acoes
    needle = 'html += `<button type="button" class="alt" onclick="selecionarContaFinanceiraUnica(${id});void excluirContaFinanceiraUnica(${id});fecharMenuAcoesFinanceiro();">Excluir</button>`;'
    insert = (
        "if (tipoFinanceiroAtual() === 'receber') {\n"
        "        html += `<button type=\"button\" class=\"alt\" onclick=\"selecionarContaFinanceiraUnica(${id});void imprimirExtratoDividaContaReceber(${id});fecharMenuAcoesFinanceiro();\">Extrato da divida</button>`;\n"
        "      }\n"
        "      " + needle
    )
    if "imprimirExtratoDividaContaReceber" not in text:
        if needle not in text:
            die("main.py: botao Excluir do menu financeiro nao encontrado")
        text = text.replace(needle, insert, 1)

    if "function imprimirExtratoDividaContaReceber" not in text:
        # injeta perto de abrirModalBaixaContaFinanceira
        marker = "async function abrirModalBaixaContaFinanceira(contaId = null) {"
        if marker not in text:
            die("main.py: abrirModalBaixaContaFinanceira nao encontrado")
        text = text.replace(marker, PRINT_JS + "\n    " + marker, 1)

    if text == original:
        print("  main.py: sem mudancas (ja aplicado?)")
        return
    main_py.write_text(text, encoding="utf-8")
    print("  main.py: patch extrato ok")


def deploy_one(root: Path, stamp: str) -> None:
    if not root.is_dir():
        print(f"SKIP {root}")
        return
    broot = root.parent / "restore-points" / f"extrato-divida-{stamp}"
    for rel in FILES:
        src = REPO_SGA / rel
        dest = root / rel
        if not src.is_file():
            die(f"fonte ausente: {src}")
        backup(dest, broot)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        print(f"OK {root.parent.name}/{rel} {md5(dest)}")
    main_py = root / "main.py"
    backup(main_py, broot)
    patch_main(main_py)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for root in ROOTS:
        print(f"== {root}")
        deploy_one(root, stamp)
    if args.restart:
        for unit in ("onix-prod", "onix-homolog"):
            r = subprocess.run(["systemctl", "restart", unit], check=False)
            print(f"restart {unit}: rc={r.returncode}")
    print("deploy concluido")


if __name__ == "__main__":
    main()
