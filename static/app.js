/* Chat client: sidebar, streaming answers, charts and tables. No build step. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const els = {
    shell: $('shell'), list: $('chat-list'), thread: $('thread'), scroll: $('scroll'), empty: $('empty'),
    input: $('input'), send: $('send'), sendIcon: $('send-icon'), composer: $('composer'), title: $('conv-title'),
    chip: $('portfolio-chip'), progChip: $('program-chip'),
  };
  const ICON_SEND = '<path d="M12 19V5M5 12l7-7 7 7"/>';
  const ICON_STOP = '<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none"/>';
  const PALETTE = ['#c96442', '#3f6fb5', '#4f9a6a', '#d19a2a', '#8a67b8', '#3a9fa6', '#b8577f', '#7b776d'];
  const WORKING = {
    search_columns: 'Looking through the columns…', run_sql: 'Querying the data…',
    create_chart: 'Building a chart…', show_table: 'Preparing a table…',
  };

  let me = null;
  let convs = [];
  let currentId = null;
  let controller = null;   // AbortController while a reply is streaming

  marked.setOptions({ gfm: true, breaks: false });
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  const md = (text) => DOMPurify.sanitize(marked.parse(text || ''));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const h = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  async function api(path, opts = {}) {
    const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
    if (r.status === 401) { location.href = '/login'; throw new Error('signed out'); }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    return r.json();
  }

  // ------------------------------------------------------------ number formats
  function fmt(v, format = 'number', compact = false) {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v !== 'number') return String(v);
    const abs = Math.abs(v);
    if (format === 'percent') return (v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 }) + '%';
    if (format === 'currency') {
      return v.toLocaleString(undefined, {
        style: 'currency', currency: 'USD',
        notation: compact && abs >= 1e4 ? 'compact' : 'standard',
        minimumFractionDigits: 0,
        maximumFractionDigits: compact ? (abs >= 1e4 ? 1 : 0) : abs >= 100 ? 0 : 2,
      });
    }
    if (format === 'ratio') return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
    return v.toLocaleString(undefined, {
      notation: compact && abs >= 1e4 ? 'compact' : 'standard',
      maximumFractionDigits: abs >= 1e5 ? 0 : abs >= 1000 ? 1 : abs >= 1 ? 2 : 4,   // keeps 100.65 (an MLR %) at two decimals
    });
  }
  const trunc = (s, n) => { s = String(s ?? ''); return s.length > n ? s.slice(0, n - 1) + '…' : s; };

  // ------------------------------------------------------------------ sidebar
  function groupLabel(ts) {
    const d = new Date(ts * 1000), now = new Date();
    const days = (new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5;
    if (days < 1) return 'Today';
    if (days < 2) return 'Yesterday';
    if (days < 7) return 'Previous 7 days';
    if (days < 30) return 'Previous 30 days';
    return 'Older';
  }

  function renderSidebar() {
    els.list.innerHTML = '';
    let last = null;
    for (const c of convs) {
      const g = groupLabel(c.updated_at);
      if (g !== last) { els.list.append(h(`<div class="chat-group">${g}</div>`)); last = g; }
      const badge = c.program && me.programs.length > 1 ? `<span class="mini-tag">${esc(c.program)}</span>` : '';
      const item = h(`<div class="chat-item${c.id === currentId ? ' active' : ''}">
        <a href="#/c/${c.id}" title="${esc(c.title)}">${badge}${esc(c.title)}</a>
        <button class="menu-btn" aria-label="Chat options">
          <svg class="icon" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>
        </button></div>`);
      item.querySelector('.menu-btn').addEventListener('click', (e) => { e.stopPropagation(); openMenu(item, c); });
      item.querySelector('a').addEventListener('click', () => els.shell.classList.remove('nav-open'));
      els.list.append(item);
    }
  }

  function closeMenus() { document.querySelectorAll('.chat-menu').forEach((m) => m.remove()); }
  function openMenu(item, c) {
    closeMenus();
    const m = h(`<div class="chat-menu">
      <button data-a="rename"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>Rename</button>
      <button data-a="delete" class="danger"><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>Delete</button></div>`);
    m.addEventListener('click', async (e) => {
      const a = e.target.closest('button')?.dataset.a;
      closeMenus();
      if (a === 'rename') {
        const t = prompt('Rename chat', c.title);
        if (t && t.trim()) { await api(`/api/conversations/${c.id}`, { method: 'PATCH', body: JSON.stringify({ title: t.trim() }) }); await loadConvs(); if (c.id === currentId) els.title.textContent = t.trim(); }
      } else if (a === 'delete') {
        if (!confirm('Delete this chat?')) return;
        await api(`/api/conversations/${c.id}`, { method: 'DELETE' });
        if (c.id === currentId) location.hash = '';
        await loadConvs();
      }
    });
    item.append(m);
  }
  document.addEventListener('click', closeMenus);

  async function loadConvs() { convs = await api('/api/conversations'); renderSidebar(); }

  // -------------------------------------------------------------- empty state
  let pendingProgram = null;   // dataset chosen for the next new chat
  const DB_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>';

  function programById(id) { return me.programs.find((p) => p.id === id) || null; }

  function showEmpty() {
    els.thread.innerHTML = '';
    els.empty.hidden = false;
    els.title.textContent = '';
    const hr = new Date().getHours();
    const part = hr < 12 ? 'Good morning' : hr < 17 ? 'Good afternoon' : 'Good evening';
    $('greeting').textContent = `${part}, ${me.user.display_name.split(' ')[0]}`;
    if (me.programs.length === 1) pendingProgram = me.programs[0].id;
    renderPicker();
  }

  function renderPicker() {
    const picker = $('program-picker');
    const multi = me.programs.length > 1;
    picker.hidden = !multi;
    if (multi) {
      picker.innerHTML = '<div class="picker-title">Which dataset do you want to work with?</div><div class="picker-cards"></div>';
      const cards = picker.querySelector('.picker-cards');
      for (const p of me.programs) {
        const card = h(`<button class="program-card${p.id === pendingProgram ? ' selected' : ''}" data-id="${esc(p.id)}">
          <span class="program-tag">${esc(p.id)}</span>
          <span class="program-label">${esc(p.label)}</span>
          <span class="program-desc">${esc(p.description)}</span>
          <span class="program-meta">${p.rows.toLocaleString()} TINs · ${p.columns.toLocaleString()} columns</span>
        </button>`);
        card.addEventListener('click', () => { pendingProgram = p.id; renderPicker(); els.input.focus(); });
        cards.append(card);
      }
    }
    const prog = programById(pendingProgram);
    const chip = $('data-chip');
    chip.hidden = !prog;
    if (prog) chip.innerHTML = `${DB_ICON} ${esc(prog.sources.join(', '))} · ${prog.rows.toLocaleString()} rows · ${prog.columns.toLocaleString()} columns`;
    const box = $('suggestions');
    box.innerHTML = '';
    for (const q of (prog ? prog.suggestions : [])) {
      const b = h(`<button class="suggestion">${esc(q)}</button>`);
      b.addEventListener('click', () => { els.input.value = q; sendMessage(); });
      box.append(b);
    }
    box.hidden = !prog || !prog.suggestions.length;
    els.input.disabled = !prog;
    els.input.placeholder = prog ? `Ask about the ${prog.label} data…` : 'Choose a dataset above to start';
    if (!controller) els.send.disabled = !prog || !els.input.value.trim();
    renderState({ program: prog ? prog.id : null });
  }

  // ---------------------------------------------------------------- rendering
  function userEl(text) { return h(`<div class="msg-user"><div class="bubble">${esc(text)}</div></div>`); }

  function blockEl(b) {
    if (b.type === 'text') { const d = h('<div class="md"></div>'); d.innerHTML = md(b.text); return d; }
    if (b.type === 'tool') return toolEl(b);
    if (b.type === 'chart') return chartEl(b);
    if (b.type === 'table') return tableEl(b);
    if (b.type === 'error') return h(`<div class="err">${esc(b.text)}</div>`);
    if (b.type === 'usage') return h(`<div class="usage-line">≈ ${b.tokens.toLocaleString()} tokens · ${money(b.cost_usd)}${b.unpriced ? ' (rate not configured for this model)' : ''} · ${b.calls} model call${b.calls === 1 ? '' : 's'}</div>`);
    return document.createTextNode('');
  }

  function toolEl(b) {
    const icon = b.ok === false
      ? '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>'
      : b.name === 'search_columns'
        ? '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>'
        : '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></svg>';
    const body = b.sql ? `<pre>${esc(b.sql)}</pre>` : '';
    const chev = body ? '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="m9 6 6 6-6 6"/></svg>' : '';
    return h(`<details class="tool${b.ok === false ? ' fail' : ''}"><summary>${icon}<span class="lbl">${esc(b.label)}</span>${b.detail ? `<span class="det">· ${esc(trunc(b.detail, 90))}</span>` : ''}${chev}</summary>${body}</details>`);
  }

  const ICON_CODE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></svg>';
  const ICON_DL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>';

  function cardShell(title, sub, actions) {
    const card = h(`<div class="card"><div class="card-head"><div class="card-title">${esc(title)}${sub ? `<div class="card-sub">${esc(sub)}</div>` : ''}</div><div class="card-actions"></div></div></div>`);
    const bar = card.querySelector('.card-actions');
    for (const [icon, label, fn] of actions) {
      const btn = h(`<button title="${label}" aria-label="${label}">${icon}</button>`);
      btn.addEventListener('click', fn);
      bar.append(btn);
    }
    return card;
  }

  function toggleSql(card, sql) {
    const ex = card.querySelector('pre.sql');
    if (ex) { ex.remove(); return; }
    card.append(h(`<pre class="sql">${esc(sql)}</pre>`));
  }

  function download(name, blob) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  const fileSafe = (s) => (s || 'export').replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '_').slice(0, 60) || 'export';

  // ------------------------------------------------------------------- charts
  const bgPlugin = { id: 'bg', beforeDraw(chart) { const c = chart.ctx; c.save(); c.fillStyle = css('--panel'); c.fillRect(0, 0, chart.width, chart.height); c.restore(); } };

  function chartEl(b) {
    let chart;
    const sub = b.truncated ? 'Showing the first rows of a larger result' : '';
    const card = cardShell(b.title, sub, [
      ...(b.sql ? [[ICON_CODE, 'Show SQL', () => toggleSql(card, b.sql)]] : []),
      [ICON_DL, 'Download PNG', () => chart && chart.canvas.toBlob((bl) => download(fileSafe(b.title) + '.png', bl))],
    ]);
    const box = h('<div class="chart-box"><canvas></canvas></div>');
    const horizontal = b.chart_type === 'horizontal_bar';
    if (horizontal) box.style.height = Math.max(300, Math.min(900, b.labels.length * 26 + 80)) + 'px';
    card.append(box);
    requestAnimationFrame(() => { chart = drawChart(box.querySelector('canvas'), b); });
    return card;
  }

  function drawChart(canvas, b) {
    const text = css('--muted'), grid = css('--border'), panel = css('--panel');
    const type = b.chart_type;
    const isPie = type === 'pie' || type === 'doughnut';
    const horizontal = type === 'horizontal_bar';
    const stacked = type === 'stacked_bar';
    const f = b.value_format || 'number';
    const multi = b.datasets.length > 1;

    const datasets = b.datasets.map((d, i) => {
      const color = PALETTE[i % PALETTE.length];
      const base = { label: d.label, data: d.data };
      if (isPie) return { ...base, backgroundColor: d.data.map((_, j) => PALETTE[j % PALETTE.length]), borderColor: panel, borderWidth: 2 };
      if (type === 'line' || type === 'area') return { ...base, borderColor: color, backgroundColor: color + '26', fill: type === 'area', tension: .25, pointRadius: d.data.length > 40 ? 0 : 3, borderWidth: 2 };
      if (type === 'scatter') return { ...base, backgroundColor: color + 'b3', borderColor: color, pointRadius: d.data.length > 1000 ? 2 : 4, pointHoverRadius: 6 };
      return { ...base, backgroundColor: color, borderRadius: 4, maxBarThickness: 48 };
    });

    const valueAxis = { grid: { color: grid }, border: { display: false }, ticks: { color: text, maxRotation: 0, callback: (v) => fmt(v, f, true) },
      title: { display: !!b.y_label, text: b.y_label, color: text } };
    const labelLen = canvas.parentElement.clientWidth < 520 ? 15 : 24;
    const catAxis = { grid: { display: false }, ticks: { color: text, autoSkip: true, maxRotation: 45, callback(v) { return trunc(this.getLabelForValue(v), labelLen); } },
      title: { display: !!b.x_label, text: b.x_label, color: text } };

    let scales = {};
    if (type === 'scatter') {
      scales = { x: { ...valueAxis, ticks: { color: text, callback: (v) => fmt(v, 'number', true) }, title: { display: true, text: b.x_label, color: text } }, y: valueAxis };
    } else if (!isPie) {
      scales = horizontal
        ? { x: { ...valueAxis, stacked, title: { display: !!b.y_label, text: b.y_label, color: text } }, y: { ...catAxis, stacked, title: { display: false } } }
        : { x: { ...catAxis, stacked }, y: { ...valueAxis, stacked } };
    }

    return new Chart(canvas, {
      type: type === 'horizontal_bar' || type === 'stacked_bar' ? 'bar' : type === 'area' ? 'line' : type,
      data: { labels: b.labels, datasets },
      plugins: [bgPlugin],
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? 'y' : 'x',
        animation: { duration: 350 },
        interaction: type === 'scatter' ? { mode: 'nearest', intersect: true } : { mode: 'index', intersect: false },
        scales,
        plugins: {
          legend: { display: multi || isPie, position: isPie ? 'right' : 'top', labels: { color: text, boxWidth: 12, usePointStyle: true } },
          tooltip: {
            callbacks: {
              label(ctx) {
                if (type === 'scatter') {
                  const p = ctx.raw;
                  return `${p.label ? p.label + ': ' : ''}${fmt(p.x)} , ${fmt(p.y, f)}`;
                }
                const v = isPie ? ctx.raw : ctx.parsed[horizontal ? 'x' : 'y'];
                return `${ctx.dataset.label}: ${fmt(v, f)}`;
              },
            },
          },
        },
      },
    });
  }

  // ------------------------------------------------------------------- tables
  function toCsv(cols, rows) {
    const q = (v) => { if (v === null || v === undefined) return ''; const s = String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
    return [cols.map(q).join(','), ...rows.map((r) => r.map(q).join(','))].join('\r\n');
  }

  function tableEl(b) {
    const PAGE = 200;
    let rows = b.rows.slice();
    let shown = PAGE;
    let sort = { i: -1, dir: 1 };
    const numeric = b.columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] === null || typeof r[i] === 'number'));
    const card = cardShell(b.title, b.subtitle || `${b.rows.length.toLocaleString()}${b.truncated ? '+' : ''} rows`, [
      ...(b.sql ? [[ICON_CODE, 'Show SQL', () => toggleSql(card, b.sql)]] : []),
      [ICON_DL, 'Download CSV', () => download(fileSafe(b.title) + '.csv', new Blob(['﻿' + toCsv(b.columns, rows)], { type: 'text/csv' }))],
    ]);
    const wrap = h('<div class="table-wrap"><table class="data-table"><thead><tr></tr></thead><tbody></tbody></table></div>');
    const foot = h('<div class="table-foot"><span></span></div>');
    const headRow = wrap.querySelector('tr'), body = wrap.querySelector('tbody');
    b.columns.forEach((c, i) => {
      const th = h(`<th class="${numeric[i] ? 'num' : ''}" title="${esc(c)}">${esc(trunc(c, 40))}</th>`);
      th.addEventListener('click', () => {
        sort = { i, dir: sort.i === i ? -sort.dir : (numeric[i] ? -1 : 1) };
        rows.sort((a, z) => {
          const x = a[i], y = z[i];
          if (x === null) return 1; if (y === null) return -1;
          return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
        });
        paint();
      });
      headRow.append(th);
    });
    function paint() {
      body.innerHTML = rows.slice(0, shown).map((r) => `<tr class="${r[0] === 'TOTAL' ? 'total' : ''}">${r.map((v, i) =>
        `<td class="${numeric[i] ? 'num' : ''}" title="${esc(v)}">${esc(numeric[i] ? fmt(v) : v ?? '')}</td>`).join('')}</tr>`).join('');
      const span = foot.querySelector('span');
      span.textContent = `Showing ${Math.min(shown, rows.length).toLocaleString()} of ${rows.length.toLocaleString()}${b.truncated ? ' (result capped)' : ''}`;
      foot.querySelector('.link-btn')?.remove();
      if (shown < rows.length) {
        const more = h('<button class="link-btn">Show more</button>');
        more.addEventListener('click', () => { shown += PAGE * 5; paint(); });
        foot.append(more);
      }
    }
    paint();
    card.append(wrap, foot);
    return card;
  }

  // ------------------------------------------------------------ conversation
  function renderState(state) {
    const prog = state && state.program ? programById(state.program) : null;
    els.progChip.hidden = !prog;
    if (prog) { els.progChip.textContent = prog.id; els.progChip.title = prog.label; }
    const tins = (state && state.portfolio) || [];
    if (!tins.length) { els.chip.hidden = true; return; }
    els.chip.hidden = false;
    els.chip.textContent = `Portfolio: ${tins.length} TIN${tins.length === 1 ? '' : 's'}` +
      (state.target_mlr ? ` · target MLR ${(state.target_mlr * 100).toFixed(0)}%` : '');
    els.chip.title = tins.join(', ');
  }

  function renderConversation(conv) {
    els.empty.hidden = true;
    els.thread.innerHTML = '';
    els.title.textContent = conv.title;
    renderState(conv.state);
    els.input.disabled = false;
    const prog = conv.state && programById(conv.state.program);
    els.input.placeholder = prog ? `Ask about the ${prog.label} data…` : 'Ask a question about your data…';
    for (const m of conv.messages) {
      if (m.role === 'user') els.thread.append(userEl(m.text));
      else {
        const wrap = h('<div class="msg-assistant"></div>');
        m.blocks.forEach((b) => wrap.append(blockEl(b)));
        els.thread.append(wrap);
      }
    }
    requestAnimationFrame(() => { els.scroll.scrollTop = els.scroll.scrollHeight; });
  }

  async function route() {
    if (controller) return;
    const m = location.hash.match(/^#\/c\/([0-9a-f]+)/);
    currentId = m ? m[1] : null;
    renderSidebar();
    if (!currentId) { showEmpty(); els.input.focus(); return; }
    try { renderConversation(await api(`/api/conversations/${currentId}`)); }
    catch { location.hash = ''; }
  }
  window.addEventListener('hashchange', route);

  // ----------------------------------------------------------------- sending
  const nearBottom = () => els.scroll.scrollHeight - els.scroll.scrollTop - els.scroll.clientHeight < 120;
  const stick = (was) => { if (was) els.scroll.scrollTop = els.scroll.scrollHeight; };

  function setStreaming(on) {
    els.sendIcon.innerHTML = on ? ICON_STOP : ICON_SEND;
    els.send.setAttribute('aria-label', on ? 'Stop' : 'Send');
    els.send.disabled = on ? false : !els.input.value.trim();
  }

  async function sendMessage() {
    const text = els.input.value.trim();
    if (!text || controller) return;
    if (!currentId && !pendingProgram) { $('program-picker').scrollIntoView({ behavior: 'smooth' }); return; }
    els.input.value = ''; autosize();
    els.empty.hidden = true;
    els.thread.append(userEl(text));
    const wrap = h('<div class="msg-assistant"></div>');
    els.thread.append(wrap);
    let working = h('<div class="dots"><i></i><i></i><i></i></div>');
    wrap.append(working);
    els.scroll.scrollTop = els.scroll.scrollHeight;

    let textEl = null, textBuf = '', raf = 0;
    const flush = () => { raf = 0; if (textEl) { const was = nearBottom(); textEl.innerHTML = md(textBuf); stick(was); } };
    const clearWorking = () => { working?.remove(); working = null; };

    controller = new AbortController();
    setStreaming(true);
    try {
      const r = await fetch('/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ message: text, conversation_id: currentId, program: currentId ? undefined : pendingProgram }),
      });
      if (r.status === 401) { location.href = '/login'; return; }
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);

      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
          if (!chunk.startsWith('data: ')) continue;
          const ev = JSON.parse(chunk.slice(6));
          const was = nearBottom();
          if (ev.type === 'conversation') {
            if (currentId !== ev.id) {
              currentId = ev.id;
              history.replaceState(null, '', `#/c/${ev.id}`);
              els.title.textContent = ev.title;
              convs.unshift({ id: ev.id, title: ev.title, updated_at: Date.now() / 1000, program: ev.program });
              renderSidebar();
              renderState({ program: ev.program });
            }
          } else if (ev.type === 'text') {
            clearWorking();
            if (!textEl) { textEl = h('<div class="md"></div>'); wrap.append(textEl); textBuf = ''; }
            textBuf += ev.text;
            if (!raf) raf = requestAnimationFrame(flush);
          } else if (ev.type === 'tool_pending') {
            if (raf) { cancelAnimationFrame(raf); flush(); }
            textEl = null;
            clearWorking();
            working = h(`<div class="working"><span class="spinner"></span>${esc(WORKING[ev.name] || 'Working…')}</div>`);
            wrap.append(working);
          } else if (ev.type === 'block') {
            const w = working; working = null;
            const el = blockEl(ev.block);
            if (w) w.replaceWith(el); else wrap.append(el);
            working = h('<div class="dots"><i></i><i></i><i></i></div>');
            wrap.append(working);
          } else if (ev.type === 'state') {
            renderState(ev.state);
          } else if (ev.type === 'error') {
            clearWorking();
            wrap.append(h(`<div class="err">${esc(ev.message)}</div>`));
          }
          stick(was);
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') wrap.append(h(`<div class="err">${esc(e.message || 'Request failed')}</div>`));
    } finally {
      if (raf) { cancelAnimationFrame(raf); flush(); }
      clearWorking();
      controller = null;
      setStreaming(false);
      loadConvs().catch(() => {});
      refreshSpend();
    }
  }

  // ------------------------------------------------------------------ usage
  function money(v) {
    if (v === null || v === undefined) return '—';
    if (v < 0.01 && v > 0) return '<$0.01';
    return v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
  }
  const tok = (n) => (n || 0).toLocaleString();

  async function refreshSpend() {
    try {
      const u = await api(`/api/usage${currentId ? `?conversation_id=${currentId}` : ''}`);
      lastUsage = u;
      const p = u.periods;
      $('spend').textContent = `${money(p.month.cost_usd)} this month · ${money(p.all_time.cost_usd)} all time`;
    } catch { /* non-critical */ }
  }
  let lastUsage = null;

  function kpi(label, s) {
    return `<div class="kpi"><div class="k-label">${esc(label)}</div><div class="k-value">${money(s.cost_usd)}</div><div class="k-sub">${tok(s.total_tokens)} tokens · ${s.requests} call${s.requests === 1 ? '' : 's'}</div></div>`;
  }
  function usageTable(cols, rows) {
    return `<table class="usage-table"><thead><tr>${cols.map((c) => `<th class="${c.num ? 'num' : ''}">${esc(c.label)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td class="${c.num ? 'num' : ''} ${c.ell ? 'ell' : ''}" title="${esc(r[c.key])}">${c.fmt ? c.fmt(r[c.key]) : esc(r[c.key] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }

  async function openUsage() {
    $('usage-modal').hidden = false;
    $('usage-body').innerHTML = '<div class="working"><span class="spinner"></span>Loading…</div>';
    await refreshSpend();
    const u = lastUsage;
    if (!u) { $('usage-body').textContent = 'Could not load usage.'; return; }
    const p = u.periods;
    let html = '<h3>Your spend</h3><div class="kpis">';
    if (p.this_chat) html += kpi('This chat', p.this_chat);
    html += kpi('Today', p.today) + kpi('This month', p.month) + kpi('All time', p.all_time) + '</div>';
    const a = p.all_time;
    html += `<h3>Token breakdown (all time)</h3>${usageTable(
      [{ key: 'k', label: 'Type' }, { key: 'v', label: 'Tokens', num: true, fmt: tok }],
      [{ k: 'Input (uncached)', v: a.input_tokens }, { k: 'Cache reads', v: a.cache_read_tokens }, { k: 'Cache writes', v: a.cache_write_tokens }, { k: 'Output', v: a.output_tokens }])}`;
    if (u.by_model.length) html += `<h3>By model</h3>${usageTable(
      [{ key: 'model', label: 'Model' }, { key: 'provider', label: 'Provider' }, { key: 'requests', label: 'Calls', num: true, fmt: tok }, { key: 'total_tokens', label: 'Tokens', num: true, fmt: tok }, { key: 'cost_usd', label: 'Cost', num: true, fmt: money }], u.by_model)}`;
    if (u.recent_chats.length) html += `<h3>Recent chats</h3>${usageTable(
      [{ key: 'title', label: 'Chat', ell: true }, { key: 'requests', label: 'Calls', num: true, fmt: tok }, { key: 'total_tokens', label: 'Tokens', num: true, fmt: tok }, { key: 'cost_usd', label: 'Cost', num: true, fmt: money }],
      u.recent_chats.map((r) => ({ ...r, title: r.title || '(deleted chat)' })))}`;
    if (u.all_users) html += `<h3>All users (admin view)</h3>${usageTable(
      [{ key: 'name', label: 'User', ell: true }, { key: 'today', label: 'Today', num: true, fmt: money }, { key: 'month', label: 'This month', num: true, fmt: money }, { key: 'cost_usd', label: 'All time', num: true, fmt: money }, { key: 'total_tokens', label: 'Tokens', num: true, fmt: tok }],
      u.all_users.map((r) => ({ ...r, name: r.display_name || r.username, today: r.today ? r.today.cost_usd : 0, month: r.month ? r.month.cost_usd : 0 })))}`;
    html += `<h3>Rates used ($ per million tokens)</h3>${usageTable(
      [{ key: 'model', label: 'Model' }, { key: 'input', label: 'Input', num: true }, { key: 'output', label: 'Output', num: true }, { key: 'cache_write', label: 'Cache write', num: true }, { key: 'cache_read', label: 'Cache read', num: true }, { key: 'multiplier', label: '×', num: true }],
      u.rate_card.map((r) => ({ ...r, input: r.input ?? 'n/a', output: r.output ?? 'n/a', cache_write: r.cache_write ?? 'n/a', cache_read: r.cache_read ?? 'n/a' })))}`;
    html += `<div class="fine">${esc(u.note)} App version ${esc(u.app_version || '?')}.</div>`;
    $('usage-body').innerHTML = html;
  }

  // ----------------------------------------------------------------- wiring
  function autosize() { els.input.style.height = 'auto'; els.input.style.height = Math.min(els.input.scrollHeight, 220) + 'px'; }
  els.input.addEventListener('input', () => { autosize(); if (!controller) els.send.disabled = !els.input.value.trim() || els.input.disabled; });
  els.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(); }
  });
  els.composer.addEventListener('submit', (e) => { e.preventDefault(); if (controller) controller.abort(); else sendMessage(); });
  $('new-chat').addEventListener('click', () => { if (controller) return; location.hash = ''; route(); els.shell.classList.remove('nav-open'); });
  $('menu-toggle').addEventListener('click', () => els.shell.classList.add('nav-open'));
  $('scrim').addEventListener('click', () => els.shell.classList.remove('nav-open'));
  $('usage-btn').addEventListener('click', openUsage);
  $('usage-close').addEventListener('click', () => { $('usage-modal').hidden = true; });
  $('usage-modal').addEventListener('click', (e) => { if (e.target.id === 'usage-modal') e.currentTarget.hidden = true; });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('usage-modal').hidden = true; });
  $('logout').addEventListener('click', async () => { await api('/api/logout', { method: 'POST' }).catch(() => {}); location.href = '/login'; });

  (async () => {
    me = await api('/api/me');
    document.title = me.app_name;
    $('brand-name').textContent = me.app_name;
    $('who').textContent = me.user.display_name;
    $('avatar').textContent = (me.user.display_name[0] || '?').toUpperCase();
    await loadConvs();
    route();
    refreshSpend();
  })();
})();
