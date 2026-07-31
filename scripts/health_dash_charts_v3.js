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
      if (!isFinite(p)) return '#444';
      if (p >= 90) return '#FF4500';
      if (p >= 80) return '#FF8C00';
      if (p >= 70) return '#FFD700';
      return '#7CFC00';
    }

    function healthDashFormatUptime(seconds) {
      var s = Math.max(0, Number(seconds) || 0);
      var d = Math.floor(s / 86400);
      var h = Math.floor((s % 86400) / 3600);
      if (d >= 7) {
        var weeks = (d / 7).toFixed(1);
        if (weeks.slice(-2) === '.0') weeks = weeks.slice(0, -2);
        return weeks + ' week';
      }
      if (d >= 1) return d + 'd ' + h + 'h';
      var m = Math.floor((s % 3600) / 60);
      if (h >= 1) return h + 'h ' + m + 'm';
      return m + 'm';
    }

    function healthDashFormatBytes(n, digits) {
      var v = Number(n);
      if (!isFinite(v) || v < 0) return '-';
      var u = ['B', 'KB', 'MB', 'GB', 'TB'];
      var i = 0;
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
      var d = digits == null ? 2 : digits;
      return (i === 0 ? String(Math.round(v)) : v.toFixed(d)) + ' ' + u[i];
    }

    function healthDashHistoryPush(snapshot) {
      var key = 'onixHealthDashHistoryV2';
      var list = [];
      try { list = JSON.parse(sessionStorage.getItem(key) || '[]') || []; } catch (eHist) { list = []; }
      if (!Array.isArray(list)) list = [];
      list.push(snapshot);
      if (list.length > 48) list = list.slice(list.length - 48);
      try { sessionStorage.setItem(key, JSON.stringify(list)); } catch (eSet) {}
      return list;
    }

    function healthDashSeries(list, field) {
      return (list || []).map(function(h) { return h[field]; }).filter(function(v) { return v != null && isFinite(Number(v)); }).map(Number);
    }

    function healthDashSparkSvg(points, color) {
      var vals = (points || []).slice();
      var w = 360, h = 90, pad = 4;
      if (vals.length < 2) vals = vals.length ? [vals[0], vals[0]] : [0, 0];
      var min = Math.min.apply(null, vals);
      var max = Math.max.apply(null, vals);
      if (max === min) max = min + 1;
      var path = '';
      vals.forEach(function(v, idx) {
        var x = pad + (idx / (vals.length - 1)) * (w - pad * 2);
        var y = h - pad - ((v - min) / (max - min)) * (h - pad * 2);
        path += (idx ? ' L ' : 'M ') + x.toFixed(1) + ' ' + y.toFixed(1);
      });
      var last = vals[vals.length - 1];
      var area = path + ' L ' + (w - pad) + ' ' + (h - pad) + ' L ' + pad + ' ' + (h - pad) + ' Z';
      return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
        '<path d="' + area + '" fill="' + color + '" opacity="0.12"></path>' +
        '<path d="' + path + '" fill="none" stroke="' + color + '" stroke-width="2"></path>' +
        '<text x="' + (w - 6) + '" y="12" text-anchor="end" fill="#ddd" font-size="11" font-weight="700">' +
        healthDashEsc(isFinite(last) ? (Math.round(last * 10) / 10) : '-') + '</text></svg>';
    }

    function healthDashGaugeSvg(pct, color, centerText) {
      var p = Math.max(0, Math.min(100, Number(pct) || 0));
      var cx = 54, cy = 50, r = 38;
      function polar(ang) { return { x: cx + r * Math.cos(ang), y: cy + r * Math.sin(ang) }; }
      var start = Math.PI;
      var end = Math.PI - (Math.PI * (p / 100));
      var p0 = polar(start);
      var p1 = polar(end);
      var t1 = polar(0);
      var track = 'M ' + p0.x.toFixed(2) + ' ' + p0.y.toFixed(2) + ' A ' + r + ' ' + r + ' 0 0 1 ' + t1.x.toFixed(2) + ' ' + t1.y.toFixed(2);
      var value = 'M ' + p0.x.toFixed(2) + ' ' + p0.y.toFixed(2) + ' A ' + r + ' ' + r + ' 0 0 1 ' + p1.x.toFixed(2) + ' ' + p1.y.toFixed(2);
      var label = centerText != null ? String(centerText) : (Math.round(p * 10) / 10) + '%';
      return '<svg viewBox="0 0 108 68" aria-hidden="true">' +
        '<path d="' + track + '" fill="none" stroke="#222" stroke-width="9" stroke-linecap="round"></path>' +
        '<path d="' + value + '" fill="none" stroke="' + color + '" stroke-width="9" stroke-linecap="round"></path>' +
        '<text x="' + cx + '" y="56" text-anchor="middle" fill="#fff" font-size="15" font-weight="800">' +
        healthDashEsc(label) + '</text></svg>';
    }

    function healthDashBarsSvg(items) {
      var list = (items || []).slice(0, 8);
      var w = 200, h = 200, padTop = 10, padBottom = 28, padX = 10;
      var chartH = h - padTop - padBottom;
      var n = Math.max(1, list.length);
      var bw = Math.max(10, ((w - padX * 2) / n) - 6);
      var html = '<svg viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true">';
      var colors = ['#7CFC00', '#FFD700', '#1E90FF', '#FF8C00', '#DA70D6', '#00CED1', '#FF6347', '#ADFF2F'];
      list.forEach(function(it, idx) {
        var pct = Math.max(0, Math.min(100, Number(it.pct) || 0));
        var barH = (pct / 100) * chartH;
        var x = padX + idx * ((w - padX * 2) / n) + 3;
        var y = padTop + (chartH - barH);
        html += '<rect x="' + x.toFixed(1) + '" y="' + padTop + '" width="' + bw.toFixed(1) + '" height="' + chartH + '" fill="#151515"></rect>';
        html += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + Math.max(2, barH).toFixed(1) + '" fill="' + (it.color || colors[idx % colors.length]) + '"></rect>';
        html += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (h - 8) + '" text-anchor="middle" fill="#888" font-size="8">' + healthDashEsc((it.name || '').slice(0, 6)) + '</text>';
      });
      html += '</svg>';
      return html;
    }

    function healthDashSection(title, bodyHtml) {
      return '<div class="gf-section"><div class="gf-section-head"><span>' + healthDashEsc(title) +
        '</span><span>v</span></div><div class="gf-section-body">' + bodyHtml + '</div></div>';
    }

    function healthDashGaugeCard(name, pct, opts) {
      opts = opts || {};
      var na = !!opts.na || !isFinite(Number(pct));
      var val = na ? 0 : Number(pct);
      var color = na ? '#333' : healthDashPctColor(val);
      var center = na ? 'N/A' : (opts.label != null ? opts.label : ((Math.round(val * 10) / 10) + '%'));
      return '<div class="gf-gauge' + (na || opts.alert ? ' is-na' : '') + '">' +
        ((na || opts.alert) ? '<div class="gf-gauge-alert">!</div>' : '') +
        '<div class="gf-gauge-chart">' + healthDashGaugeSvg(val, color, center) + '</div>' +
        '<div class="gf-gauge-name">' + healthDashEsc(name) + '</div></div>';
    }

    function renderHealthDashboard(data) {
      var resumo = document.getElementById('healthDashResumo');
      var grid = document.getElementById('healthDashGrid');
      var man = document.getElementById('healthDashManutencao');
      if (!resumo || !grid) return;
      if (man) man.style.display = 'none';
      resumo.className = 'gf-banner';
      resumo.style.display = 'none';

      var byId = healthDashById(Array.isArray(data && data.itens) ? data.itens : []);
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
      var whatsapp = byId.whatsapp || {};
      var servicos = byId.servicos || {};
      var armazenamento = byId.armazenamento || {};

      var cpuPct = Number((cpu.metricas || {}).pct);
      var ramPct = Number((mem.metricas || {}).pct);
      var diskPct = Number((disco.metricas || {}).pior_pct);
      var ramUsed = Number((mem.metricas || {}).usada);
      var cores = Number((cpu.metricas || {}).cores) || 0;
      // approx MHz display like Grafana sample (not exact host MHz)
      var cpuMhz = isFinite(cpuPct) && cores ? Math.round((cpuPct / 100) * cores * 3200) : null;
      var peers = Number((wg.metricas || {}).peers) || 0;
      var peersAtivos = Number((wg.metricas || {}).peers_ativos) || 0;
      var wgPct = peers ? (peersAtivos / peers) * 100 : 0;
      var pgPct = Number((pg.metricas || {}).barra_pct);
      var swapPct = Number((mem.metricas || {}).swap_pct);
      var certDias = Number((cert.metricas || {}).dias_restantes);
      var certPct = isFinite(certDias) ? Math.max(0, Math.min(100, (certDias / 365) * 100)) : null;
      var backupAge = Number((backup.metricas || {}).idade_horas);
      var backupFresh = isFinite(backupAge) ? Math.max(0, 100 - Math.min(100, (backupAge / 24) * 100)) : null;
      var smtpMs = Number((smtp.metricas || {}).latencia_ms);
      var smtpHealth = isFinite(smtpMs) ? Math.max(0, Math.min(100, 100 - (smtpMs / 1000) * 100)) : null;
      var nginxUp = !!(nginx.metricas || {}).ativo;
      var waOk = String(whatsapp.status || '').toLowerCase() === 'ok' || (!!(whatsapp.metricas || {}).envio_habilitado && !!(whatsapp.metricas || {}).worker_ativo);
      var rx = Number((wg.metricas || {}).rx);
      var tx = Number((wg.metricas || {}).tx);

      var hist = healthDashHistoryPush({
        t: Date.now(),
        cpu: isFinite(cpuPct) ? cpuPct : null,
        ram: isFinite(ramPct) ? ramPct : null,
        disk: isFinite(diskPct) ? diskPct : null,
        wg: isFinite(wgPct) ? wgPct : null,
        pg: isFinite(pgPct) ? pgPct : null,
        smtp: isFinite(smtpMs) ? smtpMs : null,
        rx: isFinite(rx) ? rx : null,
        tx: isFinite(tx) ? tx : null
      });

      // network MB/s from rx+tx deltas
      var netSeries = [];
      for (var i = 1; i < hist.length; i++) {
        var dt = (Number(hist[i].t) - Number(hist[i - 1].t)) / 1000;
        if (dt <= 0) continue;
        var dBytes = (Number(hist[i].rx || 0) + Number(hist[i].tx || 0)) - (Number(hist[i - 1].rx || 0) + Number(hist[i - 1].tx || 0));
        if (dBytes < 0) dBytes = 0;
        netSeries.push((dBytes / dt) / (1024 * 1024));
      }
      if (!netSeries.length) netSeries = [0, 0];

      var leftStats =
        '<div class="gf-stack">' +
          '<div class="gf-stat"><div class="gf-stat-label">Uptime</div><div class="gf-stat-value is-ok">' + healthDashEsc(healthDashFormatUptime((cpu.metricas || {}).uptime_segundos)) + '</div></div>' +
          '<div class="gf-stat"><div class="gf-stat-label">CPU Usage</div><div class="gf-stat-value ' + (cpuPct >= 85 ? 'is-erro' : (cpuPct >= 70 ? 'is-aviso' : 'is-ok')) + '">' + healthDashEsc(cpuMhz != null ? (cpuMhz + ' MHz') : '-') + '</div></div>' +
          '<div class="gf-stat"><div class="gf-stat-label">RAM Usage</div><div class="gf-stat-value ' + (ramPct >= 85 ? 'is-erro' : (ramPct >= 70 ? 'is-aviso' : 'is-ok')) + '">' + healthDashEsc(healthDashFormatBytes(ramUsed, 2)) + '</div></div>' +
        '</div>';

      var centerCharts =
        '<div class="gf-charts4">' +
          '<div class="gf-panel"><div class="gf-panel-title">Cluster CPU</div><div class="gf-panel-chart">' + healthDashSparkSvg(healthDashSeries(hist, 'cpu'), '#7CFC00') + '</div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Cluster RAM</div><div class="gf-panel-chart">' + healthDashSparkSvg(healthDashSeries(hist, 'ram'), '#7CFC00') + '</div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Cluster Network Usage</div><div class="gf-panel-chart">' + healthDashSparkSvg(netSeries, '#FFD700') + '</div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Cluster Storage / Disk</div><div class="gf-panel-chart">' + healthDashSparkSvg(healthDashSeries(hist, 'disk'), '#1E90FF') + '</div></div>' +
        '</div>';

      var barItems = [];
      (((disco.metricas || {}).particoes) || []).forEach(function(p) {
        var name = ((p.rotulos || p.paths || ['disk'])[0] || 'disk');
        barItems.push({ name: String(name).replace('/mnt/', '').replace('/opt/', ''), pct: 100 - Number(p.pct || 0), color: healthDashPctColor(p.pct) });
      });
      (((armazenamento.metricas || {}).diretorios) || []).slice(0, 5).forEach(function(d, idx) {
        // relative capacity bar using share of largest dir (visual only)
        barItems.push({ name: String(d.nome || d.path || 'dir').slice(0, 8), pct: null, bytes: Number(d.bytes) || 0 });
      });
      // convert byte dirs to % of max for remaining slots
      var maxBytes = 0;
      barItems.forEach(function(b) { if (b.bytes != null) maxBytes = Math.max(maxBytes, b.bytes); });
      barItems = barItems.map(function(b) {
        if (b.pct == null && maxBytes > 0) {
          return { name: b.name, pct: (b.bytes / maxBytes) * 100, color: '#1E90FF' };
        }
        return b;
      }).slice(0, 8);

      var rightBars =
        '<div class="gf-bars-panel"><div class="gf-panel-title">Datastores - Usage Capacity</div>' +
        '<div class="gf-panel-chart">' + healthDashBarsSvg(barItems) + '</div></div>';

      var cluster = '<div class="gf-cluster">' + leftStats + centerCharts + rightBars + '</div>';

      // Datastore-like gauges
      var parts = ((disco.metricas || {}).particoes) || [];
      function partPct(want) {
        for (var i = 0; i < parts.length; i++) {
          var paths = parts[i].paths || [];
          var rotulos = parts[i].rotulos || [];
          if (paths.indexOf(want) >= 0 || rotulos.indexOf(want) >= 0) return Number(parts[i].pct);
          if (want === 'hd_A' && (paths.join(' ').indexOf('/mnt/hd_A') >= 0 || rotulos.join(' ').indexOf('hd_A') >= 0)) return Number(parts[i].pct);
          if (want === 'hd_B' && (paths.join(' ').indexOf('/mnt/hd_B') >= 0 || rotulos.join(' ').indexOf('hd_B') >= 0)) return Number(parts[i].pct);
        }
        return null;
      }
      var gauges =
        '<div class="gf-gauges">' +
          healthDashGaugeCard('root /', partPct('/') != null ? partPct('/') : diskPct) +
          healthDashGaugeCard('hd_A', partPct('hd_A')) +
          healthDashGaugeCard('hd_B', partPct('hd_B')) +
          healthDashGaugeCard('CPU', cpuPct) +
          healthDashGaugeCard('RAM', ramPct) +
          healthDashGaugeCard('Swap', swapPct) +
          healthDashGaugeCard('PostgreSQL', pgPct) +
          healthDashGaugeCard('WireGuard', wgPct, { label: peersAtivos + '/' + peers }) +
          healthDashGaugeCard('Cert A1', certPct, { label: isFinite(certDias) ? (Math.round(certDias) + 'd') : undefined }) +
          healthDashGaugeCard('Backup', backupFresh) +
          healthDashGaugeCard('SMTP', smtpHealth, { label: isFinite(smtpMs) ? (Math.round(smtpMs) + 'ms') : undefined }) +
          healthDashGaugeCard('Nginx', nginxUp ? 100 : 0, { label: nginxUp ? 'UP' : 'DOWN', alert: !nginxUp }) +
          healthDashGaugeCard('WhatsApp', waOk ? 100 : 35, { label: waOk ? 'ON' : 'OFF', alert: !waOk }) +
          healthDashGaugeCard('Containers', ((containers.metricas || {}).ativos != null) ? Math.min(100, (Number((containers.metricas || {}).ativos) || 0) * 50) : null, {
            label: String((containers.metricas || {}).ativos != null ? (containers.metricas || {}).ativos : 'N/A'),
            na: (containers.metricas || {}).ativos == null,
            alert: (containers.metricas || {}).ativos == null
          }) +
        '</div>';

      var bottom =
        '<div class="gf-bottom">' +
          '<div class="gf-panel"><div class="gf-panel-title">Hypervisor CPU</div><div class="gf-panel-chart">' + healthDashSparkSvg(healthDashSeries(hist, 'cpu'), '#FFD700') + '</div><div class="gf-legend"><span>current ' + healthDashEsc(isFinite(cpuPct) ? cpuPct + '%' : '-') + '</span><span>cores ' + healthDashEsc(cores || '-') + '</span></div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Hypervisor Memory</div><div class="gf-panel-chart">' + healthDashSparkSvg(healthDashSeries(hist, 'ram'), '#7CFC00') + '</div><div class="gf-legend"><span>current ' + healthDashEsc(isFinite(ramPct) ? ramPct + '%' : '-') + '</span><span>used ' + healthDashEsc(healthDashFormatBytes(ramUsed, 2)) + '</span></div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Hypervisor Net Usage</div><div class="gf-panel-chart">' + healthDashSparkSvg(netSeries, '#FFD700') + '</div><div class="gf-legend"><span>RX ' + healthDashEsc(healthDashFormatBytes(rx, 1)) + '</span><span>TX ' + healthDashEsc(healthDashFormatBytes(tx, 1)) + '</span></div></div>' +
          '<div class="gf-panel"><div class="gf-panel-title">Postgres / SMTP latency</div><div class="gf-panel-chart">' + healthDashSparkSvg(healthDashSeries(hist, 'smtp'), '#7CFC00') + '</div><div class="gf-legend"><span>pg ' + healthDashEsc((pg.metricas || {}).latencia_ms != null ? (pg.metricas || {}).latencia_ms + ' ms' : '-') + '</span><span>smtp ' + healthDashEsc(isFinite(smtpMs) ? smtpMs + ' ms' : '-') + '</span></div></div>' +
        '</div>';

      grid.innerHTML =
        healthDashSection('Cluster Status', cluster) +
        healthDashSection('Datastore Status', gauges) +
        healthDashSection('Hypervisor Status', bottom);

      if (typeof atualizarBadgeHealthDashboard === 'function') {
        try { atualizarBadgeHealthDashboard(data); } catch (eBadge) {}
      }
    }
    /* HEALTH_DASH_CHARTS_V3_JS_END */
