#!/usr/bin/env python3
"""Deploy CIRURGICO do recebimento parcial com multa/juros corretos (AlmaLinux).

Troca apenas:
- services/encargos_atraso_service.py
- services/pagamento_service.py
- models/conta_receber.py
- schemas/conta_receber.py
- routes/contas_receber.py
- patch pontual em main.py (colunas + UI do modal)
- patch pontual em documentos_email_service.py

Uso no servidor:
  python3 scripts/deploy_recebimento_parcial_cirurgico.py --restart
"""

from __future__ import annotations

import argparse
import hashlib
import re
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
    "services/encargos_atraso_service.py",
    "services/pagamento_service.py",
    "models/conta_receber.py",
    "schemas/conta_receber.py",
    "routes/contas_receber.py",
]


def die(msg: str) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def backup(path: Path, broot: Path) -> None:
    broot.mkdir(parents=True, exist_ok=True)
    rel = path.name
    # preserve folder hint in name
    dest = broot / f"{path.parent.name}__{rel}"
    shutil.copy2(path, dest)
    print(f"  backup: {path} -> {dest}")


def patch_main(main_py: Path) -> None:
    text = main_py.read_text(encoding="utf-8")
    original = text

    # 1) Schema columns
    marker = 'if "comissionar_recebimento" not in colunas:'
    schema_block = '''
        for _col, _ddl in (
            ("valor_original", "NUMERIC(14, 2) NULL"),
            ("multa_fixada", "NUMERIC(14, 2) NULL"),
            ("juros_acumulados", "NUMERIC(14, 2) NULL"),
            ("juros_apos_data", "DATE NULL"),
        ):
            if _col not in colunas:
                conn.execute(text(f"ALTER TABLE contas_receber ADD COLUMN {_col} {_ddl}"))
'''
    if "multa_fixada" not in text:
        if marker not in text:
            die("main.py: marcador comissionar_recebimento nao encontrado")
        text = text.replace(marker, schema_block + "\n        " + marker, 1)

    # 2) UI: labels Total/Parcial mais claros
    old_chk = (
        '          <label class="check-item">\n'
        '            <input type="checkbox" id="baixaReceberParcial" onchange="void toggleBaixaReceberParcial()" />\n'
        '            <span>Recebimento parcial</span>\n'
        '          </label>'
    )
    new_chk = (
        '          <div style="margin:8px 0 4px;font-weight:600;">Tipo de recebimento</div>\n'
        '          <label class="check-item">\n'
        '            <input type="radio" name="baixaTipoRecebimento" id="baixaReceberTotal" value="total" checked onchange="void onChangeTipoRecebimentoBaixa()" />\n'
        '            <span>Recebimento total</span>\n'
        '          </label>\n'
        '          <label class="check-item">\n'
        '            <input type="radio" name="baixaTipoRecebimento" id="baixaReceberParcial" value="parcial" onchange="void onChangeTipoRecebimentoBaixa()" />\n'
        '            <span>Recebimento parcial</span>\n'
        '          </label>\n'
        '          <p class="muted" style="font-size:11px;margin:2px 0 6px;">Parcial abate o principal; multa integral permanece; juros passam a correr sobre o restante.</p>'
    )
    if 'id="baixaReceberTotal"' not in text:
        if old_chk not in text:
            # fallback: checkbox antigo sem formatação exata
            text2 = re.sub(
                r'<input type="checkbox" id="baixaReceberParcial"[^>]*>\s*<span>Recebimento parcial</span>',
                '<input type="radio" name="baixaTipoRecebimento" id="baixaReceberParcial" value="parcial" onchange="void onChangeTipoRecebimentoBaixa()" />\n'
                '            <span>Recebimento parcial</span>',
                text,
                count=1,
            )
            if text2 == text:
                die("main.py: bloco recebimento parcial nao encontrado")
            text = text2
            # insert total radio before parcial label if missing
            if 'id="baixaReceberTotal"' not in text:
                text = text.replace(
                    '<label class="check-item">\n'
                    '            <input type="radio" name="baixaTipoRecebimento" id="baixaReceberParcial"',
                    '<div style="margin:8px 0 4px;font-weight:600;">Tipo de recebimento</div>\n'
                    '          <label class="check-item">\n'
                    '            <input type="radio" name="baixaTipoRecebimento" id="baixaReceberTotal" value="total" checked onchange="void onChangeTipoRecebimentoBaixa()" />\n'
                    '            <span>Recebimento total</span>\n'
                    '          </label>\n'
                    '          <label class="check-item">\n'
                    '            <input type="radio" name="baixaTipoRecebimento" id="baixaReceberParcial"',
                    1,
                )
        else:
            text = text.replace(old_chk, new_chk, 1)

    # 3) JS helpers
    if "function onChangeTipoRecebimentoBaixa" not in text:
        inject = '''
    function onChangeTipoRecebimentoBaixa() {
      const parcial = !!(document.getElementById('baixaReceberParcial') && document.getElementById('baixaReceberParcial').checked);
      const wrap = document.getElementById('baixaValorRecebidoWrap');
      const inp = document.getElementById('baixaValorRecebido');
      if (wrap) wrap.classList.toggle('hidden', !parcial);
      if (parcial && baixaSimulacaoReceber && inp) {
        const prin = Number((baixaSimulacaoReceber.itens && baixaSimulacaoReceber.itens[0] && baixaSimulacaoReceber.itens[0].valor_principal) || baixaSimulacaoReceber.total_principal || 0);
        inp.value = formatMoedaBrCampo(prin > 0 ? prin : Number(baixaSimulacaoReceber.total_devido || 0));
      }
      validarBaixaValorRecebido();
    }

'''
        text = text.replace(
            "function toggleBaixaReceberParcial()",
            inject + "    function toggleBaixaReceberParcial()",
            1,
        )

    # Make toggleBaixaReceberParcial call radio-aware version
    text = text.replace(
        "onchange=\"void toggleBaixaReceberParcial()\"",
        "onchange=\"void onChangeTipoRecebimentoBaixa()\"",
    )

    # Improve hint text in validarBaixaValorRecebido
    old_hint = "hint.textContent = 'Saldo apos este recebimento: ' + moeda(total - vr);"
    new_hint = (
        "const item0 = (baixaSimulacaoReceber.itens && baixaSimulacaoReceber.itens[0]) || {};\n"
        "      const prin = Number(item0.valor_principal || baixaSimulacaoReceber.total_principal || 0);\n"
        "      const multa = Number(item0.multa || 0);\n"
        "      const juros = Number(item0.juros || 0);\n"
        "      const abatePrin = Math.min(vr, prin);\n"
        "      const resto1 = Math.max(0, vr - abatePrin);\n"
        "      const abateJ = Math.min(resto1, juros);\n"
        "      const resto2 = Math.max(0, resto1 - abateJ);\n"
        "      const abateM = Math.min(resto2, multa);\n"
        "      const prinRest = Math.max(0, prin - abatePrin);\n"
        "      const multaRest = Math.max(0, multa - abateM);\n"
        "      const jurosRest = Math.max(0, juros - abateJ);\n"
        "      hint.textContent = 'Apos parcial → principal ' + moeda(prinRest)\n"
        "        + ' + multa integral ' + moeda(multaRest)\n"
        "        + ' + juros ' + moeda(jurosRest)\n"
        "        + ' = ' + moeda(prinRest + multaRest + jurosRest)\n"
        "        + '. Juros futuros sobre o principal restante.';"
    )
    if old_hint in text:
        text = text.replace(old_hint, new_hint, 1)

    # Reset radios on open modal
    text = text.replace(
        "if (parcialEl) parcialEl.checked = false;",
        "const totalEl = document.getElementById('baixaReceberTotal');\n"
        "      if (totalEl) totalEl.checked = true;\n"
        "      if (parcialEl) parcialEl.checked = false;",
    )

    # confirmarBaixa: parcial via radio checked
    # already uses baixaReceberParcial.checked — works for radio too

    # Enhance encargos table with multa fixada note
    needle = "+ '<tr><td style=\"padding:2px 0;\">Multa (' + escapeHtml(pctM) + ')</td><td style=\"text-align:right;padding:2px 0;\">' + moeda(item.multa) + '</td></tr>'"
    if "multa fixada" not in text and needle in text:
        text = text.replace(
            needle,
            "+ '<tr><td style=\"padding:2px 0;\">Multa (' + escapeHtml(pctM) + ')' + (item.multa_fixada ? ' <em>fixada</em>' : '') + '</td><td style=\"text-align:right;padding:2px 0;\">' + moeda(item.multa) + '</td></tr>'",
            1,
        )

    if text == original:
        print("  main.py: sem mudancas (ja aplicado?)")
        return
    main_py.write_text(text, encoding="utf-8")
    print("  main.py: patch aplicado")


def patch_documentos_email(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "calcular_encargos_da_conta_receber" in text and "valor_principal=Decimal(conta.valor" not in text.split("def _linhas_valor_lembrete_conta_receber")[1][:800]:
        print("  documentos_email_service.py: ja ok")
        return
    old = '''    from sga_financeiro.services.encargos_atraso_service import calcular_encargos_atraso_conta_receber

    hoje = hoje or _hoje_fuso_brasil()
    venc = conta.data_vencimento
    if not venc:
        return [f"Valor: R$ {_formatar_valor_brl_lembrete(conta.valor)}"]

    enc = calcular_encargos_atraso_conta_receber(
        valor_principal=Decimal(conta.valor or 0),
        data_vencimento=venc,
        data_recebimento=hoje,
    )'''
    new = '''    from sga_financeiro.services.encargos_atraso_service import calcular_encargos_da_conta_receber

    hoje = hoje or _hoje_fuso_brasil()
    venc = conta.data_vencimento
    if not venc:
        return [f"Valor: R$ {_formatar_valor_brl_lembrete(conta.valor)}"]

    enc = calcular_encargos_da_conta_receber(
        conta,
        data_recebimento=hoje,
    )'''
    if old not in text:
        die("documentos_email_service.py: bloco lembrete nao encontrado")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("  documentos_email_service.py: patch ok")


def deploy_one(root: Path, stamp: str) -> None:
    if not root.is_dir():
        print(f"SKIP {root}")
        return
    broot = root.parent / "restore-points" / f"recebimento-parcial-{stamp}"
    for rel in FILES:
        src = REPO_SGA / rel
        dest = root / rel
        if not src.is_file():
            die(f"fonte ausente: {src}")
        if not dest.is_file():
            die(f"destino ausente: {dest}")
        backup(dest, broot)
        shutil.copy2(src, dest)
        print(f"OK {root.parent.name}/{rel} {md5(dest)}")

    main_py = root / "main.py"
    backup(main_py, broot)
    patch_main(main_py)

    docs = root / "services" / "documentos_email_service.py"
    backup(docs, broot)
    patch_documentos_email(docs)


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
