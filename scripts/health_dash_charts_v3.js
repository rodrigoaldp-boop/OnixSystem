/* HEALTH_DASH_CHARTS_V3_JS_BEGIN */
    function healthDashEsc(text) {
      return String(text == null ? '' : text)
        .split('&').join('&amp;')
        .split('<').join('&lt;')
        .split('>').join('&gt;')
        .split('"').join('&quot;');
    }

    function healthDashById(itens) {
      var map = {};
      (itens || []).forEach(function(it) { map[String(it.id || '')] = it; });
      return map;
    }

    function healthDashPctColor(pct) {
      var p = Number(pct);
      if (!isFinite(p)) return '#64748b';
      if (p >= 90) return '#ef4444';
      if (p >= 80) return '#f97316';
      if (p >= 70) return '#f59e0b';
      return '#22c55e';
    }

    function healthDashStatusTone(st) {
      var s = String(st || '').toLowerCase();
      if (s === 'ok') return 'ok';
      if (s === 'aviso') return 'aviso';
      if (s === 'risco' || s === 'erro') return s;
      return 'info';
    }

    function healthDashFormatUptime(seconds) {
      var s = Math.max(0, Number(seconds) || 0);
      var d = Math.floor(s / 86400);
      var h = Math.floor((s % 86400) / 3600);
      if (d >= 7) {
        var weeks = (d / 7).toFixed(1);
        if (weeks.slice(-2) === '.0') weeks = weeks.slice(0, -2);
        return weeks + 'w';
      }
      if (d >= 1) return d + 'd ' + h + 'h';
      var m = Math.floor((s % 3600) / 60);
      if (h >= 1) return h + 'h ' + m + 'm';
      return m + 'm';
    }

    function healthDashFormatBytes(n) {
      var v = Number(n);
      if (!isFinite(v) || v < 0) return '-';
      var u = ['B', 'KB', 'MB', 'GB', 'TB'];
      var i = 0;
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
      return (i === 0 ? String(Math.round(v)) : v.toFixed(1)) + ' ' + u[i];
    }

    function healthDashHistoryPush(snapshot) {
      var key = 'onixHealthDashHistoryV1';
      var list = [];
      try { list = JSON.parse(sessionStorage.getItem(key) || '[]') || []; } catch (eHist) { list = []; }
      if (!Array.isArray(list)) list = [];
      list.push(snapshot);
      if (list.length > 36) list = list.slice(list.length - 36);
      try { sessionStorage.setItem(key, JSON.stringify(list)); } catch (eSet) {}
      return list;
    }

    function healthDashSparkSvg(points, color) {
      var vals = (points || []).map(function(p) { return Number(p); }).filter(function(v) { return isFinite(v); });
      var w = 320, h = 100, pad = 6;
      if (vals.length < 2) {
        vals = vals.length ? [vals[0], vals[0]] : [0, 0];
      }
      var min = Math.min.apply(null, vals);
      var max = Math.max.apply(null, vals);
      if (max === min) { max = min + 1; }
      var path = '';
      vals.forEach(function(v, idx) {
        var x = pad + (idx / (vals.length - 1)) * (w - pad * 2);
        var y = h - pad - ((v - min) / (max - min)) * (h - pad * 2);
        path += (idx ? ' L ' : 'M ') + x.toFixed(1) + ' ' + y.toFixed(1);
      });
      var last = vals[vals.length - 1];
      var area = path + ' L ' + (w - pad) + ' ' + (h - pad) + ' L ' + pad + ' ' + (h - pad) + ' Z';
      return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<path d="' + area + '" fill="' + color + '" opacity="0.14"></path>' +
        '<path d="' + path + '" fill="none" stroke="' + color + '" stroke-width="2.2"></path>' +
        '<text x="' + (w - 8) + '" y="16" text-anchor="end" fill="#e2e8f0" font-size="12" font-weight="700">' +
        healthDashEsc(isFinite(last) ? (Math.round(last * 10) / 10) : '-') + '</text>' +
        '</svg>';
    }

    function healthDashGaugeSvg(pct, color) {
      var p = Math.max(0, Math.min(100, Number(pct) || 0));
      var cx = 55, cy = 52, r = 40;
      function polar(ang) {
        return { x: cx + r * Math.cos(ang), y: cy + r * Math.sin(ang) };
      }
      // semicircle from PI to 0 (left to right, upper arc)
      var start = Math.PI;
      var end = Math.PI - (Math.PI * (p / 100));
      var p0 = polar(start);
      var p1 = polar(end);
      var large = (Math.PI * (p / 100)) > Math.PI ? 1 : 0;
      // track full semicircle
      var t1 = polar(0);
      var track = 'M ' + p0.x.toFixed(2) + ' ' + p0.y.toFixed(2) +
        ' A ' + r + ' ' + r + ' 0 0 1 ' + t1.x.toFixed(2) + ' ' + t1.y.toFixed(2);
      var value = 'M ' + p0.x.toFixed(2) + ' ' + p0.y.toFixed(2) +
        ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' + p1.x.toFixed(2) + ' ' + p1.y.toFixed(2);
      return '<svg viewBox="0 0 110 70" aria-hidden="true">' +
        '<path d="' + track + '" fill="none" stroke="#1e293b" stroke-width="10" stroke-linecap="round"></path>' +
        '<path d="' + value + '" fill="none" stroke="' + color + '" stroke-width="10" stroke-linecap="round"></path>' +
        '<text x="' + cx + '" y="58" text-anchor="middle" fill="#f8fafc" font-size="16" font-weight="800">' +
        healthDashEsc(Math.round(p) + '%') + '</text>' +
        '</svg>';
    }

    function healthDashSection(title, bodyHtml) {
      return '<div class="gf-section"><div class="gf-section-head"><span>' + healthDashEsc(title) +
        '</span><span>v</span></div><div class="gf-section-body">' + bodyHtml + '</div></div>';
    }

    function renderHealthDashboard(data) {
      var resumo = document.getElementById('healthDashResumo');
      var grid = document.getElementById('healthDashGrid');
      var man = document.getElementById('healthDashManutencao');
      if (!resumo || !grid) return;
      if (man) man.style.display = 'none';

      var rg = (data && data.resumo_geral) || {};
      var erros = Number(rg.erros) || 0;
      var avisos = Number(rg.alertas) || 0;
      var normais = Number(rg.normais) || 0;
      var quando = '';
      if (data && data.checked_at) {
        try { quando = ' | ' + new Date(data.checked_at).toLocaleString('pt-BR'); } catch (eWhen) { quando = ''; }
      }
      var bannerClass = 'gf-banner';
      var bannerText = 'Visao geral saudavel - ' + normais + ' verificacoes ok' + quando;
      if (erros > 0) {
        bannerClass += ' is-erro';
        bannerText = 'Criticos: ' + erros + ' | alertas: ' + avisos + ' | ok: ' + normais + quando;
      } else if (avisos > 0 || !(data && data.ok)) {
        bannerClass += ' is-warn';
        bannerText = 'Atencao: ' + avisos + ' alerta(s) | ok: ' + normais + quando;
      }
      resumo.className = bannerClass;
      resumo.style.display = 'block';
      resumo.textContent = bannerText;

      var itens = Array.isArray(data && data.itens) ? data.itens : [];
      var byId = healthDashById(itens);
      var cpu = byId.cpu || {};
      var mem = byId.memoria || {};
      var disco = byId.disco || {};
      var wg = byId.wireguard || {};
      var pg = byId.postgres || {};
      var cert = byId.certificado || {};
      var smtp = byId.smtp || {};
      var backup = byId.backup || {};
      var nginx = byId.nginx || {};
      var containers = byId.containers || {};
      var servicos = byId.servicos || {};
      var whatsapp = byId.whatsapp || {};
      var armazenamento = byId.armazenamento || {};

      var cpuPct = Number((cpu.metricas || {}).barra_pct != null ? cpu.metricas.barra_pct : (cpu.metricas || {}).pct);
      var ramPct = Number((mem.metricas || {}).barra_pct != null ? mem.metricas.barra_pct : (mem.metricas || {}).pct);
      var diskPct = Number((disco.metricas || {}).barra_pct != null ? disco.metricas.barra_pct : (disco.metricas || {}).pior_pct);
      var pgPct = Number((pg.metricas || {}).barra_pct);
      var peers = Number((wg.metricas || {}).peers) || 0;
      var peersAtivos = Number((wg.metricas || {}).peers_ativos) || 0;
      var wgPct = peers ? (peersAtivos / peers) * 100 : 0;
      var certDias = Number((cert.metricas || {}).dias_restantes);
      var certPct = isFinite(certDias) ? Math.max(0, Math.min(100, (certDias / 365) * 100)) : null;
      var uptime = healthDashFormatUptime((cpu.metricas || {}).uptime_segundos);

      var hist = healthDashHistoryPush({
        t: Date.now(),
        cpu: isFinite(cpuPct) ? cpuPct : null,
        ram: isFinite(ramPct) ? ramPct : null,
        disk: isFinite(diskPct) ? diskPct : null,
        wg: isFinite(wgPct) ? wgPct : null,
        pg: isFinite(pgPct) ? pgPct : null
      });
      var cpuSeries = hist.map(function(h) { return h.cpu; }).filter(function(v) { return v != null; });
      var ramSeries = hist.map(function(h) { return h.ram; }).filter(function(v) { return v != null; });
      var diskSeries = hist.map(function(h) { return h.disk; }).filter(function(v) { return v != null; });

      var kpis = '' +
        '<div class="gf-kpis">' +
          '<div class="gf-kpi"><div class="gf-kpi-label">Uptime</div><div class="gf-kpi-value is-ok">' + healthDashEsc(uptime) + '</div><div class="gf-kpi-sub">servidor AlmaLinux</div></div>' +
          '<div class="gf-kpi"><div class="gf-kpi-label">CPU Usage</div><div class="gf-kpi-value ' + (cpuPct >= 85 ? 'is-erro' : (cpuPct >= 70 ? 'is-aviso' : 'is-ok')) + '">' + healthDashEsc(isFinite(cpuPct) ? (Math.round(cpuPct * 10) / 10) + '%' : '-') + '</div><div class="gf-kpi-sub">load ' + healthDashEsc((cpu.metricas || {}).load_1 != null ? (cpu.metricas || {}).load_1 : '-') + '</div></div>' +
          '<div class="gf-kpi"><div class="gf-kpi-label">RAM Usage</div><div class="gf-kpi-value ' + (ramPct >= 85 ? 'is-erro' : (ramPct >= 70 ? 'is-aviso' : 'is-ok')) + '">' + healthDashEsc(healthDashFormatBytes((mem.metricas || {}).usada)) + '</div><div class="gf-kpi-sub">' + healthDashEsc(isFinite(ramPct) ? (Math.round(ramPct * 10) / 10) + '% de ' + healthDashFormatBytes((mem.metricas || {}).total) : '-') + '</div></div>' +
          '<div class="gf-kpi"><div class="gf-kpi-label">Disk Usage</div><div class="gf-kpi-value ' + (diskPct >= 85 ? 'is-erro' : (diskPct >= 70 ? 'is-aviso' : 'is-ok')) + '">' + healthDashEsc(isFinite(diskPct) ? (Math.round(diskPct * 10) / 10) + '%' : '-') + '</div><div class="gf-kpi-sub">pior particao monitorada</div></div>' +
          '<div class="gf-kpi"><div class="gf-kpi-label">WireGuard</div><div class="gf-kpi-value is-ok">' + healthDashEsc(peersAtivos + '/' + peers) + '</div><div class="gf-kpi-sub">peers ativos</div></div>' +
        '</div>';

      var trends = '' +
        '<div class="gf-trends">' +
          '<div class="gf-panel"><div class="gf-panel-title">Cluster CPU</div><div class="gf-panel-chart">' + healthDashSparkSvg(cpuSeries, '#22c55e') + '</div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Cluster RAM</div><div class="gf-panel-chart">' + healthDashSparkSvg(ramSeries, '#38bdf8') + '</div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Cluster Disk</div><div class="gf-panel-chart">' + healthDashSparkSvg(diskSeries, '#f59e0b') + '</div></div>' +
        '</div>';

      function gaugeCard(name, pct, sub) {
        var color = healthDashPctColor(pct);
        var val = isFinite(Number(pct)) ? Number(pct) : 0;
        return '<div class="gf-gauge"><div class="gf-gauge-chart">' + healthDashGaugeSvg(val, color) +
          '</div><div class="gf-gauge-name">' + healthDashEsc(name) + '</div><div class="gf-gauge-sub">' + healthDashEsc(sub || '') + '</div></div>';
      }

      var storageBars = '';
      var dirs = ((armazenamento.metricas || {}).diretorios) || [];
      if (dirs.length) {
        var maxB = 0;
        dirs.slice(0, 7).forEach(function(d) { maxB = Math.max(maxB, Number(d.bytes) || 0); });
        if (maxB <= 0) maxB = 1;
        storageBars = '<div class="gf-panel" style="min-height:132px;"><div class="gf-panel-title">Datastores / diretorios</div><div class="gf-panel-chart">';
        storageBars += '<svg viewBox="0 0 360 100" aria-hidden="true">';
        dirs.slice(0, 7).forEach(function(d, idx) {
          var hBar = Math.max(4, ((Number(d.bytes) || 0) / maxB) * 78);
          var x = 18 + idx * 48;
          var y = 90 - hBar;
          var colors = ['#22c55e', '#38bdf8', '#f59e0b', '#fb7185', '#a3e635', '#2dd4bf', '#94a3b8'];
          storageBars += '<rect x="' + x + '" y="' + y.toFixed(1) + '" width="28" height="' + hBar.toFixed(1) + '" rx="3" fill="' + colors[idx % colors.length] + '"></rect>';
        });
        storageBars += '</svg></div></div>';
      }

      var gauges = '<div class="gf-gauges">' +
        gaugeCard('CPU', cpuPct, (cpu.resumo || '')) +
        gaugeCard('RAM', ramPct, (mem.resumo || '')) +
        gaugeCard('Disco', diskPct, (disco.resumo || '')) +
        gaugeCard('PostgreSQL', pgPct, (pg.resumo || '')) +
        gaugeCard('WireGuard', wgPct, peersAtivos + '/' + peers + ' peers') +
        gaugeCard('Certificado', certPct, isFinite(certDias) ? (Math.round(certDias) + ' dias') : (cert.resumo || '')) +
        (storageBars || gaugeCard('Backup idade', Math.max(0, 100 - Math.min(100, (Number((backup.metricas || {}).idade_horas) || 0) / 24 * 100)), (backup.resumo || ''))) +
      '</div>';

      var serviceIds = ['nginx', 'whatsapp', 'smtp', 'postgres', 'containers', 'servicos', 'backup', 'certificado'];
      var svcHtml = '<div class="gf-services">';
      serviceIds.forEach(function(id) {
        var it = byId[id];
        if (!it) return;
        var tone = healthDashStatusTone(it.status);
        var meta = String(it.detalhe || '').split(String.fromCharCode(10)).slice(0, 1).join(' | ');
        svcHtml += '<div class="gf-svc is-' + tone + '">' +
          '<div class="gf-svc-title">' + healthDashEsc(it.nome || id) + '</div>' +
          '<div class="gf-svc-resumo">' + healthDashEsc(it.resumo || '') + '</div>' +
          '<div class="gf-svc-meta">' + healthDashEsc(meta) + '</div>' +
          '</div>';
      });
      svcHtml += '</div>';

      grid.innerHTML =
        healthDashSection('Cluster Status', kpis + trends) +
        healthDashSection('Capacity / Gauges', gauges) +
        healthDashSection('Services & Integrations', svcHtml);

      if (typeof atualizarBadgeHealthDashboard === 'function') {
        try { atualizarBadgeHealthDashboard(data); } catch (eBadge) {}
      }
    }
    /* HEALTH_DASH_CHARTS_V3_JS_END */
