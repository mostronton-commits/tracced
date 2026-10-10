/* The token's page (owner, 09.10: one page from a token to its wallets). The chart is the control: two clicks mark a
   range and Get wallets appears under the chart. A run fills a line under the chart with its own steps and counts while
   its band glows on the chart; the result arrives below without a reload. The token's analyses are tabs: one result is on
   the page at a time (static/result.js mounts it and unmounts it), the others wait as fetched markup, so switching back
   is instant and a weak computer never runs two. The address follows the tab: /job/<id> is shareable, /token?mint= is
   the bare token. */
(function () {
  const root = document.getElementById('token'); if (!root) return;
  const $ = id => document.getElementById(id);
  const D = root.dataset, mint = D.mint, DEMO = D.demo === '1';
  const MAX_TABS = +D.maxTabs || 3, MAX_HOURS = +D.maxHours || 24, RESET = +D.reset || 0;
  const acct = () => document.documentElement.dataset.acct === '1';
  const TOUCH = !!(window.matchMedia && matchMedia('(pointer: coarse)').matches), VERB = TOUCH ? 'Tap' : 'Click';
  const reduced = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const RAN = 'early:ran:', DKEY = 'early:draft:' + mint;
  const tabsEl = $('tabs'), pick = $('pick'), runEl = $('run'), resEl = $('result'), hintEl = $('charthint');
  const parseJSON = v => { try { return JSON.parse(v || 'null'); } catch (e) { return null; } };
  let tabs = parseJSON(D.tabs) || [];                      // [{id, from, to, label, n, status, deletable, demo}]
  const ACTIVE = parseJSON(D.active), PRESET = parseJSON(D.preset);
  let runsLeft = D.runsLeft === '' ? null : +D.runsLeft;

  // times: the server and the state speak UTC "YYYY-MM-DDTHH:MM"; the fields show the footer's zone
  const pad = n => String(n).padStart(2, '0');
  const fmt = ms => { const d = new Date(ms); return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + 'T' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()); };
  const parse = v => v ? Date.parse(v + ':00Z') : null;
  const inLocal = () => (window.EarlyTZ && EarlyTZ.get()) === 'local';
  const fmtLoc = ms => { const d = new Date(ms); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()); };
  const show = u => (u && inLocal() ? fmtLoc(parse(u)) : (u || ''));
  const keep = v => (v && inLocal() ? fmt(Date.parse(v)) : v);
  const tfmt = ms => (window.EarlyTZ ? EarlyTZ.fmt(ms) : new Date(ms).toISOString().slice(0, 16).replace('T', ' '));
  const dur = m => (m >= 60 ? Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' min' : '') : Math.max(1, m) + ' min');
  function sumText(r) {
    const a = parse(r.from), b = parse(r.to);
    if (!(a && b)) return '';
    const to = tfmt(b), same = tfmt(a).split(', ')[0] === to.split(', ')[0];
    return tfmt(a) + ' → ' + (same ? to.replace(/^.*, /, '') : to) + ' · ' + dur(Math.round((b - a) / 60000));
  }
  const nf = v => Number(v || 0).toLocaleString('en-US');
  const ran = id => { try { return !!localStorage.getItem(RAN + id); } catch (e) { return true; } };

  /* the range being marked: one at a time, kept in the browser until it runs; a demo tab not yet replayed here is one too */
  let draft = parseJSON((() => { try { return localStorage.getItem(DKEY); } catch (e) { return null; } })()) || { from: '', to: '' };
  if (PRESET && PRESET.from && !tabs.some(t => t.from === PRESET.from && t.to === PRESET.to)) draft = { from: PRESET.from, to: PRESET.to };
  if (DEMO) draft = { from: '', to: '' };
  const saveDraft = () => { try { if (draft.demo) return; localStorage.setItem(DKEY, JSON.stringify({ from: draft.from, to: draft.to })); } catch (e) {} };
  let step = draft.from && !draft.to ? 1 : 0;
  let sel = null;                                          // the tab whose result is below the chart
  const tabOf = id => tabs.find(t => t.id === id);
  const taken = () => tabs.filter(t => !t.demo && t.status !== 'error').length;
  const limitMsg = () => MAX_TABS + ' ranges per token is the limit here. ' + (tabs.some(t => t.deletable) ? 'Delete one of yours to add another.' : 'Open one of the analyzed ranges instead.');

  /* ── the chart: every tab's range, the one shown highlighted, the range being marked after them ── */
  const winList = () => tabs.map((t, i) => ({ n: i + 1, label: t.label, from: parse(t.from), to: parse(t.to) }))
    .concat(draft.from && !draft.demo ? [{ n: tabs.length + 1, label: 'New range', from: parse(draft.from), to: parse(draft.to) }] : []);
  const selIndex = () => { if (draft.from && !draft.demo) return tabs.length; const i = tabs.findIndex(t => t.id === sel); return i < 0 ? 0 : i; };
  const ch = EarlyChart($('chart'), { symbol: D.symbol, mint, created: +D.created, now: +D.now, interactive: true,
    windows: winList(), selected: selIndex(),
    onSelect: i => { if (i < tabs.length) openTab(tabs[i].id); },
    onClick: ms => mark(ms) });
  const drawChart = () => ch.setWindows(winList(), selIndex());
  if (!DEMO) $('chart').classList.add('pickable');        // a crosshair, because the canvas is the control
  fetch('/marks.json?mint=' + encodeURIComponent(mint) + (ACTIVE ? '&job=' + encodeURIComponent(ACTIVE.id) : ''))
    .then(r => r.ok ? r.json() : null).then(d => { if (d) ch.setEvents(EarlyUI.marks(d)); }).catch(function () {});

  /* ── marking: the first click is where buying starts, the second where the pump takes off. A result on screen stays
        while a new range is marked; it changes only when the new one runs ── */
  let nudged = 0;
  function mark(ms) {
    if (DEMO) { const t = Date.now(); if (t - nudged > 4000) { nudged = t; EarlyUI.toast('Demo ranges are fixed. Open one of the pumps below, or paste any other token to analyze it.', 6000); } return; }
    if (!draft.from && taken() >= MAX_TABS) { EarlyUI.toast(limitMsg(), 6000); return; }
    if (draft.demo) draft = { from: '', to: '' };
    if (step === 0) { draft = { from: fmt(ms), to: '' }; step = 1; ch.setMarker(ms); EarlyUI.use('range-set', { end: 'from' }); }
    else {
      draft.to = fmt(ms); if (parse(draft.to) <= parse(draft.from)) { const t = draft.from; draft.from = draft.to; draft.to = t; }
      step = 0; ch.setMarker(null); try { localStorage.setItem('early:hinted', '1'); } catch (x) {}
      EarlyUI.use('range-set', { end: 'to' });
    }
    saveDraft(); drawChart(); renderPick(); renderTabs(); hint();
  }
  function clearDraft() { draft = { from: '', to: '' }; step = 0; ch.setMarker(null); saveDraft(); drawChart(); renderPick(); renderTabs(); hint(); }

  /* the chart says what to click while nothing is marked: a label and a cursor clicking twice (owner, 30.09); once any
     range is on the page only the mid-way label stays */
  function hint() {
    const empty = !DEMO && (step === 1 || !(draft.from && draft.to)) && !draft.demo;
    const first = !tabs.length;
    ch.setDemo(!empty || !first ? null : step === 1 && draft.from ? { after: parse(draft.from) } : 'two');
    hintEl.textContent = step === 1 ? 'Now ' + VERB.toLowerCase() + ' where the pump takes off' : VERB + ' where buying starts';
    hintEl.hidden = !empty || (!first && step !== 1) || (sel && step !== 1);
  }

  /* ── the bar under the chart: the marked range, ✎ for exact minutes, Get wallets ── */
  const ptext = $('picktext'), pedit = $('pickedit'), pfrom = $('pfrom'), pto = $('pto'), getw = $('getw');
  let editing = false;
  function renderPick() {
    const set = !!(draft.from && draft.to);
    pick.hidden = !(draft.from || draft.demo);
    if (pick.hidden) return;
    pick.classList.toggle('ready', set);
    pick.style.setProperty('--wc', EarlyChart.SHADES[(draft.demo ? tabs.findIndex(t => t.id === draft.demo) : tabs.length) % EarlyChart.SHADES.length]);
    ptext.textContent = set ? sumText(draft) : tfmt(parse(draft.from)) + ' → … now ' + VERB.toLowerCase() + ' where the pump takes off';
    getw.hidden = !set; $('pickt').hidden = !set || !!draft.demo; $('pickx').hidden = !!draft.demo;
    pedit.hidden = !editing || !set || !!draft.demo;
    if (!pedit.hidden) { if (document.activeElement !== pfrom) pfrom.value = show(draft.from); if (document.activeElement !== pto) pto.value = show(draft.to); }
  }
  $('pickt').addEventListener('click', () => { editing = !editing; renderPick(); if (editing) pfrom.focus(); });
  $('pickx').addEventListener('click', () => { editing = false; clearDraft(); });
  [pfrom, pto].forEach(x => x.addEventListener('input', () => {
    draft[x === pfrom ? 'from' : 'to'] = keep(x.value); saveDraft(); drawChart();
    ptext.textContent = sumText(draft);
  }));

  /* ── Get wallets: the same checks as before, then the run starts and the page stays ── */
  let starting = false;
  async function getWallets() {
    const f0 = parse(draft.from), t0 = parse(draft.to);
    if (!f0 || !t0) { EarlyUI.toast('Mark the range first: ' + VERB.toLowerCase() + ' the chart where buying starts, then where the pump takes off.', 6000); return; }
    if (f0 >= t0) { EarlyUI.toast('From must be earlier than To.'); return; }
    if (t0 - f0 > MAX_HOURS * 3600e3) { EarlyUI.toast('Range up to ' + MAX_HOURS + ' h. Shorten it.'); return; }
    if (!DEMO && acct() && runsLeft === 0 && openLimit(D.limitKind || 'limit')) return;   // nothing left today: say so before the round trip
    if (!DEMO && !acct()) { EarlyWallet.open(() => getWallets(), 'Connect a wallet to get these wallets.'); return; }
    if (starting) return;
    starting = true; getw.disabled = true;
    const rng = { from: draft.from, to: draft.to };          // what is sent is what the tab keeps, whatever the chart does meanwhile
    EarlyUI.track('analyze', { who: acct() ? 'wallet' : 'guest' });
    let r, d = {};
    try {
      r = await fetch('/analyze.json', { method: 'POST', credentials: 'same-origin', body: new URLSearchParams({ mint, from: rng.from, to: rng.to }) });
      try { d = await r.json(); } catch (e) {}
    } catch (e) { starting = false; getw.disabled = false; EarlyUI.toast('Could not reach the server.'); return; }
    starting = false; getw.disabled = false;
    if (r.status === 401) { EarlyWallet.open(() => getWallets(), 'Connect a wallet to get these wallets.'); return; }
    if (!r.ok) { EarlyUI.toast(d.error || 'Could not start the analysis.', 7000); return; }
    if (d.notice) { if (d.notice === 'demo') EarlyUI.toast(D.bounced || 'Demo ranges are fixed.', 6000); else openLimit(d.notice); return; }
    if (!d.ok || !d.id) { EarlyUI.toast('Could not start the analysis.'); return; }
    if (runsLeft && !DEMO && d.status !== 'done') { runsLeft -= 1; noteLeft(); }   // an existing result opens free
    const tabId = d.canon || d.id;                          // a demo replay runs under its own id and opens as the recorded one
    let t = tabOf(tabId);
    if (!t) {
      t = { id: tabId, from: rng.from, to: rng.to, label: '', n: null, status: d.status, deletable: false, demo: false, mine: !!d.mine };
      tabs.push(t); order();
    }
    if (draft.from === rng.from && draft.to === rng.to) { editing = false; draft = { from: '', to: '' }; step = 0; saveDraft(); }
    if (d.status === 'done') { t.status = 'done'; if (DEMO) markRan(tabId); openTab(tabId); return; }
    t.status = 'running'; t.run = d.id;
    openTab(tabId, { fresh: true });
  }
  getw.addEventListener('click', getWallets);
  // tabs in the server's order and names: by where the range starts, Pump 1, 2, 3 (app.py _tabs_for), so a reload
  // shows the same names and colours, and a deleted tab leaves no gap or twin
  function order() {
    if (DEMO) return;
    tabs.sort((a, b) => parse(a.from) - parse(b.from));
    tabs.forEach((t, i) => { t.label = 'Pump ' + (i + 1); });
  }
  function noteLeft() {
    const el = $('picknote'); if (!el || runsLeft == null || DEMO) return;
    el.textContent = runsLeft > 0 ? runsLeft + ' of ' + (D.runsCap || '') + ' left today' : 'None left today · resets at 00:00 UTC';
  }
  function markRan(id) { try { localStorage.setItem(RAN + id, '1'); } catch (e) {} }

  /* ── the run: its own steps and counts fill a line under the chart (owner, 09.10: «бігуча строка»), its band glows on
        the chart; polled every second, every three in a hidden tab; one poll per run, whichever tab is open ── */
  const STEP = ['queued', 'token', 'trades', 'wallets', 'tags', 'done'];
  const runs = new Map();                                    // tab id → its run's live state
  function pctOf(p, status) {
    if (status === 'done') return 100;
    const k = p && p.phase, f = p && p.total ? Math.min(1, (p.done || 0) / p.total) : 0;
    return k === 'token' ? 6 : k === 'trades' ? 8 + 47 * f : k === 'wallets' ? 55 + 37 * f : k === 'tags' ? 95 : 3;
  }
  function phaseText(p, st) {
    if (st.status === 'done') return [st.found != null ? nf(st.found) + ' wallets found' : 'Done', ''];
    const k = p && p.phase;
    if (k === 'token') return ['Reading the token', ''];
    if (k === 'trades') return ['Reading the trades', p.total ? Math.min(99, Math.round(100 * (p.done || 0) / p.total)) + '%' : ''];   // its pages: a share says it plainer
    if (k === 'wallets') return ['Checking where they sold', (p.done || 0) + ' / ' + (p.total || 0) + ' wallets'];
    if (k === 'tags') return ['Tagging the wallets', ''];
    return [st.status === 'queued' ? 'In the queue' : 'Starting', ''];
  }
  function startRun(t) {
    if (runs.has(t.id)) return;
    const st = { id: t.run || t.id, status: t.status, progress: null, t0: Date.now(), el0: 0, timer: 0, fails: 0, found: null };
    runs.set(t.id, st);
    const poll = async () => {
      let d;
      try {
        const r = await fetch('/job/' + encodeURIComponent(st.id) + '.state.json?since=9999999', { cache: 'no-store', credentials: 'same-origin' });
        if (r.status === 404) { finish(t, st, 'error', 'This analysis is gone: the server restarted while it ran. Mark the range again; your day is not spent.'); return; }
        if (!r.ok) throw new Error(r.status);
        d = await r.json(); st.fails = 0;
      } catch (e) { st.timer = setTimeout(poll, ++st.fails > 3 ? 6000 : 3000); return; }
      st.status = d.status; st.progress = d.progress || null; st.el0 = Math.max(0, d.now_ms - d.started_ms); st.t0 = Date.now();
      if (d.status === 'done') { st.found = d.found; finish(t, st, 'done', null, d.open); return; }
      if (d.status === 'error') { finish(t, st, 'error', d.error || 'The analysis failed.'); return; }
      paintRun();
      st.timer = setTimeout(poll, document.hidden ? 3000 : 1000);
    };
    poll();
    paintRun();
  }
  function finish(t, st, status, err, open) {
    clearTimeout(st.timer);
    t.status = status; st.status = status; st.error = err;
    if (err) t.error = err;                                  // the reason stays with the tab after its run line is gone
    if (status === 'done') {
      t.n = st.found; if (DEMO) markRan(t.id);
      if (t.mine) t.deletable = true;
      EarlyUI.track('analysis-done', { secs: Math.round((st.el0 + Date.now() - st.t0) / 1000) });
    } else EarlyUI.track('analysis-failed');
    paintRun(); renderTabs(); runGlow();
    if (sel !== t.id) { runs.delete(t.id); return; }
    // the line fills, says how many, then makes room for the result
    setTimeout(() => {
      runs.delete(t.id);
      if (status === 'done' && sel === t.id) showResult(t, { fresh: true });
      else paintRun();
    }, status === 'done' && !reduced ? 900 : 0);
  }
  let clockT = 0;
  function paintRun() {
    const t = tabOf(sel), st = t && runs.get(t.id);
    const errText = t && t.status === 'error' ? (st && st.error) || t.error || 'The analysis failed.' : '';
    runEl.hidden = !(st || errText);
    if (runEl.hidden) { clearInterval(clockT); clockT = 0; return; }
    runEl.classList.toggle('err', !!errText);
    runEl.style.setProperty('--wc', EarlyChart.SHADES[tabs.indexOf(t) % EarlyChart.SHADES.length]);
    $('runerr').hidden = !errText; $('runerr').textContent = errText;
    if (!st) { $('runphase').textContent = 'The analysis stopped'; $('runcount').textContent = ''; $('runfill').style.width = '0'; return; }
    const p = st.progress, [ph, cnt] = phaseText(p, st), pct = Math.round(pctOf(p, st.status));
    $('runphase').textContent = ph; $('runcount').textContent = cnt;
    $('runfill').style.width = pct + '%'; $('runbar').setAttribute('aria-valuenow', String(pct));
    runEl.classList.toggle('done', st.status === 'done');
    runEl.classList.toggle('indet', !!p && p.phase === 'trades' && !p.total);
    const at = STEP.indexOf(st.status === 'done' ? 'done' : (p && p.phase) || 'queued');
    $('runsteps').querySelectorAll('li').forEach(li => { const k = STEP.indexOf(li.dataset.s); li.classList.toggle('on', k === at); li.classList.toggle('past', k < at); });
    if (!clockT) clockT = setInterval(tickClock, 1000);
    tickClock();
  }
  function tickClock() {
    const t = tabOf(sel), st = t && runs.get(t.id); if (!st || st.status === 'done') return;
    const s = Math.max(0, Math.floor((st.el0 + Date.now() - st.t0) / 1000));
    $('runclock').textContent = pad(Math.floor(s / 60)) + ':' + pad(s % 60);
  }
  // the band of the run on screen glows; the others' runs go on quietly
  const runGlow = () => { const t = tabOf(sel); ch.setRunning(t && runs.has(t.id) && t.status !== 'done' && t.status !== 'error' ? tabs.indexOf(t) : null); };

  /* ── tabs ── */
  function renderTabs() {
    tabsEl.innerHTML = tabs.map((t, i) => {
      const on = t.id === sel, sh = EarlyChart.SHADES[i % EarlyChart.SHADES.length];
      const sub = t.status === 'done' ? (t.n != null ? nf(t.n) + ' wallets' : 'ready') : t.status === 'error' ? 'stopped'
        : (DEMO && !ran(t.id)) ? 'demo' : 'analyzing…';
      const fresh = t.status !== 'done' && t.status !== 'error';
      return '<button type="button" role="tab" class="atab' + (on ? ' on' : '') + (fresh ? ' busy' : '') + (t.status === 'error' ? ' bad' : '') + '" data-id="' + t.id + '" aria-selected="' + on + '" style="--wc:' + sh + '">'
        + '<i class="tdot" aria-hidden="true"></i><b>' + EarlyTags.esc(t.label) + '</b><small>' + sub + '</small>'
        + (t.deletable ? '<span class="tdel" role="button" tabindex="0" title="Delete this analysis — the slot is free again" aria-label="Delete">×</span>' : '') + '</button>';
    }).join('')
      + (DEMO ? '' : '<button type="button" class="atab new' + (draft.from ? ' on' : '') + '" data-new="1"' + (taken() >= MAX_TABS ? ' disabled title="' + EarlyTags.esc(limitMsg()) + '"' : ' title="Mark a new range on the chart"') + '>'
        + '<b>+ New range</b><small>' + (draft.from && draft.to ? dur(Math.round((parse(draft.to) - parse(draft.from)) / 60000)) : VERB.toLowerCase() + ' the chart') + '</small></button>');
    tabsEl.hidden = !tabs.length && !draft.from;
  }
  tabsEl.addEventListener('click', e => {
    const del = e.target.closest('.tdel');
    if (del) { e.stopPropagation(); dropTab(del.closest('.atab').dataset.id, del); return; }
    const b = e.target.closest('.atab'); if (!b) return;
    if (b.dataset.new) { if (taken() >= MAX_TABS) { EarlyUI.toast(limitMsg(), 6000); return; } hintEl.hidden = false; hintEl.textContent = VERB + ' where buying starts'; focusAll(); return; }
    openTab(b.dataset.id);
  });
  function dropTab(id, b) {
    if (!b.dataset.armed) {                                   // an analysis on the server: a second click deletes it for everyone
      b.dataset.armed = '1'; b.textContent = 'Delete?'; b.classList.add('armed');
      setTimeout(() => { if (b.isConnected) { delete b.dataset.armed; b.textContent = '×'; b.classList.remove('armed'); } }, 5000);
      return;
    }
    EarlyWallet.post('/job/' + id + '/delete').then(() => {
      tabs = tabs.filter(t => t.id !== id); frags.delete(id); order();
      if (sel === id) { closeResult(); sel = null; go(null); }
      drawChart(); renderTabs(); runGlow(); paintRun(); EarlyUI.toast('Analysis deleted. The slot is free again.');
    }).catch(x => EarlyUI.toast(x.message));
  }

  /* ── one result on the page: its markup fetched once and kept (three tabs at most), mounted, unmounted ── */
  const frags = new Map();
  let unmount = null, mountedId = null, loadSeq = 0;
  function closeResult() {
    if (unmount) { try { unmount(); } catch (e) {} unmount = null; }
    mountedId = null; resEl.innerHTML = ''; resEl.classList.remove('in');
  }
  function mountHere(id, html, opts) {
    closeResult();
    resEl.innerHTML = html;
    const box = resEl.querySelector('#resultroot');
    if (!box) return;
    mountedId = id;
    resEl.querySelectorAll('.amt[data-usd]').forEach(el => { el.dataset.usdText = el.textContent; });
    unmount = EarlyResult.mount(box, ch);
    if (window.EarlyCur) EarlyCur.apply();
    if (window.EarlyTZ) EarlyTZ.apply();
    resEl.querySelectorAll('[data-count]').forEach(EarlyUI.countUp);
    if (opts && opts.fresh && !reduced) { resEl.classList.remove('in'); void resEl.offsetWidth; resEl.classList.add('in'); }
    const t = tabOf(id); if (t) ch.focus(parse(t.from), parse(t.to), null);
  }
  async function showResult(t, opts) {
    const seq = ++loadSeq;
    paintRun(); runGlow();
    let html = frags.get(t.id);
    if (!html) {
      resEl.classList.add('loading');
      try {
        const r = await fetch('/job/' + encodeURIComponent(t.id) + '/view', { credentials: 'same-origin' });
        if (r.status === 409) { const d = await r.json().catch(() => ({})); t.status = d.status === 'error' ? 'error' : 'running'; t.error = d.error; if (t.status === 'running') startRun(t); renderTabs(); paintRun(); return; }
        if (!r.ok) throw new Error(r.status);
        html = await r.text();
      } catch (e) { if (seq === loadSeq) EarlyUI.toast('Could not load this result. Try again.'); return; }
      finally { resEl.classList.remove('loading'); }
      frags.set(t.id, html);
      if (frags.size > 3) frags.delete(frags.keys().next().value);   // the oldest kept markup goes: memory stays small
    }
    if (seq !== loadSeq || sel !== t.id) return;             // another tab was chosen meanwhile
    mountHere(t.id, html, opts);
  }
  function openTab(id, opts) {
    const t = tabOf(id); if (!t) return;
    const same = sel === id && mountedId === id;
    sel = id; go(id, opts && opts.replace);
    if (DEMO && t.status === 'done' && !ran(id) && !(opts && opts.fresh)) {
      // a recorded pump opens as a range to replay: its run plays once, here, then the result stays open
      closeResult(); draft = { from: t.from, to: t.to, demo: id }; step = 0; renderPick(); renderTabs(); drawChart(); paintRun(); runGlow();
      ch.focus(parse(t.from), parse(t.to), null); return;
    }
    if (draft.demo) draft = { from: '', to: '' };
    renderPick(); renderTabs(); drawChart(); hint();
    if (t.status === 'done') { if (!same) showResult(t, opts); }
    else {
      closeResult();
      if (t.status !== 'error') startRun(t);
      paintRun(); runGlow(); ch.focus(parse(t.from), parse(t.to), null);
    }
    if (opts && opts.fresh) $('chart').scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
  }

  /* ── the address follows the tab ── */
  function go(id, replace) {
    const url = id ? '/job/' + id : '/token?mint=' + mint;
    if (location.pathname + location.search === url) return;
    try { history[replace ? 'replaceState' : 'pushState']({ tab: id }, '', url); } catch (e) {}
    const tf = $('tokenfoot'); if (tf) tf.hidden = !!id;
  }
  addEventListener('popstate', () => {
    const m = location.pathname.match(/^\/job\/([^/]+)$/), id = m ? decodeURIComponent(m[1]) : null;
    if (id && tabOf(id)) openTab(id, { replace: true });
    else { sel = null; closeResult(); renderTabs(); drawChart(); paintRun(); runGlow(); hint(); }
  });

  /* ── a daily cap: a window that says which count ran out and when it resets; the range stays ── */
  const LIMIT = $('limitsheet');
  function openLimit(kind) {
    if (!LIMIT) return false;
    const tx = document.getElementById('limit-texts').content.querySelector('[data-kind="' + (kind || 'limit') + '"]')
      || document.getElementById('limit-texts').content.querySelector('[data-kind="limit"]');
    EarlyUI.track('limit-window', { kind: kind || 'limit' });
    $('limith').textContent = tx.dataset.h; $('limitwhy').textContent = tx.textContent;
    const m = Math.max(1, Math.round((RESET - Date.now()) / 60000));
    const local = new Date().getTimezoneOffset() ? ' (' + new Date(RESET).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' your time)' : '';
    LIMIT.querySelector('[data-reset]').textContent = (m >= 60 ? Math.floor(m / 60) + ' h ' + (m % 60) + ' min' : m + ' min') + local;
    LIMIT.hidden = false; LIMIT.querySelector('.primary').focus();
    return true;
  }
  LIMIT.addEventListener('click', e => { if (e.target === LIMIT || e.target.closest('[data-limit-close]')) LIMIT.hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') LIMIT.hidden = true; });

  function focusAll() {
    const ws = winList().filter(w => w.from && w.to);
    if (ws.length) ch.focus(Math.min(...ws.map(w => w.from)), Math.max(...ws.map(w => w.to)), null);
  }

  /* ── the first paint: /job/<id> opens on its analysis, its result already in the page; /token on the bare token ── */
  if (D.bounced) EarlyUI.toast(D.bounced, 6000);
  if (ACTIVE && !tabOf(ACTIVE.id)) tabs.push({ id: ACTIVE.id, from: ACTIVE.from, to: ACTIVE.to, label: 'Pump ' + (tabs.length + 1), n: null, status: ACTIVE.status, deletable: false, demo: false, error: ACTIVE.error });
  if (ACTIVE) {
    const t = tabOf(ACTIVE.id);
    sel = t.id; if (ACTIVE.error) t.error = ACTIVE.error;
    if (ACTIVE.status !== 'done') { t.status = ACTIVE.status; if (ACTIVE.run && ACTIVE.run !== t.id) t.run = ACTIVE.run; }   // a demo replay runs under its own id
    if (DEMO) markRan(t.id);                                // a result's own address opens as it is, replayed or not
    renderTabs(); drawChart(); renderPick(); hint();
    const box = resEl.querySelector('#resultroot');
    if (box && t.status === 'done') { frags.set(t.id, resEl.innerHTML); mountedId = t.id; unmount = EarlyResult.mount(box, ch); ch.focus(parse(t.from), parse(t.to), null); }
    else if (t.status !== 'done' && t.status !== 'error') { startRun(t); paintRun(); runGlow(); ch.focus(parse(t.from), parse(t.to), null); }
    else { paintRun(); ch.focus(parse(t.from), parse(t.to), null); }
  } else {
    renderTabs(); drawChart(); renderPick(); hint();
    if (draft.from && draft.to) ch.focus(parse(draft.from), parse(draft.to), null);
    else if (tabs.length) focusAll(); else ch.init('1m');
  }
  if (D.notice) {
    openLimit(D.notice);
    try { history.replaceState(history.state, '', location.pathname + location.search.replace(/([?&])notice=[^&]*(&|$)/, '$1').replace(/[?&]$/, '') + location.hash); } catch (e) {}
  }
})();
