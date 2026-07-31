/* HEALTH_DASH_CHARTS_V3_JS_BEGIN */
    function healthDashChartColor(st) {
      var s = String(st || '').toLowerCase();
      if (s === 'ok') return '#0d9488';
      if (s === 'aviso') return '#d97706';
      if (s === 'risco') return '#ea580c';
      if (s === 'erro') return '#dc2626';
      return '#64748b';
    }

    function healthDashPolar(cx, cy, r, ang) {
      return { x: cx + r * Math.cos(ang), y: cy + r * Math.sin(ang) };
    }

    function healthDashPieSvg(slices, centerText) {
      var size = 78, cx = 39, cy = 39, r = 30, inner = 18;
      var total = 0;
      (slices || []).forEach(function(sl) { total += Math.max(0, Number(sl.v) || 0); });
      var parts = '';
      if (total <= 0) {
        parts = '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="#e2e8f0"></circle>' +
          '<circle cx="' + cx + '" cy="' + cy + '" r="' + inner + '" fill="#fff"></circle>';
      } else if (slices.length === 1 || (slices.filter(function(s){ return (Number(s.v)||0) > 0; }).length === 1)) {
        var only = slices.filter(function(s){ return (Number(s.v)||0) > 0; })[0] || slices[0];
        parts = '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + (only.color || '#0d9488') + '"></circle>' +
          '<circle cx="' + cx + '" cy="' + cy + '" r="' + inner + '" fill="#fff"></circle>';
      } else {
        var ang = -Math.PI / 2;
        slices.forEach(function(sl) {
          var v = Math.max(0, Number(sl.v) || 0);
          if (v <= 0) return;
          var delta = (v / total) * Math.PI * 2;
          if (delta >= Math.PI * 2 - 0.0001) {
            parts += '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + (sl.color || '#0d9488') + '"></circle>';
            return;
          }
          var a0 = ang;
          var a1 = ang + delta;
          var p0 = healthDashPolar(cx, cy, r, a0);
          var p1 = healthDashPolar(cx, cy, r, a1);
          var large = delta > Math.PI ? 1 : 0;
          parts += '<path d="M ' + cx + ' ' + cy +
            ' L ' + p0.x.toFixed(2) + ' ' + p0.y.toFixed(2) +
            ' A ' + r + ' ' + r + ' 0 ' + large + ' 1 ' + p1.x.toFixed(2) + ' ' + p1.y.toFixed(2) +
            ' Z" fill="' + (sl.color || '#0d9488') + '"></path>';
          ang = a1;
        });
        parts += '<circle cx="' + cx + '" cy="' + cy + '" r="' + inner + '" fill="#fff"></circle>';
      }
      var label = String(centerText == null ? '' : centerText);
      var font = label.length > 4 ? 10 : 12;
      parts += '<text x="' + cx + '" y="' + (cy + 1) + '" text-anchor="middle" dominant-baseline="middle" ' +
        'font-size="' + font + '" font-weight="800" fill="#0f172a">' + label.replace(/</g, '&lt;') + '</text>';
      return '<svg viewBox="0 0 ' + size + ' ' + size + '" aria-hidden="true">' + parts + '</svg>';
    }

    function healthDashDonutPct(pct, color, centerText) {
      var p = Math.max(0, Math.min(100, Number(pct) || 0));
      var rest = Math.max(0.0001, 100 - p);
      return healthDashPieSvg([
        { v: p, color: color || '#0d9488' },
        { v: rest, color: '#e2e8f0' }
      ], centerText != null ? centerText : (Math.round(p) + '%'));
    }

    function healthDashMiniBars(rows) {
      var list = (rows || []).slice(0, 4);
      if (!list.length) return '';
      var max = 0;
      list.forEach(function(r) { max = Math.max(max, Number(r.v) || 0); });
      if (max <= 0) max = 1;
      var y = 8, h = 10, gap = 5, w = 78;
      var parts = '';
      list.forEach(function(r, idx) {
        var val = Math.max(0, Number(r.v) || 0);
        var bw = Math.max(2, (val / max) * (w - 4));
        var yy = y + idx * (h + gap);
        parts += '<rect x="2" y="' + yy + '" width="' + (w - 4) + '" height="' + h + '" rx="3" fill="#e2e8f0"></rect>';
        parts += '<rect x="2" y="' + yy + '" width="' + bw.toFixed(1) + '" height="' + h + '" rx="3" fill="' + (r.color || '#0d9488') + '"></rect>';
      });
      var height = y + list.length * (h + gap);
      return '<svg viewBox="0 0 ' + w + ' ' + height + '" aria-hidden="true">' + parts + '</svg>';
    }

    function healthDashChartForItem(item, st) {
      var met = item.metricas || {};
      var id = String(item.id || '');
      var color = healthDashChartColor(st);

      if (id === 'saude_geral') {
        var slices = [
          { v: Number(met.normais) || 0, color: '#0d9488' },
          { v: Number(met.alertas) || 0, color: '#d97706' },
          { v: Number(met.erros) || 0, color: '#dc2626' },
          { v: Number(met.indisponiveis) || 0, color: '#94a3b8' }
        ];
        var tot = slices.reduce(function(a, b) { return a + b.v; }, 0);
        return healthDashPieSvg(slices, tot ? String(tot) : '-');
      }
      if (id === 'servicos') {
        return healthDashPieSvg([
          { v: Number(met.ativos) || 0, color: '#0d9488' },
          { v: Number(met.inativos) || 0, color: '#f59e0b' },
          { v: Number(met.falha) || 0, color: '#dc2626' }
        ], String(Number(met.ativos) || 0));
      }
      if (id === 'wireguard') {
        var peers = Number(met.peers) || 0;
        var ativos = Number(met.peers_ativos) || 0;
        var inativos = Math.max(0, peers - ativos);
        var pctWg = peers ? Math.round((ativos / peers) * 100) : 0;
        return healthDashPieSvg([
          { v: ativos, color: '#0d9488' },
          { v: inativos, color: '#e2e8f0' }
        ], pctWg + '%');
      }
      if (id === 'containers') {
        return healthDashPieSvg([
          { v: Number(met.ativos) || 0, color: '#0d9488' },
          { v: Number(met.parados) || 0, color: '#f59e0b' },
          { v: Math.max(0, (Number(met.imagens) || 0) - (Number(met.ativos) || 0)), color: '#cbd5e1' }
        ], String(Number(met.ativos) || 0));
      }
      if (id === 'whatsapp') {
        var okWa = met.worker_ativo && met.envio_habilitado;
        return healthDashDonutPct(okWa ? 100 : (met.envio_habilitado ? 45 : 15), okWa ? '#0d9488' : color, okWa ? 'ON' : 'OFF');
      }
      if (id === 'nginx') {
        return healthDashDonutPct(met.ativo ? 100 : 0, met.ativo ? '#0d9488' : '#dc2626', met.ativo ? 'UP' : 'DOWN');
      }
      if (id === 'certificado' && met.dias_restantes != null) {
        var dias = Math.max(0, Number(met.dias_restantes) || 0);
        var pctCert = Math.max(0, Math.min(100, (dias / 365) * 100));
        return healthDashDonutPct(pctCert, color, String(Math.round(dias)) + 'd');
      }
      if (id === 'backup' && met.idade_horas != null) {
        var idade = Math.max(0, Number(met.idade_horas) || 0);
        var pctB = Math.max(0, Math.min(100, 100 - (idade / 24) * 100));
        return healthDashDonutPct(pctB, color, (idade < 10 ? idade.toFixed(1) : Math.round(idade)) + 'h');
      }
      if (id === 'smtp' && met.latencia_ms != null) {
        var lat = Math.max(0, Number(met.latencia_ms) || 0);
        var pctSmtp = Math.max(0, Math.min(100, 100 - (lat / 1000) * 100));
        return healthDashDonutPct(pctSmtp, color, Math.round(lat) + 'ms');
      }
      if (id === 'armazenamento' && Array.isArray(met.diretorios) && met.diretorios.length) {
        var bars = met.diretorios.slice(0, 4).map(function(d, idx) {
          var palette = ['#0d9488', '#0284c7', '#d97706', '#475569'];
          return { v: Number(d.bytes) || 0, color: palette[idx % palette.length] };
        });
        return healthDashMiniBars(bars);
      }
      if (id === 'disco' && Array.isArray(met.particoes) && met.particoes.length > 1) {
        return healthDashPieSvg(met.particoes.slice(0, 4).map(function(p, idx) {
          var palette = ['#0d9488', '#0284c7', '#d97706', '#64748b'];
          return { v: Math.max(0.1, Number(p.pct) || 0), color: palette[idx % palette.length] };
        }), (Math.round(Number(met.barra_pct) || Number(met.pior_pct) || 0)) + '%');
      }
      if (met.barra_pct != null && isFinite(Number(met.barra_pct))) {
        return healthDashDonutPct(Number(met.barra_pct), color);
      }
      if (st === 'ok') return healthDashDonutPct(100, '#0d9488', 'OK');
      if (st === 'aviso') return healthDashDonutPct(66, '#d97706', '!');
      if (st === 'risco') return healthDashDonutPct(80, '#ea580c', '!!');
      if (st === 'erro') return healthDashDonutPct(100, '#dc2626', 'X');
      return healthDashDonutPct(35, '#64748b', 'i');
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
        try { quando = ' | ' + new Date(data.checked_at).toLocaleString('pt-BR'); } catch (eWhen) { quando = ''; }
      }
      if (erros > 0) {
        resumo.className = 'health-dash-summary health-dash-summary--erro';
        resumo.textContent = 'Criticos: ' + erros + ' | alertas: ' + avisos + ' | ok: ' + normais + ' | indisponiveis: ' + indisponiveis + quando;
      } else if (avisos > 0 || !(data && data.ok)) {
        resumo.className = 'health-dash-summary health-dash-summary--warn';
        resumo.textContent = 'Atencao necessaria: ' + avisos + ' alerta(s) | ok: ' + normais + ' | indisponiveis: ' + indisponiveis + quando;
      } else {
        resumo.className = 'health-dash-summary health-dash-summary--ok';
        resumo.textContent = 'Visao geral saudavel - ' + normais + ' verificacoes ok' + quando;
      }
      if (man) man.style.display = 'none';
      grid.innerHTML = '';
      var itens = Array.isArray(data && data.itens) ? data.itens.slice() : [];
      var ordem = ['saude_geral','cpu','memoria','disco','postgres','whatsapp','smtp','nginx','wireguard','containers','servicos','backup','armazenamento','certificado'];
      var map = {};
      itens.forEach(function(it) { map[String(it.id || '')] = it; });
      var ordered = [];
      ordem.forEach(function(id) { if (map[id]) ordered.push(map[id]); });
      itens.forEach(function(it) {
        if (ordem.indexOf(String(it.id || '')) < 0) ordered.push(it);
      });
      ordered.forEach(function(item) {
        var st = String(item.status || 'info').toLowerCase();
        if (['ok','aviso','risco','erro','info'].indexOf(st) < 0) st = 'info';
        var box = document.createElement('div');
        box.className = 'health-dash-item health-dash-item--' + st;
        var chart = document.createElement('div');
        chart.className = 'health-dash-chart';
        chart.innerHTML = healthDashChartForItem(item, st);
        var main = document.createElement('div');
        main.className = 'health-dash-item-main';
        var tit = document.createElement('div');
        tit.className = 'health-dash-item-title';
        tit.textContent = String(item.nome || item.id || 'Item');
        var sum = document.createElement('div');
        sum.className = 'health-dash-item-resumo';
        var _lab = healthDashStatusLabel(st);
        var _r = String(item.resumo || '');
        // Sem escapes de barra no JS: o HTML vive em string Python triple-quote.
        sum.textContent = (/^(OK|Atencao|Risco|Problema|Info)(?![A-Za-z0-9_])/i.test(_r) ? _r : (_lab + ' - ' + _r));
        main.appendChild(tit);
        main.appendChild(sum);
        if (item.detalhe) {
          var det = document.createElement('div');
          det.className = 'health-dash-item-detalhe';
          det.textContent = String(item.detalhe || '').split(String.fromCharCode(10)).slice(0, 2).join(' | ');
          main.appendChild(det);
        }
        var chip = document.createElement('span');
        chip.className = 'health-dash-chip' + (st !== 'ok' ? (' is-' + st) : '');
        chip.textContent = healthDashStatusLabel(st);
        main.appendChild(chip);
        box.appendChild(chart);
        box.appendChild(main);
        grid.appendChild(box);
      });
      if (typeof atualizarBadgeHealthDashboard === 'function') {
        try { atualizarBadgeHealthDashboard(data); } catch (eBadge) {}
      }
    }
    /* HEALTH_DASH_CHARTS_V3_JS_END */
