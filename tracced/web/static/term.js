/* Live terminal for a queued/running analysis: polls /job/<id>.state.json, types the log lines,
   shows the phase and a thin progress bar; reloads the page when the result is ready. No libraries. */
(function () {
  const t = document.getElementById('term'); if (!t) return;
  const id = t.dataset.id, lines = t.querySelector('.term-lines'), body = t.querySelector('.term-body');
  const fill = t.querySelector('.term-fill'), phase = t.querySelector('.term-phase'), clock = t.querySelector('.term-clock');
  const foot = t.querySelector('.term-foot'), errEl = t.querySelector('.term-err'), sym = t.querySelector('.term-sym');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let since = 0, elapsed0 = 0, tick0 = Date.now(), failures = 0, stopped = false;
  const p2 = n => String(n).padStart(2, '0'), esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  const hi = s => esc(s).replace(/(^|[\s(≈$×])(\d[\d,]*(?:\.\d+)?)(?=[\s%,;:)×]|$)/g, '$1<b>$2</b>');
  const LABEL = { queued: () => 'queued', token: () => 'token', trades: p => 'trades ' + p.done + (p.total ? ' of ≈' + p.total : ''),
                  wallets: p => 'wallets ' + p.done + '/' + p.total, tags: () => 'tags', done: () => 'done', error: () => 'error' };
  function add(text, i, cls) {
    const stick = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    const row = document.createElement('div'); row.className = 'tl' + (cls ? ' ' + cls : '');
    row.style.setProperty('--i', reduced ? 0 : Math.min(i, 8));
    const d = new Date(); row.innerHTML = '<span class="ts">' + p2(d.getHours()) + ':' + p2(d.getMinutes()) + ':' + p2(d.getSeconds()) + '</span><span class="tx">' + hi(text) + '</span>';
    lines.appendChild(row); if (stick) body.scrollTop = body.scrollHeight;
  }
  function tickClock() { if (stopped) return; const s = Math.max(0, Math.floor((elapsed0 + Date.now() - tick0) / 1000)); clock.textContent = p2(Math.floor(s / 60)) + ':' + p2(s % 60); }
  async function poll() {
    let d;
    try {
      const r = await fetch('/job/' + id + '.state.json?since=' + since, { cache: 'no-store', credentials: 'same-origin' });
      if (!r.ok || !(r.headers.get('content-type') || '').includes('json')) throw new Error(r.status);
      d = await r.json(); failures = 0;
    } catch (e) { if (++failures === 1) add('… connection lost, retrying', 0, 'dim'); setTimeout(poll, 3000); return; }
    elapsed0 = Math.max(0, d.now_ms - d.started_ms); tick0 = Date.now(); tickClock();
    if (d.symbol) sym.textContent = d.symbol;
    d.log.forEach((l, i) => add(l, i, /warning|unavailable|failed/i.test(l) ? 'dim' : '')); since = d.n_lines;
    const p = d.progress || {}; phase.textContent = (LABEL[p.phase] || (() => p.phase || ''))(p);
    const pct = p.total ? Math.min(100, Math.round(100 * p.done / p.total)) : (d.status === 'done' ? 100 : 0);
    fill.style.width = pct + '%'; t.classList.toggle('indeterminate', !p.total && d.status === 'running');
    t.classList.remove('queued', 'running', 'done', 'error'); t.classList.add(d.status);
    if (d.status === 'done') { stopped = true; add('done — opening the result', 0, 'dim'); setTimeout(() => location.reload(), reduced ? 0 : 500); return; }
    if (d.status === 'error') { stopped = true; errEl.textContent = d.error || 'The analysis failed.'; foot.hidden = false; return; }
    setTimeout(poll, document.hidden ? 3000 : 1000);
  }
  setInterval(tickClock, 1000); poll();
})();
