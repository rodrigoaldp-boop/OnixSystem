#!/usr/bin/env python3
"""Reformula visual da tela Saude do sistema com barras horizontais (somente UI)."""
from __future__ import annotations

from pathlib import Path

JS_BEGIN = "    /* HEALTH_DASH_CHARTS_V3_JS_BEGIN */"
JS_END = "    /* HEALTH_DASH_CHARTS_V3_JS_END */"
CSS_BEGIN = "    /* HEALTH_DASH_CHARTS_V3_BEGIN */"
CSS_END = "    /* HEALTH_DASH_CHARTS_V3_END */"

NEW_CSS = r'''    /* HEALTH_DASH_CHARTS_V3_BEGIN */
    #modalHealthDashboard.modal-overlay {
      align-items: stretch;
      justify-content: center;
      padding: 18px;
      background: rgba(15, 23, 42, 0.55);
    }
    #modalHealthDashboard .modal-box,
    #modalHealthDashboard .modal-box.modal-box--finance {
      width: min(1180px, 96vw) !important;
      max-width: 1180px !important;
      max-height: calc(100vh - 36px) !important;
      margin: 0 auto !important;
      display: flex !important;
      flex-direction: column !important;
      overflow: hidden !important;
      border-radius: 18px !important;
      border: 1px solid #dbe3ef !important;
      background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%) !important;
      box-shadow: 0 24px 60px rgba(15, 23, 42, 0.28) !important;
    }
    #modalHealthDashboard .health-dash-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 16px 18px 12px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.35);
      background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
    }
    #modalHealthDashboard .health-dash-header-title {
      font-size: 18px;
      font-weight: 850;
      letter-spacing: -0.02em;
      color: #0f172a;
    }
    #modalHealthDashboard .health-dash-header-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    #modalHealthDashboard .health-dash-btn {
      appearance: none;
      border: 1px solid #cbd5e1;
      background: linear-gradient(180deg, #ffffff 0%, #eef2ff 100%);
      color: #0f172a;
      font-weight: 750;
      font-size: 12px;
      padding: 8px 14px;
      border-radius: 999px;
      cursor: pointer;
      box-shadow: 0 1px 0 rgba(255,255,255,.8) inset, 0 6px 14px rgba(15, 23, 42, 0.08);
      transition: transform .15s ease, box-shadow .15s ease, background .15s ease;
    }
    #modalHealthDashboard .health-dash-btn:hover {
      transform: translateY(-1px);
      box-shadow: 0 1px 0 rgba(255,255,255,.9) inset, 0 10px 18px rgba(15, 23, 42, 0.12);
    }
    #modalHealthDashboard .health-dash-btn--primary {
      border-color: #93c5fd;
      background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%);
      color: #1e3a8a;
    }
    #modalHealthDashboard .health-dash-body {
      padding: 14px 18px 18px !important;
      overflow: auto !important;
      flex: 1 1 auto !important;
      max-height: none !important;
    }
    #modalHealthDashboard .health-dash-intro {
      margin: 0 0 12px;
      font-size: 12px;
      line-height: 1.45;
      color: #64748b;
    }
    #modalHealthDashboard .health-dash-summary {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin: 0 0 16px;
      padding: 14px 16px;
      border-radius: 14px;
      border: 1px solid #dbe3ef;
      background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
    }
    #modalHealthDashboard .health-dash-summary.is-ok {
      border-color: #86efac;
      background: linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%);
    }
    #modalHealthDashboard .health-dash-summary.is-aviso {
      border-color: #fcd34d;
      background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%);
    }
    #modalHealthDashboard .health-dash-summary.is-erro {
      border-color: #fca5a5;
      background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
    }
    #modalHealthDashboard .health-dash-summary-left {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
    }
    #modalHealthDashboard .health-dash-summary-title {
      font-size: 15px;
      font-weight: 850;
      color: #0f172a;
      letter-spacing: 0.02em;
    }
    #modalHealthDashboard .health-dash-summary-counts {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 12px;
      font-weight: 700;
      color: #475569;
    }
    #modalHealthDashboard .health-dash-summary-counts .is-ok { color: #15803d; }
    #modalHealthDashboard .health-dash-summary-counts .is-aviso { color: #b45309; }
    #modalHealthDashboard .health-dash-summary-counts .is-erro { color: #b91c1c; }
    #modalHealthDashboard .health-dash-grid {
      display: flex !important;
      flex-direction: column !important;
      gap: 18px !important;
      margin-top: 0 !important;
    }
    #modalHealthDashboard .health-dash-group {
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    #modalHealthDashboard .health-dash-group-title {
      grid-column: auto !important;
      margin: 0 !important;
      padding: 0 2px !important;
      border: 0 !important;
      font-size: 11px !important;
      font-weight: 850 !important;
      letter-spacing: 0.08em !important;
      text-transform: uppercase;
      color: #64748b !important;
    }
    #modalHealthDashboard .hb-row {
      position: relative;
      padding: 12px 14px 12px;
      border-radius: 14px;
      border: 1px solid rgba(148, 163, 184, 0.35);
      background: linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(248,250,252,0.94) 100%);
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
      overflow: hidden;
    }
    #modalHealthDashboard .hb-row::before {
      content: "";
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 4px;
      background: var(--hb-accent, #94a3b8);
    }
    #modalHealthDashboard .hb-top {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 8px;
    }
    #modalHealthDashboard .hb-name {
      font-size: 13px;
      font-weight: 850;
      color: #0f172a;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      min-width: 0;
    }
    #modalHealthDashboard .hb-value {
      font-size: 18px;
      font-weight: 900;
      letter-spacing: -0.02em;
      color: var(--hb-accent, #0f172a);
      white-space: nowrap;
    }
    #modalHealthDashboard .hb-track {
      position: relative;
      height: 18px;
      border-radius: 999px;
      background:
        linear-gradient(180deg, rgba(15,23,42,0.18) 0%, rgba(15,23,42,0.08) 40%, rgba(255,255,255,0.35) 100%),
        #1e293b;
      box-shadow:
        inset 0 2px 4px rgba(0,0,0,0.35),
        inset 0 -1px 0 rgba(255,255,255,0.12);
      overflow: hidden;
    }
    #modalHealthDashboard .hb-fill {
      position: absolute;
      left: 0; top: 0; bottom: 0;
      width: 0%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--hb-c1), var(--hb-c2));
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,0.55),
        inset 0 -2px 4px rgba(0,0,0,0.18),
        0 0 12px color-mix(in srgb, var(--hb-c2) 35%, transparent);
      transition: width .7s cubic-bezier(.22,.8,.28,1);
    }
    #modalHealthDashboard .hb-fill::after {
      content: "";
      position: absolute;
      left: 8px; right: 8px; top: 2px;
      height: 42%;
      border-radius: 999px;
      background: linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0));
      pointer-events: none;
    }
    #modalHealthDashboard .hb-meta {
      margin-top: 8px;
      font-size: 12px;
      line-height: 1.45;
      color: #475569;
    }
    #modalHealthDashboard .hb-details {
      margin-top: 8px;
    }
    #modalHealthDashboard .hb-details summary {
      cursor: pointer;
      user-select: none;
      font-size: 11px;
      font-weight: 750;
      color: #64748b;
      list-style: none;
    }
    #modalHealthDashboard .hb-details summary::-webkit-details-marker { display: none; }
    #modalHealthDashboard .hb-details summary::before {
      content: "▸ ";
      color: #94a3b8;
    }
    #modalHealthDashboard .hb-details[open] summary::before { content: "▾ "; }
    #modalHealthDashboard .hb-detalhe {
      margin: 6px 0 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 11px;
      line-height: 1.4;
      color: #475569;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: rgba(148,163,184,0.12);
      border-radius: 8px;
      padding: 8px 10px;
    }
    #modalHealthDashboard .health-dash-manutencao { display: none !important; }
    @media (max-width: 720px) {
      #modalHealthDashboard.modal-overlay { padding: 8px; }
      #modalHealthDashboard .modal-box,
      #modalHealthDashboard .modal-box.modal-box--finance {
        width: 100% !important;
        max-width: 100% !important;
        max-height: calc(100vh - 16px) !important;
        border-radius: 14px !important;
      }
      #modalHealthDashboard .hb-value { font-size: 16px; }
      #modalHealthDashboard .hb-name { font-size: 12px; }
      #modalHealthDashboard .health-dash-summary { flex-direction: column; align-items: flex-start; }
    }
    /* HEALTH_DASH_CHARTS_V3_END */
'''

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
      if (h < 1) return 'ha ' + Math.max(1, Math.round(h * 60)) + ' min';
      if (h < 48) {
        var hh = Math.floor(h);
        var mm = Math.round((h - hh) * 60);
        if (mm === 60) { hh += 1; mm = 0; }
        return mm ? ('ha ' + hh + 'h' + String(mm).padStart(2, '0')) : ('ha ' + hh + ' h');
      }
      return 'ha ' + (Math.round((h / 24) * 10) / 10) + ' dia(s)';
    }

    function healthDashToneFromStatus(st) {
      var s = String(st || '').toLowerCase();
      if (s === 'ok') return 'ok';
      if (s === 'aviso') return 'aviso';
      if (s === 'risco') return 'alerta';
      if (s === 'erro') return 'critico';
      return 'info';
    }

    // Uso alto = pior (CPU / RAM / Disco / conexoes)
    function healthDashToneUsageHighBad(pct) {
      var p = Number(pct);
      if (!isFinite(p)) return 'info';
      if (p >= 90) return 'critico';
      if (p >= 85) return 'alerta';
      if (p >= 70) return 'aviso';
      return 'ok';
    }

    // Valor alto = melhor (peers ativos, dias de certificado)
    function healthDashToneHighGood(pct) {
      var p = Number(pct);
      if (!isFinite(p)) return 'info';
      if (p >= 80) return 'ok';
      if (p >= 50) return 'aviso';
      if (p >= 25) return 'alerta';
      return 'critico';
    }

    function healthDashToneColors(tone) {
      if (tone === 'ok') return { accent: '#16a34a', c1: '#4ade80', c2: '#15803d' };
      if (tone === 'aviso') return { accent: '#ca8a04', c1: '#fde047', c2: '#ca8a04' };
      if (tone === 'alerta') return { accent: '#ea580c', c1: '#fdba74', c2: '#c2410c' };
      if (tone === 'critico') return { accent: '#dc2626', c1: '#f87171', c2: '#b91c1c' };
      return { accent: '#2563eb', c1: '#93c5fd', c2: '#1d4ed8' };
    }

    function healthDashNome(it) {
      return String(it.nome || it.titulo || it.id || 'Indicador');
    }

    function healthDashIndicatorModel(it) {
      var id = String(it.id || '');
      var m = it.metricas || {};
      var st = String(it.status || 'info').toLowerCase();
      var model = {
        name: healthDashNome(it).toUpperCase(),
        valueLabel: healthDashStatusLabel(st).toUpperCase(),
        fillPct: 100,
        tone: healthDashToneFromStatus(st),
        meta: String(it.resumo || ''),
        mode: 'status'
      };

      if (id === 'cpu') {
        var cpuPct = Number(m.pct != null ? m.pct : m.barra_pct);
        model.mode = 'usage';
        model.fillPct = isFinite(cpuPct) ? cpuPct : 0;
        model.valueLabel = isFinite(cpuPct) ? (cpuPct.toFixed(1).replace('.', ',') + '%') : model.valueLabel;
        model.tone = isFinite(cpuPct) ? healthDashToneUsageHighBad(cpuPct) : model.tone;
        var partsCpu = [];
        if (isFinite(cpuPct)) partsCpu.push('Uso: ' + cpuPct.toFixed(1).replace('.', ',') + '%');
        if (m.load_1 != null) partsCpu.push('Load: ' + String(m.load_1));
        if (m.cores != null) partsCpu.push('Nucleos: ' + String(m.cores));
        if (partsCpu.length) model.meta = partsCpu.join(' • ');
        return model;
      }

      if (id === 'memoria') {
        var ramPct = Number(m.pct != null ? m.pct : m.barra_pct);
        model.mode = 'usage';
        model.fillPct = isFinite(ramPct) ? ramPct : 0;
        model.valueLabel = isFinite(ramPct) ? (ramPct.toFixed(1).replace('.', ',') + '%') : model.valueLabel;
        model.tone = isFinite(ramPct) ? healthDashToneUsageHighBad(ramPct) : model.tone;
        var partsRam = [];
        if (isFinite(ramPct)) partsRam.push('Uso: ' + ramPct.toFixed(1).replace('.', ',') + '%');
        if (m.disponivel != null) partsRam.push('Disponivel: ' + healthDashFormatBytes(m.disponivel));
        if (m.usada != null && m.total != null) partsRam.push(healthDashFormatBytes(m.usada) + ' / ' + healthDashFormatBytes(m.total));
        if (m.swap_pct != null) partsRam.push('Swap: ' + Number(m.swap_pct).toFixed(1).replace('.', ',') + '%');
        if (partsRam.length) model.meta = partsRam.join(' • ');
        return model;
      }

      if (id === 'disco') {
        var diskPct = Number(m.pior_pct != null ? m.pior_pct : m.barra_pct);
        model.mode = 'usage';
        model.fillPct = isFinite(diskPct) ? diskPct : 0;
        model.valueLabel = isFinite(diskPct) ? (diskPct.toFixed(1).replace('.', ',') + '%') : model.valueLabel;
        model.tone = isFinite(diskPct) ? healthDashToneUsageHighBad(diskPct) : model.tone;
        var partsDisk = [];
        if (isFinite(diskPct)) {
          partsDisk.push('Usado: ' + diskPct.toFixed(1).replace('.', ',') + '%');
          partsDisk.push('Livre: ' + (100 - diskPct).toFixed(1).replace('.', ',') + '%');
        }
        var parts = Array.isArray(m.particoes) ? m.particoes : [];
        if (parts.length) {
          var p0 = parts[0] || {};
          if (p0.free != null) partsDisk.push(healthDashFormatBytes(p0.free) + ' disponiveis');
        }
        if (partsDisk.length) model.meta = partsDisk.join(' • ');
        return model;
      }

      if (id === 'postgres') {
        // Status principal (conectado/erro). Conexoes ficam no meta.
        model.mode = 'status';
        model.fillPct = 100;
        model.valueLabel = (st === 'ok') ? 'OK' : healthDashStatusLabel(st).toUpperCase();
        model.tone = healthDashToneFromStatus(st);
        var partsPg = [];
        if (m.latencia_ms != null) partsPg.push(m.latencia_ms + ' ms');
        if (m.conexoes_em_uso != null && m.conexoes_max != null) {
          partsPg.push('Conexoes: ' + m.conexoes_em_uso + '/' + m.conexoes_max);
          if (m.conexoes_pct != null) partsPg.push(Number(m.conexoes_pct).toFixed(1).replace('.', ',') + '%');
        }
        if (m.tamanho_bytes != null) partsPg.push(healthDashFormatBytes(m.tamanho_bytes));
        if (partsPg.length) model.meta = partsPg.join(' • ');
        else if (it.resumo) model.meta = String(it.resumo);
        return model;
      }

      if (id === 'backup') {
        model.mode = 'status';
        model.fillPct = 100;
        model.valueLabel = (st === 'ok') ? 'OK' : healthDashStatusLabel(st).toUpperCase();
        model.tone = healthDashToneFromStatus(st);
        var partsBk = [];
        if (it.resumo) partsBk.push(String(it.resumo));
        var idade = healthDashIdadeTexto(m.idade_horas);
        if (idade) partsBk.push(idade);
        if (m.qtd_backups != null) partsBk.push(m.qtd_backups + ' arquivos');
        if (m.espaco_bytes != null) partsBk.push(healthDashFormatBytes(m.espaco_bytes));
        if (partsBk.length) model.meta = partsBk.join(' • ');
        return model;
      }

      if (id === 'certificado') {
        model.mode = 'status';
        model.fillPct = 100;
        var dias = Number(m.dias_restantes);
        if (isFinite(dias)) {
          model.valueLabel = Math.round(dias) + 'd';
          // mais dias = melhor
          var pctDias = Math.max(0, Math.min(100, (dias / 365) * 100));
          model.tone = healthDashToneHighGood(pctDias);
          if (st === 'erro') model.tone = 'critico';
          else if (st === 'aviso' || st === 'risco') model.tone = healthDashToneFromStatus(st);
        } else {
          model.valueLabel = healthDashStatusLabel(st).toUpperCase();
        }
        model.meta = it.resumo || '';
        return model;
      }

      if (id === 'wireguard') {
        var peers = Number(m.peers) || 0;
        var ativos = Number(m.peers_ativos) || 0;
        if (peers > 0) {
          var pctPeers = (ativos / peers) * 100;
          model.mode = 'usage';
          model.fillPct = pctPeers;
          model.valueLabel = ativos + '/' + peers;
          model.tone = (st === 'erro') ? 'critico' : healthDashToneHighGood(pctPeers);
          model.meta = 'Peers ativos: ' + ativos + ' de ' + peers;
          if (m.rx != null || m.tx != null) {
            model.meta += ' • RX ' + healthDashFormatBytes(m.rx || 0) + ' / TX ' + healthDashFormatBytes(m.tx || 0);
          }
          return model;
        }
      }

      if (id === 'smtp') {
        model.mode = 'status';
        model.fillPct = 100;
        model.valueLabel = (st === 'ok') ? 'OK' : healthDashStatusLabel(st).toUpperCase();
        var partsSmtp = [];
        if (m.latencia_ms != null) partsSmtp.push(m.latencia_ms + ' ms');
        if (m.host) partsSmtp.push(String(m.host) + (m.porta ? (':' + m.porta) : ''));
        if (m.remetente) partsSmtp.push(String(m.remetente));
        model.meta = partsSmtp.length ? partsSmtp.join(' • ') : (it.resumo || '');
        return model;
      }

      if (id === 'whatsapp' || id === 'nginx' || id === 'containers' || id === 'servicos' || id === 'armazenamento') {
        model.mode = 'status';
        model.fillPct = 100;
        if (id === 'nginx' && (m.ativo === true || m.ativo === false)) {
          model.valueLabel = m.ativo ? 'UP' : 'DOWN';
        } else if (st === 'ok') {
          model.valueLabel = 'OK';
        } else {
          model.valueLabel = healthDashStatusLabel(st).toUpperCase();
        }
        model.meta = it.resumo || '';
        if (id === 'servicos' && m.ativos != null) {
          model.meta = (m.ativos + ' ativos') + (m.falha ? (' • ' + m.falha + ' com falha') : '') + (m.total != null ? (' • total ' + m.total) : '');
        }
        if (id === 'containers') {
          var pc = [];
          if (m.runtime) pc.push(String(m.runtime));
          if (m.ativos != null) pc.push(m.ativos + ' ativos');
          if (m.imagens != null) pc.push(m.imagens + ' imagens');
          if (pc.length) model.meta = pc.join(' • ');
        }
        if (id === 'armazenamento' && Array.isArray(m.diretorios) && m.diretorios.length) {
          model.meta = m.diretorios.length + ' diretorios analisados';
        }
        return model;
      }

      // fallback generico: se houver barra_pct/pct, trata como uso (alto=pior)
      var genericPct = Number(m.pct != null ? m.pct : m.barra_pct);
      if (isFinite(genericPct) && id !== 'saude_geral') {
        model.mode = 'usage';
        model.fillPct = genericPct;
        model.valueLabel = genericPct.toFixed(1).replace('.', ',') + '%';
        model.tone = healthDashToneUsageHighBad(genericPct);
        model.meta = it.resumo || '';
        return model;
      }

      model.meta = it.resumo || '';
      return model;
    }

    function healthDashRowHtml(it) {
      var model = healthDashIndicatorModel(it);
      var colors = healthDashToneColors(model.tone);
      var fill = Math.max(0, Math.min(100, Number(model.fillPct) || 0));
      var html = '';
      html += '<div class="hb-row" style="--hb-accent:' + colors.accent + ';--hb-c1:' + colors.c1 + ';--hb-c2:' + colors.c2 + '">';
      html += '<div class="hb-top">';
      html += '<div class="hb-name">' + healthDashEsc(model.name) + '</div>';
      html += '<div class="hb-value">' + healthDashEsc(model.valueLabel) + '</div>';
      html += '</div>';
      html += '<div class="hb-track"><div class="hb-fill" data-hb-width="' + fill.toFixed(2) + '"></div></div>';
      if (model.meta) html += '<div class="hb-meta">' + healthDashEsc(model.meta) + '</div>';
      if (it.detalhe) {
        html += '<details class="hb-details"><summary>Detalhes</summary><pre class="hb-detalhe">' + healthDashEsc(it.detalhe) + '</pre></details>';
      }
      html += '</div>';
      return html;
    }

    function healthDashAnimateBars(root) {
      if (!root) return;
      var fills = root.querySelectorAll('.hb-fill[data-hb-width]');
      // force reflow then animate
      fills.forEach(function(el) { el.style.width = '0%'; });
      requestAnimationFrame(function() {
        requestAnimationFrame(function() {
          fills.forEach(function(el) {
            el.style.width = String(el.getAttribute('data-hb-width') || '0') + '%';
          });
        });
      });
    }

    function renderHealthDashboard(data) {
      var resumo = document.getElementById('healthDashResumo');
      var grid = document.getElementById('healthDashGrid');
      var man = document.getElementById('healthDashManutencao');
      if (!resumo || !grid) return;
      if (man) man.style.display = 'none';

      var itens = Array.isArray(data && data.itens) ? data.itens.slice() : [];
      itens = itens.filter(function(it) { return String(it.id || '') !== 'saude_geral'; });

      var nOk = 0, nAviso = 0, nErro = 0, nInfo = 0;
      itens.forEach(function(it) {
        var st = String(it.status || '').toLowerCase();
        if (st === 'ok') nOk += 1;
        else if (st === 'aviso' || st === 'risco') nAviso += 1;
        else if (st === 'erro') nErro += 1;
        else nInfo += 1;
      });

      // Preferir contadores oficiais do endpoint quando existirem
      if (data && data.resumo_geral) {
        if (data.resumo_geral.normais != null) nOk = Number(data.resumo_geral.normais) || nOk;
        if (data.resumo_geral.alertas != null) nAviso = Number(data.resumo_geral.alertas) || nAviso;
        if (data.resumo_geral.erros != null) nErro = Number(data.resumo_geral.erros) || nErro;
      } else if (typeof data.alertas === 'number' && data.alertas > 0 && nErro === 0 && nAviso === 0) {
        // fallback leve
      }

      var headline = '● SISTEMA SAUDAVEL';
      var sumCls = 'is-ok';
      if (nErro > 0) {
        headline = '● SISTEMA COM PROBLEMAS';
        sumCls = 'is-erro';
      } else if (nAviso > 0) {
        headline = '● SISTEMA EM ATENCAO';
        sumCls = 'is-aviso';
      }

      resumo.className = 'health-dash-summary ' + sumCls;
      resumo.style.display = '';
      resumo.innerHTML =
        '<div class="health-dash-summary-left">' +
          '<div class="health-dash-summary-title">' + healthDashEsc(headline) + '</div>' +
          '<div class="health-dash-summary-counts">' +
            '<span class="is-ok">' + nOk + ' OK</span>' +
            '<span class="is-aviso">' + nAviso + ' alerta' + (nAviso === 1 ? '' : 's') + '</span>' +
            '<span class="is-erro">' + nErro + ' problema' + (nErro === 1 ? '' : 's') + '</span>' +
          '</div>' +
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
        html += '<section class="health-dash-group">';
        html += '<div class="health-dash-group-title">' + healthDashEsc(healthDashGrupoTitulo(g)) + '</div>';
        lista.forEach(function(it) { html += healthDashRowHtml(it); });
        html += '</section>';
      });
      grid.innerHTML = html || '<div class="muted">Nenhum diagnostico disponivel.</div>';
      healthDashAnimateBars(grid);

      if (typeof atualizarBadgeHealthDashboard === 'function') {
        try { atualizarBadgeHealthDashboard(data); } catch (eBadge) {}
      }
    }
    /* HEALTH_DASH_CHARTS_V3_JS_END */
'''

MODAL_OLD = '''  <div id="modalHealthDashboard" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance">
      <div class="health-dash-header">
        <div style="font-weight:bold;">Saude do sistema</div>
        <div style="display:flex; gap:8px;">
          <button class="alt" type="button" onclick="void carregarHealthDashboard(true)">Atualizar</button>
          <button class="alt" type="button" onclick="fecharModalHealthDashboard()">Fechar</button>
        </div>
      </div>
      <div class="health-dash-body">
<p class="muted" style="font-size:12px;line-height:1.45;margin:0;">Resumo simples do que esta ok ou precisa de atencao. Backup mostra ha quanto tempo foi o ultimo salvamento automatico — nao e porcentagem de disco.</p>
      <div id="healthDashResumo" class="health-dash-summary">Carregando...</div>
      <div id="healthDashGrid" class="health-dash-grid"></div>'''

MODAL_OLD_ALT = '''  <div id="modalHealthDashboard" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance">
      <div class="health-dash-header">
        <div style="font-weight:bold;">Saude do sistema</div>
        <div style="display:flex; gap:8px;">
          <button class="alt" type="button" onclick="void carregarHealthDashboard(true)">Atualizar</button>
          <button class="alt" type="button" onclick="fecharModalHealthDashboard()">Fechar</button>
        </div>
      </div>
      <div class="health-dash-body">
<p class="muted" style="font-size:12px;line-height:1.45;margin:0;">Diagnostico rapido do servidor AlmaLinux e integracoes. Nao altera configuracoes.</p>
      <div id="healthDashResumo" class="health-dash-summary">Carregando...</div>
      <div id="healthDashGrid" class="health-dash-grid"></div>'''

MODAL_NEW = '''  <div id="modalHealthDashboard" class="modal-overlay hidden">
    <div class="modal-box modal-box--finance">
      <div class="health-dash-header">
        <div class="health-dash-header-title">Saude do sistema</div>
        <div class="health-dash-header-actions">
          <button class="health-dash-btn health-dash-btn--primary" type="button" onclick="void carregarHealthDashboard(true)">Atualizar</button>
          <button class="health-dash-btn" type="button" onclick="fecharModalHealthDashboard()">Fechar</button>
        </div>
      </div>
      <div class="health-dash-body">
<p class="health-dash-intro">Painel de saude do servidor e integracoes. As barras usam os dados ja coletados pelo sistema — sem alterar configuracoes.</p>
      <div id="healthDashResumo" class="health-dash-summary">Carregando...</div>
      <div id="healthDashGrid" class="health-dash-grid"></div>'''

TARGETS = [
    Path("/opt/onixsystem-prod/sga_financeiro/main.py"),
    Path("/opt/onixsystem-homolog/sga_financeiro/main.py"),
]


def _replace_between(text: str, begin: str, end: str, new_block: str) -> str:
    i0 = text.find(begin)
    i1 = text.find(end, i0)
    if i0 < 0 or i1 < 0:
        raise RuntimeError(f"Marcadores nao encontrados: {begin!r} .. {end!r}")
    i1 += len(end)
    return text[:i0] + new_block + text[i1:]


def patch_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = _replace_between(text, JS_BEGIN, JS_END, NEW_JS)
    text = _replace_between(text, CSS_BEGIN, CSS_END, NEW_CSS)
    if MODAL_OLD in text:
        text = text.replace(MODAL_OLD, MODAL_NEW, 1)
    elif MODAL_OLD_ALT in text:
        text = text.replace(MODAL_OLD_ALT, MODAL_NEW, 1)
    else:
        # fallback: so botoes/titulo se o paragrafo intro mudou
        if 'class="health-dash-header-title"' not in text:
            text = text.replace(
                '<div style="font-weight:bold;">Saude do sistema</div>',
                '<div class="health-dash-header-title">Saude do sistema</div>',
                1,
            )
            text = text.replace(
                '<div style="display:flex; gap:8px;">\n          <button class="alt" type="button" onclick="void carregarHealthDashboard(true)">Atualizar</button>\n          <button class="alt" type="button" onclick="fecharModalHealthDashboard()">Fechar</button>\n        </div>',
                '<div class="health-dash-header-actions">\n          <button class="health-dash-btn health-dash-btn--primary" type="button" onclick="void carregarHealthDashboard(true)">Atualizar</button>\n          <button class="health-dash-btn" type="button" onclick="fecharModalHealthDashboard()">Fechar</button>\n        </div>',
                1,
            )
    path.write_text(text, encoding="utf-8")
    print(f"OK barras saude: {path}")


def main() -> None:
    for path in TARGETS:
        patch_file(path)


if __name__ == "__main__":
    main()
