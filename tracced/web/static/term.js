/* Live terminal for a queued/running analysis: polls /job/<id>.state.json and prints the log one line at a time, the
   way a terminal does — each line types itself out and the next one waits for it (owner, 30.09: ten lines at once
   looked like jerks). When lines pile up the typing speeds up, so the screen is never far behind the run. At the end a
   big DONE and the count, then the result opens. No libraries. */
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
  const BIG = ['██████╗  ██████╗ ███╗   ██╗███████╗',
               '██╔══██╗██╔═══██╗████╗  ██║██╔════╝',
               '██║  ██║██║   ██║██╔██╗ ██║█████╗  ',
               '██║  ██║██║   ██║██║╚██╗██║██╔══╝  ',
               '██████╔╝╚██████╔╝██║ ╚████║███████╗',
               '╚═════╝  ╚═════╝ ╚═╝  ╚═══╝╚══════╝'];
  const queue = [], caret = document.createElement('span'); caret.className = 'caret';
  let busy = false, cur = null;                            // cur: the line being typed, so a hidden tab can finish it at once

  function stamp() {
    const d = new Date(); let u = true; try { u = localStorage.getItem('early:tz') !== 'local'; } catch (e) {}   // same clock as every date on the site
    return p2(u ? d.getUTCHours() : d.getHours()) + ':' + p2(u ? d.getUTCMinutes() : d.getMinutes()) + ':' + p2(d.getSeconds());
  }
  function append(el) {                                     // follows the bottom unless the person scrolled up to read
    const stick = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    lines.appendChild(el); if (stick) body.scrollTop = body.scrollHeight;
  }
  function line(text, cls) {
    const row = document.createElement('div'); row.className = 'tl' + (cls ? ' ' + cls : '');
    row.innerHTML = '<span class="ts">' + stamp() + '</span><span class="tx"></span>';
    append(row);
    return row.querySelector('.tx');
  }
  function add(text, cls) { queue.push({ text, cls }); if (!busy) next(); }
  function next() {
    const it = queue.shift();
    busy = !!it; t.classList.toggle('typing', busy);
    body.setAttribute('aria-busy', String(busy));            // a screen reader waits for whole lines, not every typed letter
    if (!it) return;
    if (it.end) { it.end(); return; }
    const tx = line(it.text, it.cls);
    // a hidden tab, or a pile of lines (a result that finished while the page loaded): the lines at once
    if (reduced || document.hidden || queue.length > 40) { tx.innerHTML = hi(it.text); next(); return; }
    // a line alone types in about a third of a second; with a crowd behind it, in a blink
    const ms = queue.length > 10 ? 60 : queue.length > 4 ? 150 : 320, n = it.text.length, t0 = performance.now();
    const me = cur = { tx, text: it.text, done: false };
    const settle = () => { if (me.done) return; me.done = true; cur = null; tx.innerHTML = hi(it.text); setTimeout(next, queue.length > 4 ? 25 : 110); };
    me.finish = settle;
    (function type(now) {
      if (me.done) return;
      const k = Math.min(n, Math.ceil(n * (now - t0) / ms));
      tx.textContent = it.text.slice(0, k); tx.appendChild(caret);
      if (k < n && !document.hidden) { requestAnimationFrame(type); return; }
      settle();                                             // numbers light up once the line is out
    })(t0);
  }
  // a tab hidden mid-line: frames stop there, so the line ends at once and the rest follow (review)
  document.addEventListener('visibilitychange', () => { if (document.hidden && cur && cur.finish) cur.finish(); });
  function finish(d) {
    // after the last line: DONE in big letters, how many wallets, then the result
    queue.push({ end: () => {
      const pre = document.createElement('pre'); pre.className = 'term-big'; pre.setAttribute('role', 'img'); pre.setAttribute('aria-label', 'Done');
      append(pre);
      const step = reduced || document.hidden ? 0 : 80;
      BIG.forEach((l, i) => setTimeout(() => { const s = document.createElement('span'); s.textContent = l + '\n'; pre.appendChild(s); body.scrollTop = body.scrollHeight; }, i * step));
      setTimeout(() => {
        const tx = line('', 'end');
        tx.innerHTML = (d.found ? '<b>' + Number(d.found).toLocaleString('en-US') + '</b> wallets found · ' : '') + 'opening the result';
        body.scrollTop = body.scrollHeight;
        setTimeout(() => { if (d.open) location.replace(d.open); else location.reload(); }, reduced ? 300 : 1300);
      }, BIG.length * step + 250);
    } });
    if (!busy) next();
  }
  function tickClock() { if (stopped) return; const s = Math.max(0, Math.floor((elapsed0 + Date.now() - tick0) / 1000)); clock.textContent = p2(Math.floor(s / 60)) + ':' + p2(s % 60); }
  async function poll() {
    let d;
    try {
      const r = await fetch('/job/' + id + '.state.json?since=' + since, { cache: 'no-store', credentials: 'same-origin' });
      if (!r.ok || !(r.headers.get('content-type') || '').includes('json')) throw new Error(r.status);
      d = await r.json(); failures = 0;
    } catch (e) {
      if (String(e.message) === '404') { stopped = true; add('this analysis is gone: the server restarted while it ran. Go back and run it again; your day is not spent.', 'dim'); return; }
      if (++failures === 1) add('… connection lost, retrying', 'dim'); setTimeout(poll, 3000); return;
    }
    elapsed0 = Math.max(0, d.now_ms - d.started_ms); tick0 = Date.now(); tickClock();
    if (d.symbol) sym.textContent = d.symbol;
    d.log.forEach(l => add(l, /warning|unavailable|failed/i.test(l) ? 'dim' : '')); since = d.n_lines;
    const p = d.progress || {}; phase.textContent = (LABEL[p.phase] || (() => p.phase || ''))(p);
    const pct = p.total ? Math.min(100, Math.round(100 * p.done / p.total)) : (d.status === 'done' ? 100 : 0);
    fill.style.width = pct + '%'; t.classList.toggle('indeterminate', !p.total && d.status === 'running');
    t.classList.remove('queued', 'running', 'done', 'error'); t.classList.add(d.status);
    if (d.status === 'done') { if (!stopped && window.EarlyUI) EarlyUI.track('analysis-done', { secs: Math.round((elapsed0 + Date.now() - tick0) / 1000) }); stopped = true; finish(d); return; }
    if (d.status === 'error') { if (!stopped && window.EarlyUI) EarlyUI.track('analysis-failed'); stopped = true; errEl.textContent = d.error || 'The analysis failed.'; foot.hidden = false; return; }
    setTimeout(poll, document.hidden ? 3000 : 1000);
  }
  setInterval(tickClock, 1000); poll();
})();
