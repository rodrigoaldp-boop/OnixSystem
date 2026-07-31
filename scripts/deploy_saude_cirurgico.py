#!/usr/bin/env python3
"""Deploy CIRURGICO da Saude do sistema no Onix completo (AlmaLinux).

REGRAS:
- NUNCA copia main.py / sistema.py inteiros do GitHub enxuto sobre producao.
- So adiciona health_dashboard_service.py e aplica patches pontuais.
- Faz backup timestampado antes de qualquer escrita.
- Nao toca botbot_whatsapp_config, lembrete, SMTP, mobile, etc.

Uso (no servidor AlmaLinux, como root):
  python3 scripts/deploy_saude_cirurgico.py
  python3 scripts/deploy_saude_cirurgico.py --restart
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOTS = [
    Path("/opt/onixsystem-prod/sga_financeiro"),
    Path("/opt/onixsystem-homolog/sga_financeiro"),
    Path("/root/home/projetos/OnixSystem/sga_financeiro"),
]

# Origem = pasta deste repositorio (workspace) onde esta o service novo
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_SGA = SCRIPT_DIR.parent / "sga_financeiro"
SERVICE_SRC = REPO_SGA / "services" / "health_dashboard_service.py"


def die(msg: str) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def backup(path: Path, backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    dest = backup_root / path.name
    shutil.copy2(path, dest)
    print(f"  backup: {path} -> {dest}")
    return dest


def ensure_import_sistema(text: str) -> str:
    needle = "from sga_financeiro.services.health_dashboard_service import"
    if needle in text:
        return text
    # inserir apos imports de services existentes, ou apos database import
    marker = "from sga_financeiro.database import"
    idx = text.find(marker)
    if idx < 0:
        die("sistema.py: nao achei import database para inserir health service")
    # fim da linha do import
    end = text.find("\n", idx)
    insert = (
        "\nfrom sga_financeiro.services.health_dashboard_service import ("
        "\n    coletar_health_dashboard as coletar_health_dashboard_v2,"
        "\n    limpar_cache_health,"
        "\n)"
    )
    return text[:end] + insert + text[end:]


def patch_models_sistema(text: str) -> str:
    """Estende HealthDashboardItemOut se ainda nao tiver grupo/metricas."""
    if "class HealthDashboardItemOut" not in text:
        die("sistema.py: HealthDashboardItemOut nao encontrado (saude antiga ausente?)")
    if "grupo:" in text and "metricas:" in text and "resumo_geral" in text:
        return text  # ja estendido

    # Substitui a classe Item + Out antigas por versao estendida, mantendo nomes.
    old_item = re.search(
        r"class HealthDashboardItemOut\(BaseModel\):.*?(?=\nclass HealthDashboardOut)",
        text,
        flags=re.S,
    )
    old_out = re.search(
        r"class HealthDashboardOut\(BaseModel\):.*?(?=\n\ndef _health_item|\n\ndef coletar_health|\n\ndef _checar_|\n@router\.get\(\"/health-dashboard)",
        text,
        flags=re.S,
    )
    if not old_item or not old_out:
        # fallback: so garante campos via anotacao solta — se regex falhar, nao quebra
        print("  aviso: nao consegui reescrever models; mantendo models atuais")
        return text

    new_models = '''class HealthDashboardItemOut(BaseModel):
    id: str
    nome: str
    status: str
    resumo: str
    detalhe: str = ""
    grupo: str = "aplicacao"
    metricas: dict = {}
    coletado_em: str = ""
    erro: str = ""


class HealthDashboardResumoOut(BaseModel):
    normais: int = 0
    alertas: int = 0
    erros: int = 0
    indisponiveis: int = 0
    mensagem: str = ""


class HealthDashboardManutencaoOut(BaseModel):
    habilitada: bool = False
    mensagem: str = "Recursos de manutencao estarao disponiveis apos configuracao e validacao individual."


class HealthDashboardOut(BaseModel):
    ok: bool
    checked_at: str
    alertas: int
    itens: list[HealthDashboardItemOut]
    resumo_geral: HealthDashboardResumoOut = HealthDashboardResumoOut()
    manutencao: HealthDashboardManutencaoOut = HealthDashboardManutencaoOut()


'''
    text = text[: old_item.start()] + new_models + text[old_out.end() :]
    return text


def patch_endpoint_sistema(text: str) -> str:
    """Troca o body do endpoint para usar o service v2, sem apagar _checar_* antigos."""
    if "coletar_health_dashboard_v2" in text and "limpar_cache_health" in text and "refresh" in text:
        # pode ja estar patched
        if "Depends(_exigir_admin_health)" in text or "_exigir_admin_health" in text:
            return text

    # Garantir helper admin (padrao historico_edicoes)
    if "_exigir_admin_health" not in text:
        helper = '''
def _exigir_admin_health(request: Request) -> int:
    uid = getattr(getattr(request, "state", None), "auth_user_id", None)
    if uid is None:
        raw = request.headers.get("X-Onix-Usuario-Id") or request.headers.get("x-onix-usuario-id")
        if raw and str(raw).strip().isdigit():
            uid = int(str(raw).strip())
    if not uid:
        raise HTTPException(status_code=401, detail="Nao autenticado.")
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT perfil FROM usuarios_sistema WHERE id = :id AND ativo = TRUE LIMIT 1"),
            {"id": int(uid)},
        ).mappings().first()
    if not row or str(row.get("perfil") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail="Somente administradores podem acessar o diagnostico.")
    return int(uid)


'''
        # inserir antes do endpoint health-dashboard
        m = re.search(r"@router\.get\(\"/health-dashboard\"", text)
        if not m:
            die("sistema.py: endpoint /health-dashboard nao encontrado")
        text = text[: m.start()] + helper + text[m.start() :]

    # Garantir imports Request/Query se faltarem
    if "from fastapi import" in text and "Request" not in text.split("from fastapi import", 1)[1].split("\n", 1)[0]:
        text = text.replace("from fastapi import ", "from fastapi import Request, Query, ", 1)

    # Reescreve funcao health_dashboard
    m = re.search(
        r"@router\.get\(\"/health-dashboard\".*?\)\ndef health_dashboard\([\s\S]*?return coletar_health_dashboard\(db\)\n",
        text,
    )
    if not m:
        # tentativa alternativa com corpo maior
        m = re.search(
            r"@router\.get\(\"/health-dashboard\"[\s\S]*?def health_dashboard\([\s\S]*?\n(?=@router\.|def |\Z)",
            text,
        )
    if not m:
        die("sistema.py: nao achei corpo do endpoint health_dashboard para patch")

    new_ep = '''@router.get("/health-dashboard", response_model=HealthDashboardOut)
def health_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    refresh: bool = Query(False),
    _admin_id: int = Depends(_exigir_admin_health),
) -> HealthDashboardOut:
    """Diagnostico interno somente-leitura (v2). Nao altera BotBot/SMTP/backup."""
    if refresh:
        limpar_cache_health()
    raw = coletar_health_dashboard_v2(db, refresh=refresh)
    return HealthDashboardOut(**raw)

'''
    text = text[: m.start()] + new_ep + text[m.end() :]
    return text


def patch_main_css(text: str) -> str:
    if "health-dash-item--risco" in text and "health-dash-group-title" in text:
        return text
    css = '''
    #modalHealthDashboard .health-dash-group-title {
      grid-column: 1 / -1; font-size: 12px; font-weight: 800; color: #334155;
      margin: 12px 0 0; padding-top: 6px; border-top: 1px solid #e2e8f0;
    }
    #modalHealthDashboard .health-dash-group-title:first-child { border-top: none; margin-top: 0; padding-top: 0; }
    #modalHealthDashboard .health-dash-item--risco { border-left: 4px solid #ea580c; background: #fff7ed; }
    #modalHealthDashboard .health-dash-bar {
      margin-top: 8px; height: 8px; background: #e2e8f0; border-radius: 999px; overflow: hidden;
    }
    #modalHealthDashboard .health-dash-bar > span { display: block; height: 100%; background: #16a34a; border-radius: 999px; }
    #modalHealthDashboard .health-dash-bar.is-aviso > span { background: #d97706; }
    #modalHealthDashboard .health-dash-bar.is-risco > span { background: #ea580c; }
    #modalHealthDashboard .health-dash-bar.is-erro > span { background: #dc2626; }
    #modalHealthDashboard .health-dash-bar-label { font-size: 10px; color: #64748b; margin-top: 4px; }
    #modalHealthDashboard .health-dash-manutencao {
      margin-top: 12px; padding: 10px 12px; border: 1px dashed #cbd5e1; border-radius: 8px;
      background: #f8fafc; color: #64748b; font-size: 12px; line-height: 1.45;
    }
    #modalHealthDashboard .health-dash-body { overflow: auto; max-height: min(70vh, 720px); }
'''
    anchor = "#modalHealthDashboard .health-dash-item--info"
    idx = text.find(anchor)
    if idx < 0:
        print("  aviso: CSS health info nao encontrado; inserindo no fim do bloco health")
        anchor2 = "#modalHealthDashboard .health-dash-summary--warn"
        idx2 = text.find(anchor2)
        if idx2 < 0:
            return text
        end = text.find("\n", idx2)
        return text[:end] + "\n" + css + text[end:]
    # inserir apos a linha do --info
    end = text.find("\n", idx)
    return text[:end] + "\n" + css + text[end:]


def patch_main_modal(text: str) -> str:
    if 'id="healthDashManutencao"' in text:
        return text
    # botao Atualizar com refresh
    text = text.replace(
        'onclick="void carregarHealthDashboard()"',
        'onclick="void carregarHealthDashboard(true)"',
    )
    # inserir bloco manutencao antes do status do modal
    needle = '<div id="statusModalHealthDashboard"'
    if needle not in text:
        print("  aviso: statusModalHealthDashboard nao encontrado")
        return text
    bloco = '''      <div class="health-dash-manutencao" id="healthDashManutencao">
        <strong>Manutencao assistida</strong>
        <div>Recursos de manutencao estarao disponiveis apos configuracao e validacao individual.</div>
        <button type="button" disabled>Executar manutencao (em breve)</button>
      </div>
      '''
    return text.replace(needle, bloco + needle, 1)


def patch_main_js(text: str) -> str:
    if "healthDashGrupoTitulo" in text and "barra_pct" in text and "resumo_geral" in text:
        return text

    # Substitui renderHealthDashboard + carregarHealthDashboard por versao agrupada
    m_render = re.search(r"function renderHealthDashboard\(data\) \{[\s\S]*?\n    \}\n\n    function atualizarBadgeHealthDashboard", text)
    if not m_render:
        m_render = re.search(r"function renderHealthDashboard\(data\) \{[\s\S]*?\n    \}\n\n    async function carregarHealthDashboard", text)
    if not m_render:
        print("  aviso: renderHealthDashboard nao encontrado para patch JS")
        return text

    new_js = r'''function healthDashGrupoTitulo(grupo) {
      var g = String(grupo || '').toLowerCase();
      if (g === 'visao') return 'Visao geral';
      if (g === 'recursos') return 'Recursos do servidor';
      if (g === 'aplicacao') return 'Aplicacao e integracoes';
      if (g === 'rede') return 'Rede e servicos';
      if (g === 'armazenamento') return 'Armazenamento e backups';
      if (g === 'seguranca') return 'Seguranca e certificados';
      return 'Outros';
    }

    function renderHealthDashboard(data) {
      var resumo = document.getElementById('healthDashResumo');
      var grid = document.getElementById('healthDashGrid');
      var man = document.getElementById('healthDashManutencao');
      if (!resumo || !grid) return;
      var rg = (data && data.resumo_geral) || {};
      var erros = Number(rg.erros) || 0;
      var avisos = Number(rg.alertas) || 0;
      var normais = Number(rg.normais) || 0;
      var indisponiveis = Number(rg.indisponiveis) || 0;
      var quando = '';
      if (data && data.checked_at) {
        try { quando = ' · ' + new Date(data.checked_at).toLocaleString('pt-BR'); } catch (eWhen) { quando = ''; }
      }
      if (erros > 0) {
        resumo.className = 'health-dash-summary health-dash-summary--warn';
        resumo.textContent = 'Criticos: ' + erros + ' · alertas: ' + avisos + ' · ok: ' + normais + ' · indisponiveis: ' + indisponiveis + quando;
      } else if (avisos > 0 || !(data && data.ok)) {
        resumo.className = 'health-dash-summary health-dash-summary--warn';
        resumo.textContent = 'Atencao: ' + avisos + ' alerta(s) · ok: ' + normais + ' · indisponiveis: ' + indisponiveis + quando;
      } else {
        resumo.className = 'health-dash-summary health-dash-summary--ok';
        resumo.textContent = 'Todos normais (' + normais + ' verificacoes)' + quando;
      }
      if (man && data && data.manutencao && data.manutencao.mensagem) {
        man.querySelector('div') && (man.querySelector('div').textContent = String(data.manutencao.mensagem));
      }
      grid.innerHTML = '';
      var ordemGrupos = ['visao', 'recursos', 'aplicacao', 'rede', 'armazenamento', 'seguranca'];
      var itens = Array.isArray(data && data.itens) ? data.itens.slice() : [];
      var porGrupo = {};
      itens.forEach(function(item) {
        var g = String(item.grupo || 'aplicacao').toLowerCase();
        if (!porGrupo[g]) porGrupo[g] = [];
        porGrupo[g].push(item);
      });
      ordemGrupos.forEach(function(g) {
        var lista = porGrupo[g] || [];
        if (!lista.length) return;
        var titG = document.createElement('div');
        titG.className = 'health-dash-group-title';
        titG.textContent = healthDashGrupoTitulo(g);
        grid.appendChild(titG);
        lista.forEach(function(item) {
          var st = String(item.status || 'info').toLowerCase();
          if (['ok','aviso','risco','erro','info'].indexOf(st) < 0) st = 'info';
          var box = document.createElement('div');
          box.className = 'health-dash-item health-dash-item--' + (st === 'risco' ? 'risco' : (st === 'ok' || st === 'aviso' || st === 'erro' ? st : 'info'));
          var tit = document.createElement('div');
          tit.className = 'health-dash-item-title';
          tit.textContent = String(item.nome || item.id || 'Item');
          var sum = document.createElement('div');
          sum.className = 'health-dash-item-resumo';
          sum.textContent = healthDashStatusLabel(st) + ' — ' + String(item.resumo || '');
          box.appendChild(tit); box.appendChild(sum);
          if (item.detalhe) {
            var det = document.createElement('div');
            det.className = 'health-dash-item-detalhe';
            det.textContent = String(item.detalhe || '');
            box.appendChild(det);
          }
          var met = item.metricas || {};
          if (met && met.barra_pct != null && isFinite(Number(met.barra_pct))) {
            var pct = Math.max(0, Math.min(100, Number(met.barra_pct)));
            var barWrap = document.createElement('div');
            barWrap.className = 'health-dash-bar' + (st === 'aviso' || st === 'risco' || st === 'erro' ? (' is-' + st) : '');
            var fill = document.createElement('span');
            fill.style.width = pct + '%';
            barWrap.appendChild(fill);
            box.appendChild(barWrap);
            var lab = document.createElement('div');
            lab.className = 'health-dash-bar-label';
            lab.textContent = String(met.barra_label || 'Uso') + ': ' + pct + '%';
            box.appendChild(lab);
          }
          grid.appendChild(box);
        });
      });
      if (typeof atualizarBadgeHealthDashboard === 'function') atualizarBadgeHealthDashboard(data);
    }

    function atualizarBadgeHealthDashboard'''

    # Se o match inclui atualizarBadge, usamos a versao com esse fim
    if "function atualizarBadgeHealthDashboard" in m_render.group(0) or m_render.group(0).endswith("atualizarBadgeHealthDashboard"):
        text = text[: m_render.start()] + new_js + text[m_render.end() :]
    else:
        # match ate carregarHealthDashboard
        text = text[: m_render.start()] + new_js.replace(
            "function atualizarBadgeHealthDashboard",
            "function __healthDashKeepBadge\n\n    function atualizarBadgeHealthDashboard",
        )
        # simpler: just replace render function body only
        pass

    # Patch carregarHealthDashboard para ?refresh=
    text2 = re.sub(
        r"async function carregarHealthDashboard\(\) \{[\s\S]*?\n    \}\n\n    async function abrirModalHealthDashboard",
        '''async function carregarHealthDashboard(forceRefresh) {
      var resumo = document.getElementById('healthDashResumo');
      var grid = document.getElementById('healthDashGrid');
      if (resumo) { resumo.className = 'health-dash-summary'; resumo.textContent = 'Carregando diagnostico...'; }
      if (grid) grid.innerHTML = '';
      setMsg('statusModalHealthDashboard', '');
      try {
        var q = forceRefresh ? '?refresh=1' : '';
        var headers = {};
        try {
          if (typeof usuarioSessaoAtivaId !== 'undefined' && usuarioSessaoAtivaId) headers['X-Onix-Usuario-Id'] = String(usuarioSessaoAtivaId);
          if (window.onixUsuarioAuth && window.onixUsuarioAuth.id) headers['X-Onix-Usuario-Id'] = String(window.onixUsuarioAuth.id);
        } catch (eHdr) {}
        var data = await api('/sistema/health-dashboard' + q, { headers: headers });
        renderHealthDashboard(data);
      } catch (err) {
        if (resumo) { resumo.className = 'health-dash-summary health-dash-summary--warn'; resumo.textContent = 'Falha ao carregar diagnostico.'; }
        setMsg('statusModalHealthDashboard', err.message, false);
      }
    }

    async function abrirModalHealthDashboard''',
        text,
        count=1,
    )
    return text2


def patch_health_status_label(text: str) -> str:
    if "s === 'risco'" in text:
        return text
    old = """function healthDashStatusLabel(st) {
      var s = String(st || '').toLowerCase();
      if (s === 'ok') return 'OK';
      if (s === 'aviso') return 'Atencao';
      if (s === 'erro') return 'Problema';
      return 'Info';
    }"""
    new = """function healthDashStatusLabel(st) {
      var s = String(st || '').toLowerCase();
      if (s === 'ok') return 'OK';
      if (s === 'aviso') return 'Atencao';
      if (s === 'risco') return 'Risco';
      if (s === 'erro') return 'Problema';
      return 'Info';
    }"""
    if old in text:
        return text.replace(old, new, 1)
    return text


def deploy_one(sga: Path, backup_root: Path) -> None:
    print(f"\n=== Deploy em {sga} ===")
    if not sga.is_dir():
        print("  pulando (nao existe)")
        return

    # Protecao: se for clone enxuto sem BotBot, NAO e producao completa — ainda pode receber service
    botbot = sga / "botbot_whatsapp_config.py"
    if not botbot.is_file():
        print("  AVISO: botbot_whatsapp_config.py ausente neste tree (ok se for so workspace).")
    else:
        print("  BotBot encontrado — sera preservado (nao sobrescrito).")

    sistema = sga / "routes" / "sistema.py"
    main_py = sga / "main.py"
    services = sga / "services"
    if not sistema.is_file() or not main_py.is_file():
        die(f"Arquivos obrigatorios ausentes em {sga}")

    backup(sistema, backup_root / sga.parent.name)
    backup(main_py, backup_root / sga.parent.name)

    # 1) copiar SO o service novo
    services.mkdir(exist_ok=True)
    dest_svc = services / "health_dashboard_service.py"
    if dest_svc.exists():
        backup(dest_svc, backup_root / sga.parent.name)
    shutil.copy2(SERVICE_SRC, dest_svc)
    print(f"  + {dest_svc}")

    # 2) patch sistema.py
    raw = sistema.read_text(encoding="utf-8")
    if '"/health-dashboard"' not in raw and "/health-dashboard" not in raw:
        die("Este sistema.py nao tem Saude do sistema base — abortando para nao inventar rota do zero sem UI.")
    raw = ensure_import_sistema(raw)
    raw = patch_models_sistema(raw)
    raw = patch_endpoint_sistema(raw)
    sistema.write_text(raw, encoding="utf-8")
    print("  patched routes/sistema.py (endpoint v2; funcoes antigas _checar_* preservadas)")

    # 3) patch main.py (UI apenas)
    html = main_py.read_text(encoding="utf-8")
    if "modalHealthDashboard" not in html:
        die("main.py sem modalHealthDashboard — abortando")
    html = patch_main_css(html)
    html = patch_main_modal(html)
    html = patch_health_status_label(html)
    html = patch_main_js(html)
    main_py.write_text(html, encoding="utf-8")
    print("  patched main.py (CSS/JS/modal only)")

    # sanity: BotBot file still present and untouched content hash if existed
    if botbot.is_file():
        print("  OK BotBot intacto:", botbot)


def maybe_restart() -> None:
    for unit in ("onix-prod.service", "onix-homolog.service"):
        r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"  skip restart {unit}: {r.stdout.strip() or r.stderr.strip()}")
            continue
        print(f"  restart {unit} ...")
        subprocess.run(["systemctl", "restart", unit], check=False)
        subprocess.run(["systemctl", "is-active", unit], check=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restart", action="store_true", help="Reinicia onix-prod/homolog apos patch")
    ap.add_argument("--only", action="append", default=[], help="Filtra path substring (ex: onixsystem-prod)")
    args = ap.parse_args()

    if not SERVICE_SRC.is_file():
        die(f"Fonte nao encontrada: {SERVICE_SRC}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = Path(f"/root/onix-backups/saude-cirurgico-{stamp}")
    # se /root/onix-backups for symlink para HD, aproveita
    if Path("/mnt/hd_A/onix/backups").is_dir():
        backup_root = Path(f"/mnt/hd_A/onix/backups/saude-cirurgico-{stamp}")
    print("Backup em:", backup_root)

    targets = []
    for root in ROOTS:
        if args.only and not any(o in str(root) for o in args.only):
            continue
        if root.is_dir():
            targets.append(root)
    if not targets:
        die(
            "Nenhum path de producao encontrado.\n"
            "Este script PRECISA rodar no AlmaLinux (onde existem /opt/onixsystem-prod).\n"
            "Nao rode um rsync do clone GitHub enxuto sobre /opt."
        )

    for t in targets:
        deploy_one(t, backup_root)

    if args.restart:
        maybe_restart()
    else:
        print("\nSem --restart. Para aplicar: systemctl restart onix-prod.service onix-homolog.service")
    print("\nCONCLUIDO. Abra Configuracoes > Saude do sistema (admin) e clique Atualizar.")


if __name__ == "__main__":
    main()
