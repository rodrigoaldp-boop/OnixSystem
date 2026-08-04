#!/usr/bin/env python3
"""Simplifica o painel Saude do sistema (remove visual tipo Grafana)."""
from __future__ import annotations

from pathlib import Path

JS_BEGIN = "    /* HEALTH_DASH_CHARTS_V3_JS_BEGIN */"
JS_END = "    /* HEALTH_DASH_CHARTS_V3_JS_END */"

NEW_JS = r'''    /* HEALTH_DASH_CHARTS_V3_JS_BEGIN */
    function healthDashEsc(text) {
      return String(text == null ? '' : text)
        .split('&').join('&amp;')
        .split('<').join('&lt;')
        .split('>').join('&gt;')
        .split('"').join('&quot;');
    }

    function healthDashFormatBytes(n, digits) {
      var v = Number(n);
      if (!isFinite(v) || v < 0) return '-';
      var u = ['B', 'KB', 'MB', 'GB', 'TB'];
      var i = 0;
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
      var d = digits == null ? 1 : digits;
      return (i === 0 ? String(Math.round(v)) : v.toFixed(d)) + ' ' + u[i];
    }

    function healthDashIdadeTexto(horas) {
      var h = Number(horas);
      if (!isFinite(h) || h < 0) return '';
      if (h < 1) {
        var min = Math.max(1, Math.round(h * 60));
        return 'ha ' + min + ' min';
      }
      if (h < 48) return 'ha ' + (Math.round(h * 10) / 10) + ' h';
      var dias = Math.round((h / 24) * 10) / 10;
      return 'ha ' + dias + ' dia(s)';
    }

    function healthDashBarraHtml(pct, status) {
      var p = Number(pct);
      if (!isFinite(p)) return '';
      p = Math.max(0, Math.min(100, p));
      var cls = 'health-dash-bar';
      var st = String(status || '').toLowerCase();
      if (st === 'aviso') cls += ' is-aviso';
      else if (st === 'risco') cls += ' is-risco';
      else if (st === 'erro') cls += ' is-erro';
      else if (p >= 90) cls += ' is-erro';
      else if (p >= 80) cls += ' is-risco';
      else if (p >= 70) cls += ' is-aviso';
      return '<div class="' + cls + '"><span style="width:' + p.toFixed(1) + '%"></span></div>' +
        '<div class="health-dash-bar-label">Uso: ' + p.toFixed(1) + '%</div>';
    }

    function healthDashItemExtras(it) {
      var id = String(it.id || '');
      var m = it.metricas || {};
      var html = '';
      if (id === 'backup') {
        var idade = healthDashIdadeTexto(m.idade_horas);
        var qtd = m.qtd_backups != null ? m.qtd_backups : m.qtd;
        if (idade) html += '<div class="health-dash-extra">Ultimo backup ' + healthDashEsc(idade) + '</div>';
        if (qtd != null) html += '<div class="health-dash-extra">Arquivos guardados: ' + healthDashEsc(qtd) + (m.espaco_bytes != null ? (' (' + healthDashEsc(healthDashFormatBytes(m.espaco_bytes)) + ')') : '') + '</div>';
        if (m.diretorio) html += '<div class="health-dash-extra">Pasta: ' + healthDashEsc(m.diretorio) + '</div>';
        return html;
      }
      if (id === 'disco' && m.pior_pct != null) {
        html += healthDashBarraHtml(m.pior_pct, it.status);
        return html;
      }
      if ((id === 'cpu' || id === 'memoria') && m.pct != null) {
        html += healthDashBarraHtml(m.pct, it.status);
        return html;
      }
      if (id === 'certificado' && m.dias_restantes != null) {
        html += '<div class="health-dash-extra">Validade: ' + healthDashEsc(Math.round(Number(m.dias_restantes))) + ' dia(s)</div>';
        return html;
      }
      if (id === 'postgres' && m.latencia_ms != null) {
        html += '<div class="health-dash-extra">Resposta: ' + healthDashEsc(m.latencia_ms) + ' ms</div>';
        return html;
      }
      return html;
    }

    function renderHealthDashboard(data) {
      var resumo = document.getElementById('healthDashResumo');
      var grid = document.getElementById('healthDashGrid');
      var man = document.getElementById('healthDashManutencao');
      if (!resumo || !grid) return;
      if (man) man.style.display = 'none';

      var itens = Array.isArray(data && data.itens) ? data.itens.slice() : [];
      // nao mostrar card agregado "Saude geral" — ja vai no resumo
      itens = itens.filter(function(it) { return String(it.id || '') !== 'saude_geral'; });

      var nOk = 0, nAviso = 0, nErro = 0, nInfo = 0;
      itens.forEach(function(it) {
        var st = String(it.status || '').toLowerCase();
        if (st === 'ok') nOk += 1;
        else if (st === 'aviso' || st === 'risco') nAviso += 1;
        else if (st === 'erro') nErro += 1;
        else nInfo += 1;
      });

      var frase = '';
      if (nErro > 0) frase = 'Ha ' + nErro + ' problema(s) para olhar.';
      else if (nAviso > 0) frase = 'Sistema ok, com ' + nAviso + ' aviso(s).';
      else frase = 'Tudo certo por enquanto.';

      resumo.className = 'health-dash-summary' + (nErro ? ' is-erro' : (nAviso ? ' is-aviso' : ' is-ok'));
      resumo.style.display = '';
      resumo.innerHTML =
        '<div class="health-dash-summary-title">' + healthDashEsc(frase) + '</div>' +
        '<div class="health-dash-summary-counts">' +
          '<span class="is-ok">' + nOk + ' ok</span>' +
          '<span class="is-aviso">' + nAviso + ' aviso</span>' +
          '<span class="is-erro">' + nErro + ' problema</span>' +
        '</div>';

      var ordemGrupo = ['visao', 'aplicacao', 'armazenamento', 'recursos', 'rede', 'seguranca'];
      var grupos = {};
      itens.forEach(function(it) {
        var g = String(it.grupo || 'outros').toLowerCase();
        if (!grupos[g]) grupos[g] = [];
        grupos[g].push(it);
      });
      Object.keys(grupos).forEach(function(g) {
        if (ordemGrupo.indexOf(g) < 0) ordemGrupo.push(g);
      });

      var html = '';
      ordemGrupo.forEach(function(g) {
        var lista = grupos[g];
        if (!lista || !lista.length) return;
        html += '<div class="health-dash-group-title">' + healthDashEsc(healthDashGrupoTitulo(g)) + '</div>';
        lista.forEach(function(it) {
          var st = String(it.status || 'info').toLowerCase();
          var cls = 'health-dash-item health-dash-item--' + (st === 'risco' ? 'risco' : (st === 'erro' ? 'erro' : (st === 'aviso' ? 'aviso' : (st === 'ok' ? 'ok' : 'info'))));
          html += '<div class="' + cls + '">';
          html += '<div class="health-dash-item-head">';
          html += '<div class="health-dash-item-title">' + healthDashEsc(it.titulo || it.id || 'Item') + '</div>';
          html += '<span class="health-dash-badge health-dash-badge--' + healthDashEsc(st) + '">' + healthDashEsc(healthDashStatusLabel(st)) + '</span>';
          html += '</div>';
          if (it.resumo) html += '<div class="health-dash-item-resumo">' + healthDashEsc(it.resumo) + '</div>';
          html += healthDashItemExtras(it);
          if (it.detalhe) {
            html += '<details class="health-dash-details"><summary>Detalhes</summary><pre class="health-dash-item-detalhe">' + healthDashEsc(it.detalhe) + '</pre></details>';
          }
          html += '</div>';
        });
      });

      grid.innerHTML = html || '<div class="muted">Nenhum diagnostico disponivel.</div>';

      if (typeof atualizarBadgeHealthDashboard === 'function') {
        try { atualizarBadgeHealthDashboard(data); } catch (eBadge) {}
      }
    }
    /* HEALTH_DASH_CHARTS_V3_JS_END */
'''

CSS_BEGIN = "    /* HEALTH_DASH_CHARTS_V3_BEGIN */"
CSS_END = "    /* HEALTH_DASH_CHARTS_V3_END */"

NEW_CSS = r'''    /* HEALTH_DASH_CHARTS_V3_BEGIN */
    #modalHealthDashboard .health-dash-summary {
      margin: 10px 0 12px;
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid #e2e8f0;
      background: #f8fafc;
    }
    #modalHealthDashboard .health-dash-summary.is-ok { border-color: #bbf7d0; background: #f0fdf4; }
    #modalHealthDashboard .health-dash-summary.is-aviso { border-color: #fde68a; background: #fffbeb; }
    #modalHealthDashboard .health-dash-summary.is-erro { border-color: #fecaca; background: #fef2f2; }
    #modalHealthDashboard .health-dash-summary-title { font-size: 15px; font-weight: 800; color: #0f172a; }
    #modalHealthDashboard .health-dash-summary-counts { display: flex; gap: 12px; margin-top: 6px; font-size: 12px; font-weight: 700; }
    #modalHealthDashboard .health-dash-summary-counts .is-ok { color: #16a34a; }
    #modalHealthDashboard .health-dash-summary-counts .is-aviso { color: #d97706; }
    #modalHealthDashboard .health-dash-summary-counts .is-erro { color: #dc2626; }
    #modalHealthDashboard .health-dash-item-head { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
    #modalHealthDashboard .health-dash-badge {
      flex: 0 0 auto; font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 999px;
      border: 1px solid #cbd5e1; background: #f8fafc; color: #334155;
    }
    #modalHealthDashboard .health-dash-badge--ok { border-color: #86efac; background: #dcfce7; color: #166534; }
    #modalHealthDashboard .health-dash-badge--aviso { border-color: #fcd34d; background: #fef3c7; color: #92400e; }
    #modalHealthDashboard .health-dash-badge--risco { border-color: #fdba74; background: #ffedd5; color: #9a3412; }
    #modalHealthDashboard .health-dash-badge--erro { border-color: #fca5a5; background: #fee2e2; color: #991b1b; }
    #modalHealthDashboard .health-dash-badge--info { border-color: #93c5fd; background: #dbeafe; color: #1e40af; }
    #modalHealthDashboard .health-dash-extra { font-size: 12px; color: #475569; margin-top: 4px; }
    #modalHealthDashboard .health-dash-details { margin-top: 8px; }
    #modalHealthDashboard .health-dash-details summary {
      cursor: pointer; font-size: 12px; font-weight: 700; color: #64748b; user-select: none;
    }
    #modalHealthDashboard .health-dash-item-detalhe {
      margin: 6px 0 0; white-space: pre-wrap; word-break: break-word;
      font-size: 11px; line-height: 1.4; color: #475569; font-family: inherit;
    }
    /* HEALTH_DASH_CHARTS_V3_END */
'''

INTRO_OLD = (
    '<p class="muted" style="font-size:12px;line-height:1.45;margin:0;">'
    "Diagnostico rapido do servidor AlmaLinux e integracoes. Nao altera configuracoes.</p>"
)
INTRO_NEW = (
    '<p class="muted" style="font-size:12px;line-height:1.45;margin:0;">'
    "Resumo simples do que esta ok ou precisa de atencao. "
    "Backup mostra ha quanto tempo foi o ultimo salvamento automatico — nao e porcentagem de disco.</p>"
)

TARGETS = [
    Path("/opt/onixsystem-prod/sga_financeiro/main.py"),
    Path("/opt/onixsystem-homolog/sga_financeiro/main.py"),
]


def patch_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    i0 = text.find(JS_BEGIN)
    i1 = text.find(JS_END, i0)
    if i0 < 0 or i1 < 0:
        raise RuntimeError(f"Marcadores JS nao encontrados em {path}")
    i1 += len(JS_END)
    text = text[:i0] + NEW_JS + text[i1:]

    c0 = text.find(CSS_BEGIN)
    c1 = text.find(CSS_END, c0)
    if c0 < 0 or c1 < 0:
        raise RuntimeError(f"Marcadores CSS nao encontrados em {path}")
    c1 += len(CSS_END)
    text = text[:c0] + NEW_CSS + text[c1:]

    if INTRO_OLD in text:
        text = text.replace(INTRO_OLD, INTRO_NEW, 1)

    path.write_text(text, encoding="utf-8")
    print(f"OK saude simples: {path}")


def main() -> None:
    for path in TARGETS:
        patch_file(path)


if __name__ == "__main__":
    main()
