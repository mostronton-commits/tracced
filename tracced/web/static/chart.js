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
    const sign = v < 0 ? '-' : ''; v = Math.abs(v);
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
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  window.EarlyChart = function (el, opts) {
    const created = opts.created / 1000, now = opts.now / 1000;
    const box = document.createElement('div'); box.className = 'lw'; el.appendChild(box);
    const layer = document.createElement('div'); layer.className = 'overlay'; el.appendChild(layer);

    const chart = LW.createChart(box, {
      autoSize: true,
      layout: { background: (LW.ColorType && LW.ColorType.VerticalGradient) ? { type: LW.ColorType.VerticalGradient, topColor: '#0B1220', bottomColor: '#090D16' } : { type: 'solid', color: '#090D16' },
                textColor: '#94A3B8', fontSize: 11,
                fontFamily: '"Geist Mono", "JetBrains Mono", ui-monospace, Menlo, monospace', attributionLogo: false },
      grid: { vertLines: { color: '#10172A' }, horzLines: { color: '#182236' } },
      rightPriceScale: { borderColor: '#1E293B', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: '#1E293B', timeVisible: true, secondsVisible: false, rightOffset: 4,
                   tickMarkFormatter: (t, type) => (type <= 2 ? fmtTime(t, true).replace(/, \d\d:\d\d$/, '') : fmtTime(t, false)) },
      crosshair: { mode: LW.CrosshairMode.Normal, vertLine: { color: '#64748B', labelBackgroundColor: '#1E293B' }, horzLine: { color: '#64748B', labelBackgroundColor: '#1E293B' } },
      localization: { priceFormatter: fmtMcap, timeFormatter: s => fmtTime(s, true) },
      handleScroll: true, handleScale: true,
    });
    const series = chart.addSeries(LW.CandlestickSeries, {
      upColor: '#090D16', downColor: '#CBD5E1', borderUpColor: '#A7F3D0', borderDownColor: '#CBD5E1',
      wickUpColor: '#A7F3D0', wickDownColor: '#CBD5E1',
      priceFormat: { type: 'custom', formatter: fmtMcap, minMove: 1 },
      priceLineVisible: false, lastValueVisible: true,
    });
    // volume histogram at the bottom (own scale, 18% of the height), mint on up candles, grey on down
    const vol = LW.HistogramSeries ? chart.addSeries(LW.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false }) : null;
    if (vol) chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });
    if (LW.createTextWatermark && opts.symbol) {
      try { LW.createTextWatermark(chart.panes()[0], { horzAlign: 'center', vertAlign: 'center',
        lines: [{ text: opts.symbol, color: 'rgba(148, 163, 184, 0.09)', fontSize: 72, fontFamily: '"Geist", -apple-system, sans-serif', fontStyle: '600' }] }); } catch (e) {}
    }
    // crosshair legend (top-left): O · H · L · C · Vol · time
    const legend = document.createElement('div'); legend.className = 'legend'; legend.hidden = true; el.appendChild(legend);
    const fmtVol = v => (v == null ? '—' : '$' + fmtMcap(v));
    chart.subscribeCrosshairMove(p => {
      const c = p && p.time ? data.get(p.time) : null;
      if (!c) { legend.hidden = true; return; }
      legend.hidden = false;
      legend.innerHTML = 'O <b>' + fmtMcap(c.open) + '</b> H <b>' + fmtMcap(c.high) + '</b> L <b>' + fmtMcap(c.low) + '</b> C <b>' + fmtMcap(c.close) + '</b>' +
        (c.volume != null ? ' Vol <b>' + fmtVol(c.volume) + '</b>' : '') + ' · ' + fmtTime(c.time, true);
    });

    const sec = v => (v == null ? null : (v > 1e11 ? v / 1000 : v));   // accept ms or seconds
    const normWins = ws => (ws || []).map(w => ({ ...w, from: sec(w.from), to: sec(w.to) }));
    let tf = null, data = new Map(), times = [], loaded = { a: null, b: null }, busy = false, gen = 0;
    let windows = normWins(opts.windows), selected = opts.selected || 0, exitSec = sec(opts.exit), marker = null;

    async function fetchChunk(a, b) {
      const q = new URLSearchParams({ mint: opts.mint, tf, a: Math.floor(a), b: Math.ceil(b) });
      const r = await fetch('/candles.json?' + q);
      if (!r.ok) { try { const d = await r.json(); if (d && d.error && window.EarlyUI) EarlyUI.toast(d.error, 8000); } catch (e) {} return []; }   // say why the chart is empty
      return r.json();
    }
    async function load(a, b) {
      a = Math.max(created, a); b = Math.min(now, b); if (b <= a) return;
      const my = gen; busy = true; if (!data.size) el.classList.add('loading');
      try {
        const rows = await fetchChunk(a, b); if (my !== gen) return;
        const keep = data.size ? chart.timeScale().getVisibleRange() : null;   // chunks must not move the view
        rows.forEach(c => data.set(c.time, c));
        loaded.a = loaded.a === null ? a : Math.min(loaded.a, a); loaded.b = loaded.b === null ? b : Math.max(loaded.b, b);
        const sorted = [...data.values()].sort((x, y) => x.time - y.time);
        times = sorted.map(c => c.time);
        series.setData(sorted);
        if (vol) vol.setData(sorted.map(c => ({ time: c.time, value: c.volume || 0, color: c.close >= c.open ? 'rgba(167, 243, 208, 0.28)' : 'rgba(148, 163, 184, 0.22)' })));
        renderMarkers();
        if (keep) chart.timeScale().setVisibleRange(keep);
      } finally { busy = false; el.classList.remove('loading'); place(); }
    }
    function visible() { const r = chart.timeScale().getVisibleRange(); return r ? { a: r.from, b: r.to } : null; }
    function center() { const v = visible(); return v ? (v.a + v.b) / 2 : (created + now) / 2; }

    async function setTf(newTf, keepView) {
      const v = visible();
      tf = newTf; gen++; data.clear(); times = []; loaded = { a: null, b: null };
      const span = CHUNK[tf];
      let a, b;
      if (v && keepView) { const c = (v.a + v.b) / 2, w = Math.max(v.b - v.a, span / 4); a = c - Math.max(w, span / 2); b = c + Math.max(w, span / 2); }
      else if (now - created <= span * 1.5) { a = created; b = now; }
      else { const c = center(); a = c - span / 2; b = c + span / 2; }
      await load(a, b);
      if (v && keepView) chart.timeScale().setVisibleRange({ from: Math.max(v.a, created), to: Math.min(v.b, now) });
      else chart.timeScale().fitContent();
      el.querySelectorAll('.tf').forEach(btn => btn.classList.toggle('on', btn.dataset.tf === tf));
    }
    async function focus(fromSec, toSec, exitS) {
      // bring the range into view; keep the user's timeframe and the loaded candles (no reload, no blink)
      const span = Math.max(toSec - fromSec, 300);
      const padS = Math.max(span * 1.2, 2 * 3600);
      const a = Math.max(created, fromSec - padS), b = Math.min(now, (exitS && exitS < toSec + 8 * 3600 ? exitS : toSec) + padS);
      const want = autoTf(b - a);
      if (!tf || (b - a) / TF_SEC[tf] < 12) {                       // no timeframe yet, or the range would be a few bars
        tf = want; gen++; data.clear(); times = []; loaded = { a: null, b: null };
        await load(a - CHUNK[tf] / 4, b + CHUNK[tf] / 4);
      } else {
        if (loaded.a === null) await load(a - CHUNK[tf] / 4, b + CHUNK[tf] / 4);
        else { if (loaded.a > a) await load(a - CHUNK[tf] / 4, loaded.a); if (loaded.b < b) await load(loaded.b, b + CHUNK[tf] / 4); }
      }
      const v = visible();
      if (!v || a < v.a || b > v.b) chart.timeScale().setVisibleRange({ from: a, to: b });   // already in view → leave it
      el.querySelectorAll('.tf').forEach(btn => btn.classList.toggle('on', btn.dataset.tf === tf));
    }

    // lazy-load when panning near an edge
    chart.timeScale().subscribeVisibleLogicalRangeChange(debounce(async range => {
      if (!range || busy || loaded.a === null) return;
      const info = series.barsInLogicalRange(range); if (!info) return;
      if (info.barsBefore < 40 && loaded.a > created + 1) await load(loaded.a - CHUNK[tf], loaded.a);
      else if (info.barsAfter < 40 && loaded.b < now - TF_SEC[tf]) await load(loaded.b, loaded.b + CHUNK[tf]);
    }, 120));
    chart.timeScale().subscribeVisibleTimeRangeChange(() => place());
    new ResizeObserver(() => place()).observe(el);

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
    function place() {
      layer.innerHTML = '';
      const v = visible(); if (!v) return;
      const W = box.clientWidth - 64;   // price scale on the right
      windows.forEach((w, i) => {
        if (!w.from || !w.to || w.to < v.a || w.from > v.b) return;
        const x1 = xOf(w.from), x2 = xOf(w.to); if (x1 == null || x2 == null) return;
        const d = document.createElement('div'); d.className = 'win' + (i === selected ? ' sel' : '');
        d.style.left = Math.min(x1, W) + 'px'; d.style.width = Math.max(2, Math.min(x2, W) - Math.min(x1, W)) + 'px';
        const lbl = document.createElement('span'); lbl.className = 'lbl'; lbl.textContent = (w.n || (i + 1)) + (w.label && i === selected ? ' · ' + w.label : ''); lbl.title = w.label || '';
        lbl.addEventListener('click', e => { e.stopPropagation(); if (opts.onSelect) opts.onSelect(i); else focus(w.from, w.to, null); });
        d.appendChild(lbl); layer.appendChild(d);
      });
      if (exitSec && exitSec >= v.a && exitSec <= v.b) { const x = xOf(exitSec); if (x != null) { const d = document.createElement('div'); d.className = 'exitline'; d.style.left = x + 'px'; d.title = 'Trades up to'; layer.appendChild(d); } }
      if (marker && marker >= v.a && marker <= v.b) { const x = xOf(marker); if (x != null) { const d = document.createElement('div'); d.className = 'marker'; d.style.left = x + 'px'; layer.appendChild(d); } }
    }
    if (opts.interactive) chart.subscribeClick(p => { if (p.time && opts.onClick) opts.onClick(p.time * 1000); });

    // wallet trade markers: buys = arrow up below the bar, sells = arrow down above it (each wallet a buy/sell colour pair)
    let wallets = [], markersApi = null;
    const fmtUsd = v => (v == null ? '' : '$' + (v >= 1000 ? (v / 1000).toFixed(v >= 10000 ? 0 : 1) + 'K' : v.toFixed(0)));
    function renderMarkers() {
      if (!LW.createSeriesMarkers || !tf) return;
      const step = TF_SEC[tf], v = visible(), all = [];
      wallets.forEach(w => (w.trades || []).forEach(tr => all.push({ w, tr, t: Math.floor(tr.t / 1000 / step) * step })));
      // labels: every trade when ≤ 40 markers are in view, otherwise only the 12 largest in view — zoom in for the rest
      const inView = v ? all.filter(m => m.t >= v.a && m.t <= v.b) : all;
      let labeled;
      if (inView.length <= 40) labeled = new Set(inView);
      else labeled = new Set([...inView].sort((x, y) => (y.tr.usd || 0) - (x.tr.usd || 0)).slice(0, 12));
      const ms = all.map(m => {
        const buy = m.tr.side === 'buy';
        return { time: m.t, position: buy ? 'belowBar' : 'aboveBar', shape: buy ? 'arrowUp' : 'arrowDown',
                 color: buy ? (m.w.buy || m.w.color) : (m.w.sell || m.w.color), size: 1,
                 text: labeled.has(m) ? fmtUsd(m.tr.usd) : undefined };
      });
      ms.sort((x, y) => x.time - y.time);
      if (!markersApi) markersApi = LW.createSeriesMarkers(series, ms); else markersApi.setMarkers(ms);
      if (opts.onMarkers) opts.onMarkers({ total: all.length, inView: inView.length, labeled: labeled.size });
    }
    chart.timeScale().subscribeVisibleTimeRangeChange(debounce(() => { if (wallets.length) renderMarkers(); }, 150));

    // timeframe buttons
    const tfs = document.createElement('div'); tfs.className = 'tfs';
    Object.keys(TF_SEC).forEach(k => { const b = document.createElement('button'); b.type = 'button'; b.className = 'tf'; b.dataset.tf = k; b.textContent = k; b.addEventListener('click', () => setTf(k, true)); tfs.appendChild(b); });
    const back = document.createElement('button'); back.type = 'button'; back.className = 'tf back'; back.textContent = '⌖ Range'; back.title = 'Bring the selected range back into view';
    back.addEventListener('click', () => { const w = windows[selected] || windows[0]; if (w && w.from && w.to) focus(w.from, w.to, null); });
    tfs.appendChild(back);
    el.appendChild(tfs);

    return {
      setWindows(ws, sel) { windows = normWins(ws); selected = sel; place(); },
      setExit(v) { exitSec = sec(v); place(); },
      setMarker(v) { marker = sec(v); place(); },
      setWalletMarkers(list) { wallets = list || []; renderMarkers(); },
      focus: (from, to, exit) => focus(sec(from), sec(to), sec(exit)),
      setTf, init: async () => { await setTf(autoTf(now - created), false); },
      fmtMcap,
      candles: () => [...data.values()].sort((x, y) => x.time - y.time),   // loaded candles in market cap, oldest first
    };
  };
})();
