/* EarlyChart — market-cap candlestick chart on TradingView Lightweight Charts with window overlays.
   Data comes from /candles.json in chunks per timeframe; panning past the loaded edge loads more.
   Colours follow the design system: monochrome candles, sage/mint windows, cool-grey grid. */
(function () {
  const LW = window.LightweightCharts;
  const TF_SEC = { '1m': 60, '5m': 300, '15m': 900, '1h': 3600 };
  const CHUNK = { '1m': 12 * 3600, '5m': 3 * 86400, '15m': 10 * 86400, '1h': 60 * 86400 };
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const pad = n => String(n).padStart(2, '0');

  function fmtMcap(v) {
    if (v == null || isNaN(v)) return '—';
    if (v < 0) return '';                       // a cap is never below zero: the axis goes there only to make room for markers
    const sign = ''; v = Math.abs(v);
    for (const [lim, suf] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) {
      if (v >= lim * 0.9995) { const x = Math.max(v / lim, 1); let s = x < 10 ? x.toFixed(1) : x.toFixed(0); if (s.includes('.')) s = s.replace(/\.?0+$/, ''); return sign + s + suf; }
    }
    return sign + v.toFixed(0);
  }
  const local = () => (window.EarlyTZ && window.EarlyTZ.get() === 'local');
  function fmtTime(sec, withDate) {
    const d = new Date(sec * 1000), u = !local();
    const hm = pad(u ? d.getUTCHours() : d.getHours()) + ':' + pad(u ? d.getUTCMinutes() : d.getMinutes());
    return withDate ? MONTHS[u ? d.getUTCMonth() : d.getMonth()] + ' ' + (u ? d.getUTCDate() : d.getDate()) + ', ' + hm : hm;
  }
  function autoTf(spanSec) { const h = spanSec / 3600; return h <= 24 ? '1m' : h <= 24 * 7 ? '5m' : h <= 24 * 30 ? '15m' : '1h'; }
  const TF_ORDER = ['1m', '5m', '15m', '1h'];
  /* Where a badge goes when another one already sits there: a few steps up while the chart has room, then a few
     below, else on top of the other. A bounded list of places, never a loop that waits for a free one: at the top
     edge "up" stops moving, and an open-ended loop there froze the page (JEANPHIL, migration and DexScreener
     in the same minute with the price at the top of the chart). */
  function stackY(x, y0, placed, bottom) {
    const free = y => !placed.some(q => Math.abs(q.x - x) < 30 && Math.abs(q.y - y) < 30);
    if (free(y0)) return y0;
    const tries = [];
    for (let k = 1; k <= 4; k++) if (y0 - 32 * k >= 18) tries.push(y0 - 32 * k);
    for (let k = 1; k <= 4; k++) if (y0 + 32 * k <= Math.max(bottom, y0 + 32)) tries.push(y0 + 32 * k);
    const y = tries.find(free);
    return y === undefined ? y0 : y;
  }
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // design v2 (the rebrand, 26.10, behind the `design` cookie): the chart on the page's graphite card, candles in profit
  // and loss, Switzer on the axes. Without the cookie the chart stays as it was
  const V2 = document.documentElement.dataset.design === 'v2';
  // each range its own shade of the same mint, so two neighbours are told apart without a rainbow (owner, 02.10)
  const SHADES = V2 ? ['149, 235, 213', '120, 220, 200', '178, 242, 224', '110, 205, 225', '135, 225, 190']
                    : ['52, 211, 153', '45, 212, 191', '134, 239, 172', '34, 211, 238', '110, 231, 183'];
  window.EarlyChart = function (el, opts) {
    const created = opts.created / 1000, now = opts.now / 1000;
    const C = V2
      ? { bg: { type: 'solid', color: '#17181A' }, text: '#8B8F94', font: '"Switzer", "IBM Plex Sans", ui-sans-serif, sans-serif',
          gridV: 'rgba(255, 255, 255, 0.04)', gridH: 'rgba(255, 255, 255, 0.05)', edge: 'rgba(255, 255, 255, 0.07)', cross: '#4C5055', crossBg: '#2A2C30',
          up: '#5AD46A', upFill: '#5AD46A', down: '#FF6470', volUp: 'rgba(90, 212, 106, 0.28)', volDown: 'rgba(255, 100, 112, 0.22)',
          mark: 'rgba(237, 238, 239, 0.05)', markFont: '"Switzer", "IBM Plex Sans", sans-serif', buy: '#5AD46A', sell: '#FF6470' }
      : { bg: (LW.ColorType && LW.ColorType.VerticalGradient) ? { type: LW.ColorType.VerticalGradient, topColor: '#0B1220', bottomColor: '#090D16' } : { type: 'solid', color: '#090D16' },
          text: '#94A3B8', font: '"IBM Plex Mono", ui-monospace, Menlo, monospace',
          gridV: '#10172A', gridH: '#182236', edge: '#1E293B', cross: '#64748B', crossBg: '#1E293B',
          up: '#A7F3D0', upFill: 'rgba(167, 243, 208, 0.22)', down: '#CBD5E1', volUp: 'rgba(167, 243, 208, 0.28)', volDown: 'rgba(148, 163, 184, 0.22)',
          mark: 'rgba(148, 163, 184, 0.09)', markFont: '"IBM Plex Sans", -apple-system, sans-serif', buy: '#34D399', sell: '#F87171' };
    const box = document.createElement('div'); box.className = 'lw'; el.appendChild(box);
    const layer = document.createElement('div'); layer.className = 'overlay'; el.appendChild(layer);

    const chart = LW.createChart(box, {
      autoSize: true,
      layout: { background: C.bg, textColor: C.text, fontSize: 11, fontFamily: C.font, attributionLogo: false },
      grid: { vertLines: { color: C.gridV }, horzLines: { color: C.gridH } },
      rightPriceScale: { borderColor: C.edge, scaleMargins: { top: 0.08, bottom: 0.08 } },
      // minBarSpacing 2: the renderer draws a candle body only when it is wider than its two borders, so bars packed
      // below a pixel or two turn into outlines on the dark ground and the chart reads as empty (it did on phones)
      timeScale: { borderColor: C.edge, timeVisible: true, secondsVisible: false, rightOffset: 4, minBarSpacing: 2,
                   tickMarkFormatter: (t, type) => (type <= 2 ? fmtTime(t, true).replace(/, \d\d:\d\d$/, '') : fmtTime(t, false)) },
      crosshair: { mode: LW.CrosshairMode.Normal, vertLine: { color: C.cross, labelBackgroundColor: C.crossBg }, horzLine: { color: C.cross, labelBackgroundColor: C.crossBg } },
      localization: { priceFormatter: fmtMcap, timeFormatter: s => fmtTime(s, true) },
      // a vertical swipe scrolls the page, not the chart: on a phone the chart is half the screen and used to trap it
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }, handleScale: true,
    });
    const series = chart.addSeries(LW.CandlestickSeries, {
      upColor: C.upFill, downColor: C.down, borderUpColor: C.up, borderDownColor: C.down,
      wickUpColor: C.up, wickDownColor: C.down,
      priceFormat: { type: 'custom', formatter: fmtMcap, minMove: 1 },
      priceLineVisible: false, lastValueVisible: true,
    });
    // volume histogram at the bottom (own scale, 18% of the height), mint on up candles, grey on down
    const vol = LW.HistogramSeries ? chart.addSeries(LW.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false }) : null;
    if (vol) chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });
    // v2: the price is the market cap over the supply, a display of the same candles (canvas Analysis4: Market cap | Price)
    const SUPPLY = V2 ? +opts.supply || 0 : 0;
    let mode = 'cap';
    try { if (SUPPLY && localStorage.getItem('early:cmode') === 'price') mode = 'price'; } catch (e) {}
    const SUB = '₀₁₂₃₄₅₆₇₈₉';
    function fmtPrice(v) {                                    // $0.0083, $0.0₅83: the zeros after the point counted, as terminals do
      if (v == null || isNaN(v)) return '—';
      if (v < 0) return '';
      const p = v / SUPPLY; if (!(p > 0)) return '$0';
      if (p >= 1) return '$' + (p >= 1000 ? fmtMcap(p) : p.toFixed(p >= 100 ? 0 : 2));
      let z = Math.floor(-Math.log10(p)), d = Math.round(p * Math.pow(10, z + 3));
      if (d >= 1000) { z -= 1; d = Math.round(d / 10); }
      if (z < 4) return '$' + String(parseFloat(p.toPrecision(3)));
      return '$0.0' + String(z).split('').map(c => SUB[+c]).join('') + String(d).replace(/0+$/, '');
    }
    const fmtVal = v => (mode === 'price' ? fmtPrice(v) : fmtMcap(v));
    function applyMode() {                                    // new formatter functions, so the axis redraws its labels
      chart.applyOptions({ localization: { priceFormatter: v => fmtVal(v), timeFormatter: s => fmtTime(s, true) } });
      series.applyOptions({ priceFormat: { type: 'custom', formatter: v => fmtVal(v), minMove: 1 } });
    }
    if (mode === 'price') applyMode();
    if (LW.createTextWatermark && opts.symbol && !V2) {       // v2: the symbol is in the head already (each fact once)
      try { LW.createTextWatermark(chart.panes()[0], { horzAlign: 'center', vertAlign: 'center',
        lines: [{ text: opts.symbol, color: C.mark, fontSize: 72, fontFamily: C.markFont, fontStyle: '600' }] }); } catch (e) {}
    }
    const empty = document.createElement('div'); empty.className = 'chart-empty'; empty.hidden = true;
    empty.textContent = 'No candles here yet'; el.appendChild(empty);
    // crosshair legend (top-left): O · H · L · C · Vol · time
    const legend = document.createElement('div'); legend.className = 'legend'; legend.hidden = true; el.appendChild(legend);
    const fmtVol = v => (v == null ? '—' : '$' + fmtMcap(v));
    // v2 (canvas Analysis4): the readout always stands at the top left, «Oct 7, 03:17 · O 280K · H 285K · L 234K · C 274K»,
    // for the candle under the pointer, else the last one in view
    let hovering = false;
    const legendV2 = c => fmtTime(c.time, true) + ' · O <b>' + fmtVal(c.open) + '</b> · H <b>' + fmtVal(c.high) + '</b> · L <b>' + fmtVal(c.low) + '</b> · C <b>' + fmtVal(c.close) + '</b>'
      + (c.volume != null ? ' · Vol <b>' + fmtVol(c.volume) + '</b>' : '');
    function legendIdle() {
      if (!V2 || hovering) return;
      const v = visible(); if (!v || !times.length || v.b < times[0]) { legend.hidden = true; return; }
      let lo = 0, hi = times.length - 1;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (times[m] <= v.b) lo = m; else hi = m - 1; }
      const c = data.get(times[lo]); if (!c) return;
      legend.hidden = false; legend.innerHTML = legendV2(c);
    }
    chart.subscribeCrosshairMove(p => {
      const c = p && p.time ? data.get(p.time) : null;
      if (!c) { hovering = false; if (V2) legendIdle(); else legend.hidden = true; return; }
      hovering = true;
      legend.hidden = false;
      legend.innerHTML = V2 ? legendV2(c) : 'O <b>' + fmtMcap(c.open) + '</b> H <b>' + fmtMcap(c.high) + '</b> L <b>' + fmtMcap(c.low) + '</b> C <b>' + fmtMcap(c.close) + '</b>' +
        (c.volume != null ? ' Vol <b>' + fmtVol(c.volume) + '</b>' : '') + ' · ' + fmtTime(c.time, true);
    });

    const sec = v => (v == null ? null : (v > 1e11 ? v / 1000 : v));   // accept ms or seconds
    // how many candles fit the width at ~5 px each: the timeframe is chosen from the width as well as the time span
    const scaleW = () => { try { return chart.priceScale('right').width() || 64; } catch (e) { return 64; } };
    const maxBars = () => Math.max(60, Math.floor((box.clientWidth - scaleW()) / 5));
    const narrow = () => box.clientWidth < 600;
    function pickTf(spanSec) {
      let i = TF_ORDER.indexOf(autoTf(spanSec));
      while (i < TF_ORDER.length - 1 && spanSec / TF_SEC[TF_ORDER[i]] > maxBars()) i++;
      return TF_ORDER[i];
    }
    const normWins = ws => (ws || []).map(w => ({ ...w, from: sec(w.from), to: sec(w.to) }));
    let tf = null, data = new Map(), times = [], loaded = { a: null, b: null }, busy = false, gen = 0;
    let edge = { left: false, right: false };   // the feed has nothing further that way: stop asking for it
    let windows = normWins(opts.windows), selected = opts.selected || 0, exitSec = sec(opts.exit), marker = null, events = [], running = null;
    // The first visit's demo (owner, 30.09): no line of text about clicking, and no bands the page picked by itself. A
    // cursor clicks where buying starts, then where the pump takes off, a band grows between the two clicks, and it goes
    // round until the person clicks the chart. 'two' — both clicks; {after} — the second, from the first mark
    let demo = null;
    const demoEl = document.createElement('div'); demoEl.className = 'clickdemo'; demoEl.hidden = true; demoEl.setAttribute('aria-hidden', 'true');
    demoEl.innerHTML = '<i class="cd-band"></i><i class="cd-ring r1"></i><i class="cd-ring r2"></i><i class="cd-tap"></i>'
      + '<svg class="cd-cur" viewBox="0 0 16 22"><path d="M1.5 1.5v16.2l4.3-4.1 2.8 6.4 2.8-1.2-2.8-6.3h5.9z"/></svg>';
    el.appendChild(demoEl);

    async function fetchChunk(a, b) {
      const q = new URLSearchParams({ mint: opts.mint, tf, a: Math.floor(a), b: Math.ceil(b) });
      const r = await fetch('/candles.json?' + q);
      if (!r.ok) { try { const d = await r.json(); if (d && d.error && window.EarlyUI) EarlyUI.toast(d.error, 8000); } catch (e) {} return []; }   // say why the chart is empty
      return r.json();
    }
    /* One request covers at most CHUNK[tf]: the feed silently truncates a larger one and returns only the newest
       slice, which used to look like "the history got shorter" after a timeframe switch. */
    function capSpan(a, b) { const s = CHUNK[tf]; if (b - a <= s) return [a, b]; const c = (a + b) / 2; return [c - s / 2, c + s / 2]; }
    async function load(a, b, dir) {
      a = Math.max(created, a); b = Math.min(now, b); if (b <= a) return;
      const my = gen; busy = true; if (!data.size) el.classList.add('loading');
      try {
        const had = data.size;
        const rows = await fetchChunk(a, b); if (my !== gen) return;
        // chunks must not move the view. The logical range, not the time range: the time range covers only bars
        // that exist, so a view panned into the empty space before the first candle snapped back towards the
        // range every time older candles arrived, and the start of an old token could never be reached
        const keepL = data.size ? chart.timeScale().getVisibleLogicalRange() : null, firstBefore = times[0];
        rows.forEach(c => data.set(c.time, c));
        if (dir && data.size === had) edge[dir] = true;                        // asked that way, got nothing new: that edge is done
        if (rows.length) {                                                     // trust the candles that came back, not the range we asked for
          const first = rows[0].time, last = rows[rows.length - 1].time;
          loaded.a = loaded.a === null ? first : Math.min(loaded.a, first);
          loaded.b = loaded.b === null ? last : Math.max(loaded.b, last);
        }
        const sorted = [...data.values()].sort((x, y) => x.time - y.time);
        times = sorted.map(c => c.time);
        series.setData(sorted);
        if (vol) vol.setData(sorted.map(c => ({ time: c.time, value: c.volume || 0, color: c.close >= c.open ? C.volUp : C.volDown })));
        renderMarkers();
        if (keepL) {
          const shift = firstBefore == null ? 0 : Math.max(0, times.indexOf(firstBefore));   // bars that arrived on the left
          chart.timeScale().setVisibleLogicalRange({ from: keepL.from + shift, to: keepL.to + shift });
        }
      } finally { busy = false; el.classList.remove('loading'); place(); placeSoon(); }
    }
    function visible() { const r = chart.timeScale().getVisibleRange(); return r ? { a: r.from, b: r.to } : null; }
    function center() { const v = visible(); return v ? (v.a + v.b) / 2 : (created + now) / 2; }

    async function setTf(newTf, keepView, start) {
      const v = visible();
      tf = newTf; gen++; data.clear(); times = []; loaded = { a: null, b: null }; edge = { left: false, right: false };
      const span = CHUNK[tf];
      let a, b;
      if (v && keepView) { const c = (v.a + v.b) / 2, w = Math.min(Math.max((v.b - v.a) * 1.2, span / 2), span); a = c - w / 2; b = c + w / 2; }
      else if (now - created <= span) { a = created; b = now; }
      else if (start === 'recent') { a = now - span; b = now; }       // a token page opens on its latest hours
      else { const c = center(); a = c - span / 2; b = c + span / 2; }
      await load(...capSpan(a, b));
      if (!data.size && !(v && keepView)) {
        // a cold start can land on hours with no trades: try the latest hours, then the first ones, before saying
        // the chart is empty
        for (const [x, y] of [[now - span, now], [created, created + span]]) { if (start === 'recent' && x === a) continue; await load(...capSpan(x, y)); if (data.size) break; }
      }
      empty.hidden = data.size > 0;
      if (v && keepView) chart.timeScale().setVisibleRange({ from: Math.max(v.a, created), to: Math.min(v.b, now) });
      else chart.timeScale().fitContent();
      (T ? T.left : el).querySelectorAll('.tf').forEach(btn => btn.classList.toggle('on', btn.dataset.tf === tf));
    }
    async function focus(fromSec, toSec, exitS) {
      // bring the range into view; the user's timeframe and the loaded candles stay when they suit it (no reload, no blink)
      const span = Math.max(toSec - fromSec, 300);
      // the range and its minutes around it: a 20–90 min range opens on 1m candles (hours around it forced 5m-1h)
      const padS = narrow() ? Math.max(span * 0.3, 1800) : Math.max(span * 0.6, 1800);
      const a = Math.max(created, fromSec - padS), b = Math.min(now, (exitS && exitS < toSec + 8 * 3600 ? exitS : toSec) + padS);
      const want = pickTf(b - a);
      const fits = tf && (b - a) / TF_SEC[tf] >= 12 && (b - a) / TF_SEC[tf] <= maxBars() * 1.5;   // not a few bars, not too many for the width
      // the loaded candles reach the range by one edge chunk; a range days away starts over around itself (an edge
      // chunk is capped, so it stopped half way and the view landed on two stray candles)
      const near = loaded.a !== null && a >= loaded.a - CHUNK[tf] / 2 && b <= loaded.b + CHUNK[tf] / 2;
      if (!fits || !near) {
        if (!fits) tf = want;
        gen++; data.clear(); times = []; loaded = { a: null, b: null }; edge = { left: false, right: false };
        await load(...capSpan(a - CHUNK[tf] / 4, b + CHUNK[tf] / 4));
      } else {
        if (loaded.a > a && !edge.left) await load(...capSpan(a - CHUNK[tf] / 4, loaded.a), 'left');
        if (loaded.b < b && !edge.right) await load(...capSpan(loaded.b, b + CHUNK[tf] / 4), 'right');
      }
      empty.hidden = data.size > 0;
      const v = visible();
      if (!v || a < v.a || b > v.b) chart.timeScale().setVisibleRange({ from: a, to: b });   // already in view → leave it
      (T ? T.left : el).querySelectorAll('.tf').forEach(btn => btn.classList.toggle('on', btn.dataset.tf === tf));
    }

    // lazy-load when panning near an edge
    chart.timeScale().subscribeVisibleLogicalRangeChange(debounce(async range => {
      if (!range || busy || loaded.a === null) return;
      const info = series.barsInLogicalRange(range); if (!info) return;
      if (info.barsBefore < 40 && !edge.left && loaded.a > created + 1) await load(loaded.a - CHUNK[tf], loaded.a, 'left');
      else if (info.barsAfter < 40 && !edge.right && loaded.b < now - TF_SEC[tf]) await load(loaded.b, loaded.b + CHUNK[tf], 'right');
    }, 120));
    /* The price axis re-fits to the new candles on the library's next paint, after this range change: a badge placed
       now uses the old scale and lands under the toolbar or off the chart (⇤ Launch did that). So place again once
       the library has painted, at most once per frame pair. */
    let soon = 0;
    function placeSoon() { if (!soon) soon = requestAnimationFrame(() => { soon = requestAnimationFrame(() => { soon = 0; place(); }); }); }
    chart.timeScale().subscribeVisibleTimeRangeChange(() => { place(); placeSoon(); });
    let pickedW = 0, pickedDrawer = null;
    /* A card or the agent docking beside the chart narrows it, and the library keeps the right edge: the range the
       page is about slid out on the left. The class flips before the resize, so the hours in view are taken then and
       put back once the chart has its new width. */
    let keepRange = null, keepT = 0, lastDr = document.body.classList.contains('drawer-open');
    new MutationObserver(() => {
      const dr = document.body.classList.contains('drawer-open'); if (dr === lastDr) return;
      lastDr = dr; const v = visible(); if (!v) return;
      keepRange = { from: v.a, to: v.b }; clearTimeout(keepT); keepT = setTimeout(() => { keepRange = null; }, 600);   // a phone's full-screen card changes no width
    }).observe(document.body, { attributes: true, attributeFilter: ['class'] });
    new ResizeObserver(() => {
      if (keepRange) { const k = keepRange; keepRange = null; requestAnimationFrame(() => { try { chart.timeScale().setVisibleRange(k); } catch (e) {} place(); }); }
      place();
      // turning a phone or narrowing a window by a third: re-pick the timeframe if the candles no longer fit
      const w = box.clientWidth, v = visible(), dr = document.body.classList.contains('drawer-open');
      if (!pickedW || dr !== pickedDrawer) { pickedW = w; pickedDrawer = dr; return; }   // a card opening beside the chart keeps the timeframe
      if (!tf || !v || busy || Math.abs(w - pickedW) < pickedW * 0.3) return;
      pickedW = w;
      const want = pickTf(v.b - v.a);
      if (want !== tf) setTf(want, true);
    }).observe(el);

    // overlays: windows, exit line, first-click marker
    // A time that is not exactly a candle's timestamp has no coordinate of its own: timeToCoordinate only
    // answers for bars that exist. A range drawn by hand almost never lands on the grid, so we interpolate
    // between the two neighbouring bars — otherwise the band silently disappears on coarser timeframes.
    function xOf(sec) {
      const v = visible(); if (!v) return null;
      const s = Math.min(Math.max(sec, v.a), v.b), ts = chart.timeScale();
      const exact = ts.timeToCoordinate(s);
      if (exact != null) return exact;
      if (!times.length) return null;
      let lo = 0, hi = times.length - 1;
      if (s <= times[0]) return ts.timeToCoordinate(times[0]);
      if (s >= times[hi]) return ts.timeToCoordinate(times[hi]);
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (times[m] <= s) lo = m; else hi = m - 1; }
      const a = times[lo], b = times[Math.min(lo + 1, times.length - 1)];
      const xa = ts.timeToCoordinate(a), xb = ts.timeToCoordinate(b);
      if (xa == null) return xb;
      if (xb == null || b === a) return xa;
      return xa + (xb - xa) * ((s - a) / (b - a));
    }
    /* Vertical position of an event: the close of the candle it falls into, so the badge sits on the price the
       way it does on a terminal. No candle yet, no coordinate — the caller drops it near the bottom instead. */
    function yOf(sec) {
      // above the candle's high, like a terminal draws it: on the body a badge got lost among the candles
      if (!times.length) return null;
      let lo = 0, hi = times.length - 1;
      if (sec < times[0] || sec > times[hi] + 1e6) return null;
      while (lo < hi) { const m = (lo + hi + 1) >> 1; if (times[m] <= sec) lo = m; else hi = m - 1; }
      const c = data.get(times[lo]); if (!c) return null;
      const y = series.priceToCoordinate(c.high != null ? c.high : c.close);
      return y == null ? null : y - 24;
    }
    function place() {
      layer.innerHTML = '';
      const v = visible(); if (!v) return;
      const W = box.clientWidth - scaleW(), bands = [];   // price scale on the right
      windows.forEach((w, i) => {
        if (!w.from || !w.to || w.to < v.a || w.from > v.b) return;
        const x1 = xOf(w.from), x2 = xOf(w.to); if (x1 == null || x2 == null) return;
        const d = document.createElement('div'); d.className = 'win' + (i === selected ? ' sel' : '') + (i === running ? ' run' : '') + (V2 && w.draft ? ' draft' : '');
        d.style.setProperty('--wc', SHADES[i % SHADES.length]);
        d.style.left = Math.min(x1, W) + 'px'; d.style.width = Math.max(2, Math.min(x2, W) - Math.min(x1, W)) + 'px';
        const lbl = document.createElement('span'); lbl.className = 'lbl';
        // v2 (canvas Analysis4): every band says its name and its minutes, «Pump 1 · 02:43–03:30»
        lbl.textContent = V2 ? (w.label || 'Range ' + (w.n || i + 1)) + ' · ' + fmtTime(w.from) + '–' + fmtTime(w.to) : (w.n || (i + 1)) + (w.label && i === selected ? ' · ' + w.label : '');
        lbl.title = w.label || '';
        lbl.addEventListener('click', e => { e.stopPropagation(); if (opts.onSelect) opts.onSelect(i); else focus(w.from, w.to, null); });
        d.appendChild(lbl); layer.appendChild(d); bands.push({ x: Math.min(x1, W), lbl });
      });
      // a label ends where the next range starts, so "1 · Pump 1" never hides the 2 of a close neighbour (phone, 01.10)
      bands.forEach(b => { const nx = Math.min(W, ...bands.filter(o => o.x > b.x).map(o => o.x)); b.lbl.style.maxWidth = Math.max(16, nx - b.x - 8) + 'px'; });
      // events of the token's own life: the move off the launchpad, the payments for visibility. Thin full-height
      // lines, because trade markers already live next to the candles and must not compete with these.
      // A badge at the point where it happened, not a line through the whole chart: these events sit within a
      // minute of each other in a token's first hour, and three full-height lines there are unreadable.
      const drawn = {}, placed = [];           // дві оплати за хвилину одна від одної — один значок, обидві в підказці
      events.forEach(e => {
        if (!e.sec || e.sec < v.a || e.sec > v.b) return;
        const x0 = xOf(e.sec); if (x0 == null || x0 > W) return;
        const x = Math.max(12, Math.min(x0, W - 12));   // a badge at the very edge stays whole (phone, 01.10: the M was cut in half)
        const kind = e.kind || 'ev', prev = drawn[kind];
        if (prev && Math.abs(x - prev.x) < 16) { prev.n++; prev.el.title += '\n' + (e.title || ''); prev.el.dataset.n = prev.n; return; }
        const y = stackY(x, Math.min(Math.max(18, yOf(e.sec) ?? 40), box.clientHeight - 30), placed, box.clientHeight - 30);   // never below the box, whatever the scale says
        placed.push({ x, y });
        const d = document.createElement('div'); d.className = 'evdot ' + kind;
        d.style.left = x + 'px'; d.style.top = y + 'px';
        if (e.html) d.innerHTML = e.html; else d.textContent = e.badge || '•';
        d.title = e.title || '';
        layer.appendChild(d);
        drawn[kind] = { x, el: d, n: 1 };
      });
      if (exitSec && exitSec >= v.a && exitSec <= v.b) { const x = xOf(exitSec); if (x != null) { const d = document.createElement('div'); d.className = 'exitline'; d.style.left = x + 'px'; d.title = 'Trades up to'; layer.appendChild(d); } }
      if (marker && marker >= v.a && marker <= v.b) { const x = xOf(marker); if (x != null) { const d = document.createElement('div'); d.className = 'marker'; d.style.left = x + 'px'; layer.appendChild(d); } }
      placeDemo(v, W);
      legendIdle();
    }
    function placeDemo(v, W) {
      // the clicks sit in the middle of what is on screen; the second one, right of the first mark while it is in view
      if (!demo || !v) { demoEl.hidden = true; return; }
      let x1 = W * 0.34, x2 = W * 0.62;
      if (demo.after) {
        x1 = demo.after >= v.a && demo.after <= v.b ? xOf(demo.after) : null;
        if (x1 == null || x1 > W - 60) { demoEl.hidden = true; return; }
        x2 = Math.min(W - 24, x1 + Math.max(80, W * 0.2));
      }
      demoEl.hidden = false; demoEl.classList.toggle('one', !!demo.after);
      demoEl.style.width = W + 'px';
      demoEl.style.setProperty('--x1', Math.round(x1) + 'px'); demoEl.style.setProperty('--x2', Math.round(x2) + 'px');
      demoEl.style.setProperty('--y', Math.round((box.clientHeight - 34) * 0.56) + 'px');
    }
    if (opts.interactive) chart.subscribeClick(p => { if (p.time && opts.onClick) opts.onClick(p.time * 1000); });

    /* Wallet trade markers. Colour says only what the trade was: green bought, red sold. Trades of one wallet on
       one side inside one candle merge into a single marker carrying their total, so a busy wallet does not bury
       the chart (25 wallets of the demo are 7,547 trades, 1,818 markers at 5m). Size is the amount, in three steps.
       A wallet funded together with others is drawn as a square instead of an arrow: the library stacks markers that
       share a bar and a side rather than overlaying them, so a ring behind the arrow is not possible — the group's
       own colour lives on its chip under the chart and on the row stripe in the table. */
    const BUY = C.buy, SELL = C.sell;
    let wallets = [], markersApi = null;
    const fmtUsd = v => (v == null ? '' : '$' + (v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + 'K' : v.toFixed(0)));
    function groupTrades(list, step) {
      // one marker per wallet × candle × side, with the summed amount and how many trades went into it
      const by = new Map();
      (list || []).forEach(w => (w.trades || []).forEach(tr => {
        if (tr.side !== 'buy' && tr.side !== 'sell') return;
        const t = Math.floor(tr.t / 1000 / step) * step, k = w.wallet + '|' + t + '|' + tr.side;
        const g = by.get(k);
        if (g) { g.usd += tr.usd || 0; g.qty += tr.qty || 0; g.n += 1; }
        else by.set(k, { w, t, side: tr.side, usd: tr.usd || 0, qty: tr.qty || 0, n: 1 });
      }));
      return [...by.values()];
    }
    function sizeSteps(inView) {
      // three steps by amount so a big buy reads as big; quantiles of what is on screen, not of all time
      const v = inView.map(m => m.usd).filter(x => x > 0).sort((x, y) => x - y);
      if (v.length < 4) return () => 0.9;
      const mid = v[Math.floor(v.length * 0.5)], top = v[Math.floor(v.length * 0.85)];
      return usd => (usd >= top ? 1.3 : usd >= mid ? 0.95 : 0.65);
    }
    function renderMarkers() {
      if (!LW.createSeriesMarkers || !tf) return;
      const v = visible(), all = groupTrades(wallets, TF_SEC[tf]);
      // labels: every marker when ≤ 40 are in view, otherwise only the 12 largest in view — zoom in for the rest
      const inView = v ? all.filter(m => m.t >= v.a && m.t <= v.b) : all;
      let labeled;
      if (inView.length <= 40) labeled = new Set(inView);
      else labeled = new Set([...inView].sort((x, y) => y.usd - x.usd).slice(0, 12));
      const sizeOf = sizeSteps(inView), ms = [];
      all.forEach(m => {
        const buy = m.side === 'buy';
        ms.push({ time: m.t, position: buy ? 'belowBar' : 'aboveBar', shape: m.w.bundleColor ? 'square' : (buy ? 'arrowUp' : 'arrowDown'),
                  color: buy ? BUY : SELL, size: sizeOf(m.usd), text: labeled.has(m) ? fmtUsd(m.usd) : undefined });
      });
      ms.sort((x, y) => x.time - y.time);
      if (!markersApi) markersApi = LW.createSeriesMarkers(series, ms); else markersApi.setMarkers(ms);
      if (opts.onMarkers) opts.onMarkers({ total: all.length, inView: inView.length, labeled: labeled.size });
    }
    chart.timeScale().subscribeVisibleTimeRangeChange(debounce(() => { if (wallets.length) renderMarkers(); }, 150));

    // timeframe buttons
    const T = V2 && opts.tools && opts.tools.left ? opts.tools : null;    // v2: the page's toolbar above the chart
    const tfs = document.createElement(T ? 'span' : 'div'); tfs.className = T ? 'seg tfseg' : 'tfs';
    if (T) tfs.setAttribute('role', 'group'), tfs.setAttribute('aria-label', 'Candle length');
    Object.keys(TF_SEC).forEach(k => { const b = document.createElement('button'); b.type = 'button'; b.className = 'tf'; b.dataset.tf = k; b.textContent = k; b.addEventListener('click', () => { setTf(k, true); if (window.EarlyUI) EarlyUI.use('tf', { tf: k }); }); tfs.appendChild(b); });
    const back = document.createElement('button'); back.type = 'button'; back.className = 'tf back'; back.innerHTML = '<span class="wide">⌖ Back to range</span><span class="narrow">⌖ Range</span>'; back.title = 'Bring the range you marked back into view'; back.hidden = !windows.some(w => w && w.from && w.to);   // a result page has its range from the start
    back.addEventListener('click', () => { const w = windows[selected] || windows[0]; if (w && w.from && w.to) focus(w.from, w.to, null); if (window.EarlyUI) EarlyUI.use('chart-nav', { to: 'range' }); });
    const launch = document.createElement('button'); launch.type = 'button'; launch.className = 'tf back'; launch.innerHTML = '<span class="wide">⇤ First hours</span><span class="narrow">⇤ Start</span>';
    launch.title = 'Jump to the first hours of trading, right after the token launched';
    launch.addEventListener('click', () => { focus(created, created + 3 * 3600, null); if (window.EarlyUI) EarlyUI.use('chart-nav', { to: 'launch' }); });
    if (T) {
      // v2 (canvas Analysis4): [1m 5m 15m 1h] [Market cap | Price] ⊙ ⇤ … [UTC | Local]; round marks for the two jumps
      const G = (d, l) => '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="' + l + '">' + d + '</svg>';
      back.className = launch.className = 'cbtn';
      back.innerHTML = G('<circle cx="8" cy="8" r="5.4"/><circle cx="8" cy="8" r="1.4" fill="currentColor" stroke="none"/>', 'Back to the range');
      back.title = 'Back to the range you marked'; back.setAttribute('aria-label', 'Back to the range');
      launch.innerHTML = G('<path d="M3.4 3 V13"/><path d="M12.8 3.4 L6.4 8 L12.8 12.6"/>', 'First hours');
      launch.setAttribute('aria-label', 'First hours');
      T.left.appendChild(tfs);
      if (SUPPLY) {
        const m = document.createElement('span'); m.className = 'seg cmode'; m.setAttribute('role', 'group'); m.setAttribute('aria-label', 'Market cap or price');
        m.innerHTML = '<button type="button" data-m="cap">Market cap</button><button type="button" data-m="price">Price</button>';
        const mark = () => m.querySelectorAll('[data-m]').forEach(b => { const on = b.dataset.m === mode; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
        m.addEventListener('click', e => {
          const b = e.target.closest('[data-m]'); if (!b || b.dataset.m === mode) return;
          mode = b.dataset.m; try { localStorage.setItem('early:cmode', mode); } catch (x) {}
          mark(); applyMode(); hovering = false; legendIdle(); if (window.EarlyUI) EarlyUI.use('chart-mode', { m: mode });
        });
        m.title = 'The price is the market cap over the supply, ' + fmtMcap(SUPPLY) + ' tokens';
        mark(); T.left.appendChild(m);
      }
      T.left.appendChild(back); T.left.appendChild(launch);
      if (window.EarlyTZ && T.right) {                       // UTC or local time where time is read (26.10); a switch reloads, as before
        const tz = document.createElement('button'); tz.type = 'button'; tz.className = 'seg tzseg'; tz.id = 'tz';
        tz.innerHTML = '<b' + (EarlyTZ.get() === 'utc' ? ' class="on"' : '') + '>UTC</b><b' + (EarlyTZ.get() === 'utc' ? '' : ' class="on"') + '>Local</b>';
        tz.title = EarlyTZ.get() === 'utc' ? 'Times are in UTC. Click for your local time' : 'Times are in your local time. Click for UTC';
        tz.setAttribute('aria-label', 'Time zone'); tz.addEventListener('click', () => EarlyTZ.toggle());
        T.right.appendChild(tz);
      }
    } else {
    tfs.appendChild(back);
    tfs.appendChild(launch);
    }
    // v2 has no status bar and no footer switch: UTC or local time lives here, where time is read (26.10)
    if (V2 && opts.interactive && window.EarlyTZ && !T) {
      const tz = document.createElement('button'); tz.type = 'button'; tz.className = 'tf tzone';
      tz.textContent = EarlyTZ.get() === 'utc' ? 'UTC' : 'Local';
      tz.title = EarlyTZ.get() === 'utc' ? 'Times are in UTC. Click for your local time' : 'Times are in your local time. Click for UTC';
      tz.addEventListener('click', () => EarlyTZ.toggle());
      tfs.appendChild(tz);
    }
    if (!T) el.appendChild(tfs);

    return {
      setWindows(ws, sel) { windows = normWins(ws); selected = sel; back.hidden = !windows.some(w => w && w.from && w.to); place(); },
      setEvents(list) { events = (list || []).map(e => ({ ...e, sec: sec(e.ms) })).filter(e => e.sec); place(); },
      setExit(v) { exitSec = sec(v); place(); },
      setMarker(v) { marker = sec(v); place(); },
      setDemo(m) { const next = m === 'two' ? 'two' : m && m.after ? { after: sec(m.after) } : null;
        if (JSON.stringify(next) !== JSON.stringify(demo)) { demo = next; place(); } },
      setWalletMarkers(list) { wallets = list || []; renderMarkers(); },
      setOnMarkers(fn) { opts.onMarkers = fn; },           // the page keeps one chart; each result says where its marker hint goes
      setRunning(i) { if (running !== i) { running = i; place(); } },   // the band being analyzed glows while its run goes (owner, 09.10)
      focus: (from, to, exit) => focus(sec(from), sec(to), sec(exit)),
      setTf, init: async first => { if (first) await setTf(first, false, 'recent'); else await setTf(pickTf(now - created), false); },
      fmtMcap,
      candles: () => [...data.values()].sort((x, y) => x.time - y.time),   // loaded candles in market cap, oldest first
    };
  };
  window.EarlyChart.SHADES = SHADES;
})();
