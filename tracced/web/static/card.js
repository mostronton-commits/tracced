/* The wallet card's "All tokens" block, the same on a result and in Lists: PnL and win rate, the curve of the
   period, closed positions, active hours, recent tokens. Numbers first, words only where a number needs one; how
   it is counted sits behind the i. Also the picture made from an address, for wallets without a name. */
(function () {
  const esc = t => EarlyTags.esc(t), fm = v => EarlyUI.fmtShort(v);
  const short = w => w.slice(0, 6) + '…' + w.slice(-4);
  const money = v => (v == null || isNaN(v) ? '—' : (v < 0 ? '-$' : '$') + fm(Math.abs(v)));
  const holdText = m => m == null ? '—' : m < 60 ? Math.round(m) + ' min' : m < 1440 ? (m / 60).toFixed(m < 600 ? 1 : 0) + ' h' : Math.round(m / 1440) + ' d';
  const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const utcDay = ms => { const d = new Date(ms); return MON[d.getUTCMonth()] + ' ' + d.getUTCDate(); };
  const nf = v => (+v || 0).toLocaleString('en-US');

  function spark(p) {
    // cumulative realized PnL over the period, a point at the end of every day that had a sale
    const days = p.daily || [], W = 400, H = 92, DAYMS = 86400000, t0 = p.since_ms, t1 = p.since_ms + p.days * DAYMS;
    if (!days.length) return '';
    let cum = 0;
    const pts = [[t0, 0]];
    days.forEach(d => { cum += d[1]; pts.push([Math.min(d[0] + DAYMS, t1), cum]); });
    pts.push([t1, cum]);
    const ys = pts.map(q => q[1]), lo = Math.min(0, ...ys), hi = Math.max(0, ...ys), span = (hi - lo) || 1;
    const X = t => ((t - t0) / (t1 - t0)) * W, Y = v => 5 + (H - 10) * (1 - (v - lo) / span);
    const line = pts.map((q, i) => (i ? 'L' : 'M') + X(q[0]).toFixed(1) + ' ' + Y(q[1]).toFixed(1)).join(' ');
    const zero = Y(0).toFixed(1);
    // under the pointer (custdev 01.10): the day it points at, what that day made, the running total after it
    let run = 0;
    const marks = days.map(d => { run += d[1]; const e = Math.min(d[0] + DAYMS, t1); return [+(X(e) / W * 100).toFixed(2), +(Y(run) / H * 100).toFixed(2), utcDay(d[0]), d[1], run]; });
    return '<div class="dsparkw" data-marks="' + esc(JSON.stringify(marks)) + '">'
      + '<svg class="dspark ' + (cum >= 0 ? 'up' : 'down') + '" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">'
      + '<path class="a" d="' + line + ' L' + W + ' ' + zero + ' L0 ' + zero + ' Z"/><path class="z" d="M0 ' + zero + ' H' + W + '"/><path class="l" d="' + line + '"/></svg>'
      + '<i class="dsp-dot" hidden></i><span class="dsp-tip" hidden></span></div>'
      + '<div class="dspark-x"><span>' + utcDay(t0) + '</span><span>' + utcDay(t1) + '</span></div>';
  }
  const DIST = [['>500', '> 500%', 'g3'], ['200-500', '200–500%', 'g2'], ['50-200', '50–200%', 'g1'], ['0-50', '0–50%', 'g0'], ['-50-0', '−50–0%', 'r0'], ['<-50', '< −50%', 'r1']];
  function distHtml(p) {
    // closed positions by result, big wins on the left, big losses on the right: the count sits on each wide part,
    // hover (or tap) any part for its range and share
    const d = p.dist || {}, n = DIST.reduce((a, x) => a + (d[x[0]] || 0), 0);
    if (!n) return '';
    return '<div class="ddist"><div class="dbar">' + DIST.map(x => { const k = d[x[0]] || 0; if (!k) return '';
        const pct = Math.round(k / n * 100), tip = x[1] + ': ' + k + (k === 1 ? ' position' : ' positions') + ', ' + pct + '%';
        return '<i class="' + x[2] + '" style="flex:' + k + '" title="' + tip + '" tabindex="0" aria-label="' + tip + '">' + (pct >= 10 ? k : '') + '</i>'; }).join('')
      + '</div><div class="dends"><span>big wins</span><span>big losses</span></div></div>';
  }
  function heatHtml(heat) {
    // when the wallet trades, by weekday and hour; the grid comes in UTC and follows the footer's time zone
    if (!heat) return '';
    const off = (window.EarlyTZ && EarlyTZ.get() === 'local') ? -Math.round(new Date().getTimezoneOffset() / 60) : 0;
    const g = Array.from({ length: 7 }, () => Array(24).fill(0));
    heat.forEach((row, d) => row.forEach((n, h) => { const i = ((d * 24 + h + off) % 168 + 168) % 168; g[Math.floor(i / 24)][i % 24] += n; }));
    const max = Math.max(1, ...g.map(r => Math.max(...r))), D = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const ampm = h => (h % 12 || 12) + (h < 12 ? 'am' : 'pm');
    return '<div class="dheat">' + g.map((row, d) => '<div class="hr"><span>' + D[d] + '</span>' + row.map((n, h) =>
        '<i style="--a:' + (n ? (0.18 + 0.82 * n / max).toFixed(2) : 0) + '" title="' + D[d] + ' ' + ampm(h) + '–' + ampm((h + 1) % 24) + ' · ' + n + ' swap' + (n === 1 ? '' : 's') + '"></i>').join('') + '</div>').join('')
      + '<div class="hx"><span></span>' + [0, 3, 6, 9, 12, 15, 18, 21].map(h => '<b>' + ampm(h) + '</b>').join('') + '</div></div>';
  }
  // the recent tokens of the card on screen (one card at a time): a click on a row draws that token's chart under it
  let RECENT = [], TV = 'recent', LASTTV = null;
  try { TV = localStorage.getItem('early:tv') === 'best' ? 'best' : 'recent'; } catch (e) {}
  /* the tokens under the numbers: the latest ones, or the ones it made its PnL on (owner, 08.10: «перемикач, який
     показує, як на FOMO, кращі трейди»). Best is the period's own when it has one (a list's month), else the 30 days */
  function tokensHtml(all, p) {
    const best = (p && p.best_tokens) || (all && all.best_tokens) || [], recent = (all && all.recent) || [];
    if (!best.length && !recent.length) return '';
    LASTTV = { all, p };
    const view = (TV === 'best' && best.length) || !recent.length ? 'best' : 'recent';
    const btn = (v, t) => '<button type="button" data-tv="' + v + '"' + (view === v ? ' class="on"' : '') + '>' + t + '</button>';
    return '<div class="dtv-h"><h5>' + (view === 'best' ? 'Best trades' : 'Recent tokens') + '</h5>'
      + (best.length && recent.length ? '<span class="seg sm" role="tablist" aria-label="Which tokens">' + btn('recent', 'Recent') + btn('best', 'Best') + '</span>' : '')
      + '</div>' + recentHtml(view === 'best' ? best : recent);
  }
  document.addEventListener('click', e => {
    const b = e.target.closest && e.target.closest('.dtv [data-tv]'); if (!b || !LASTTV) return;
    TV = b.dataset.tv; try { localStorage.setItem('early:tv', TV); } catch (x) {}
    b.closest('.dtv').innerHTML = tokensHtml(LASTTV.all, LASTTV.p);
    if (window.EarlyUI) EarlyUI.use('card-view', { v: 'tokens-' + TV });
    if (window.EarlyTZ) EarlyTZ.apply();
  });
  function recentHtml(list) {
    if (!list || !list.length) return '';
    RECENT = list.slice(0, 8);
    const ago = ms => { const m = (Date.now() - ms) / 60000; return m < 60 ? Math.max(1, Math.round(m)) + 'm' : m < 1440 ? Math.round(m / 60) + 'h' : Math.round(m / 1440) + 'd'; };
    return '<table class="drecent"><thead><tr><th>Token</th><th class="num">PnL</th><th class="num">ROI</th><th></th><th class="num">Last</th></tr></thead><tbody>'
      + RECENT.map((t, i) => '<tr class="rt" data-i="' + i + '" tabindex="0" title="Show ' + esc(t.symbol || 'this token') + '\'s chart with this wallet\'s buys and sells"><td><b class="rts">' + esc(t.symbol || short(t.mint)) + '</b></td>'
        + '<td class="num mono ' + (t.realized_usd > 0 ? 'pos' : (t.realized_usd < 0 ? 'neg' : '')) + '">' + (t.realized_usd == null ? '—' : money(t.realized_usd)) + '</td>'
        + '<td class="num mono">' + (t.roi == null ? '—' : (t.roi > 0 ? '+' : '') + Math.round(t.roi) + '%') + '</td>'
        + '<td><span class="st st-' + t.state.replace(' ', '-') + '">' + t.state + '</span></td>'
        + '<td class="num muted">' + ago(t.last_ms) + '</td></tr>').join('') + '</tbody></table>';
  }
  // box: where the block goes; info: the i beside the heading, which carries how it was counted
  // opts.recent false: the recent tokens go elsewhere (a result's card switches its trades and them; owner, 04.10)
  function render(all, period, box, info, opts) {
    const p = (all.periods && all.periods[period]) || all;
    const sol = (window.EarlyCur && EarlyCur.get()) === 'sol' && p.pnl_sol != null;
    const cls = p.pnl_usd > 0 ? 'pos' : (p.pnl_usd < 0 ? 'neg' : '');
    const day = x => x ? '<b class="' + (x.usd >= 0 ? 'pos' : 'neg') + '">' + money(x.usd) + '</b><small>' + utcDay(x.ms) + '</small>' : '<b>—</b>';
    if (info) {                                  // short (custdev 01.10: too much text in the tooltips)
      // owner, 07.10: profit counts on the day of the sale, at what the wallet paid, even for a token bought earlier
      info.title = 'PnL counts every sale ' + (p.label ? 'in ' + p.label : 'in these ' + p.days + ' days') + ' at what the wallet paid, even if it bought earlier. From '
        + nf(p.swaps) + ' swaps on every token' + (all.partial ? ', latest only, since ' + EarlyTZ.fmt(all.oldest_ms || p.since_ms, false) : '')
        + '. Closed = 99% sold.' + (p.unbacked_tokens ? ' ' + plural(p.unbacked_tokens, 'token') + ' sold with no buy found left out.' : '');
      info.hidden = !p.swaps;
      info.classList.toggle('warn', !!(all.partial || p.unbacked_tokens));
    }
    box.innerHTML = !p.swaps ? '<p class="dline muted small">No swaps ' + (p.label ? 'in ' + p.label : 'in ' + p.days + ' days') + '.</p>' :
      '<div class="dhero"><div><span class="lbl">PnL</span><b class="big ' + cls + '">' + (sol ? EarlyCur.solHtml(p.pnl_sol) : money(p.pnl_usd)) + '</b></div>'
      + '<div class="r" title="' + plural(p.closed, 'closed position') + '"><span class="lbl">Win rate</span><b class="big">' + (p.win_rate == null ? '—' : Math.round(p.win_rate * 100) + '%') + '</b>'
      + '<span class="sub"><span class="pos">' + p.wins + 'W</span> <span class="neg">' + p.losses + 'L</span></span></div></div>'
      + spark(p)
      + '<div class="dgrid">'
      + '<div><span>Volume</span><b>' + money(p.volume_usd) + '</b></div>'
      + '<div><span>Buys / sells</span><b>' + nf(p.buys) + ' / ' + nf(p.sells) + '</b></div>'
      + '<div><span>Tokens</span><b>' + nf(p.tokens) + '</b><small>' + nf(p.open) + ' open</small></div>'
      + '<div><span>Avg hold</span><b>' + holdText(p.avg_hold_min) + '</b></div>'
      + '<div><span>Best day</span>' + day(p.best_day) + '</div>'
      + '<div title="Deepest fall of the running PnL"><span>Drawdown</span><b class="' + (p.max_drawdown_usd ? 'neg' : '') + '">' + (p.max_drawdown_usd ? money(-p.max_drawdown_usd) : '$0') + '</b></div>'
      + '</div>'
      + (distHtml(p) ? '<h5>Closed positions <span class="muted">' + ((p.wins || 0) + (p.losses || 0) || '') + '</span></h5>' + distHtml(p) : '')
      + (all.heat ? '<h5>Active hours · ' + ((window.EarlyTZ && EarlyTZ.get() === 'local') ? 'your time' : 'UTC') + '</h5>' + heatHtml(all.heat) : '')
      + (!(opts && opts.recent === false) ? '<div class="dtv">' + tokensHtml(all, p) + '</div>' : '');
    if (window.EarlyTZ) EarlyTZ.apply();
  }
  function identicon(w) {
    // a picture made from the address, so wallets without a name are still told apart at a glance
    let h = 2166136261;
    for (let i = 0; i < w.length; i++) h = Math.imul(h ^ w.charCodeAt(i), 16777619) >>> 0;
    const hue = h % 360, cells = [];
    for (let y = 0; y < 5; y++) for (let x = 0; x < 3; x++) {
      h = Math.imul(h ^ (x * 7 + y), 16777619) >>> 0;
      if (h & 4) { cells.push([x, y]); if (x < 2) cells.push([4 - x, y]); }
    }
    return '<svg viewBox="0 0 5 5" shape-rendering="crispEdges"><rect width="5" height="5" fill="hsl(' + hue + ' 70% 95%)"/>'
      + cells.map(c => '<rect x="' + c[0] + '" y="' + c[1] + '" width="1" height="1" fill="hsl(' + hue + ' 55% 46%)"/>').join('') + '</svg>';
  }
  // a phone has no hover: a tap on a part of the closed-positions bar says what the mouse would have shown
  document.addEventListener('click', e => { const seg = e.target.closest('.ddist .dbar i'); if (seg && window.EarlyUI) EarlyUI.toast(esc(seg.title)); });
  // the PnL curve answers the pointer (a finger too): the nearest day with a sale, its result and the total after it
  function sparkAt(e) {
    const w = e.target.closest && e.target.closest('.dsparkw'); if (!w) return;
    let m; try { m = JSON.parse(w.dataset.marks || '[]'); } catch (x) { return; }
    if (!m.length) return;
    const r = w.getBoundingClientRect(), fx = (e.clientX - r.left) / r.width * 100;
    const k = m.reduce((b, q) => Math.abs(q[0] - fx) < Math.abs(b[0] - fx) ? q : b, m[0]);
    const dot = w.querySelector('.dsp-dot'), tip = w.querySelector('.dsp-tip');
    dot.style.left = k[0] + '%'; dot.style.top = k[1] + '%'; dot.hidden = false;
    tip.innerHTML = '<b>' + k[2] + '</b> <span class="' + (k[3] >= 0 ? 'pos' : 'neg') + '">' + (k[3] > 0 ? '+' : '') + money(k[3]) + '</span><small>total ' + money(k[4]) + '</small>';
    tip.hidden = false;
    tip.style.left = Math.min(Math.max(k[0], 14), 86) + '%';
  }
  const sparkOff = e => { const w = e.target.closest && e.target.closest('.dsparkw'); if (w) w.querySelectorAll('.dsp-dot, .dsp-tip').forEach(x => { x.hidden = true; }); };
  document.addEventListener('pointermove', sparkAt);
  document.addEventListener('pointerdown', sparkAt);
  document.addEventListener('pointerout', e => { if (e.target.closest && e.target.closest('.dsparkw') && !(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.dsparkw'))) sparkOff(e); });
  /* Another token's chart from the card (owner, 04.10: «реалізуй, як бачиш, я потім поправлю»): the row opens a small
     chart of that token right under it, on the hours of this wallet's trades, with its buys and sells marked the way
     the result's chart marks them. The trades come with the 30 days; the candles cost what any chart costs. */
  function tokenChart(row, t) {
    const td = row.querySelector('td'), tr = (t.trades || []).map(x => ({ t: x[0], side: x[1] === 'b' ? 'buy' : 'sell', usd: x[2], qty: x[3] || 0 }));
    const buys = tr.filter(x => x.side === 'buy'), sells = tr.filter(x => x.side === 'sell');
    const sum = a => a.reduce((s, x) => s + (x.usd || 0), 0);
    td.innerHTML = '<div class="chartbox mini"></div><div class="rtfoot"><span><b class="up">↑' + buys.length + '</b> ' + money(sum(buys))
      + ' <b class="dn">↓' + sells.length + '</b> ' + money(sum(sells)) + '</span><a href="/token?mint=' + encodeURIComponent(t.mint) + '">Open ' + esc(t.symbol || 'the token') + ' in tracced</a></div>';
    const box = td.querySelector('.chartbox');
    if (!window.EarlyChart || !window.LightweightCharts) { box.outerHTML = '<p class="muted small">The chart opens on the token\'s page.</p>'; return; }
    const first = tr.length ? tr[0].t : t.last_ms, last = tr.length ? tr[tr.length - 1].t : t.last_ms;
    const ch = EarlyChart(box, { mint: t.mint, symbol: t.symbol || '', created: first - 6 * 3600000, now: Date.now(), windows: [] });
    ch.setWalletMarkers([{ wallet: 'card', trades: tr }]);
    ch.focus(first, last, null);
    if (window.EarlyUI) EarlyUI.use('card-token-chart');
  }
  function toggleToken(row) {
    const body = row.parentElement, open = row.classList.contains('open');
    body.querySelectorAll('tr.rtc').forEach(x => x.remove());
    body.querySelectorAll('tr.rt.open').forEach(x => x.classList.remove('open'));
    if (open) return;
    const t = RECENT[+row.dataset.i]; if (!t) return;
    row.classList.add('open');
    const c = document.createElement('tr'); c.className = 'rtc'; c.innerHTML = '<td colspan="5"></td>';
    row.after(c);
    tokenChart(c, t);
  }
  document.addEventListener('click', e => { const r = e.target.closest('table.drecent tr.rt'); if (r && !e.target.closest('a')) toggleToken(r); });
  document.addEventListener('keydown', e => { const r = e.target.closest && e.target.closest('table.drecent tr.rt'); if (r && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggleToken(r); } });
  /* On a phone the card is a sheet from the bottom (owner, 07.10, «like FOMO»): a tap on the dimmed page above it closes
     it, and so does pulling its head down. Whatever closes it goes through its own ×, so each page keeps one way out */
  const PHONE = () => innerWidth <= 640;
  const openSheet = () => document.querySelector('.drawer.wcard:not([hidden])');
  document.addEventListener('click', e => {
    const s = PHONE() && e.target === document.body && openSheet();
    const x = s && s.querySelector('#dclose'); if (x) x.click();
  });
  let drag = null;
  document.addEventListener('touchstart', e => {
    const h = PHONE() && e.target.closest && e.target.closest('.wcard .drawer-head');
    if (!h || e.target.closest('button, a, input')) return;
    drag = { s: h.closest('.wcard'), y: e.touches[0].clientY, dy: 0 };
    drag.s.style.transition = 'none';
  }, { passive: true });
  document.addEventListener('touchmove', e => {
    if (!drag) return;
    drag.dy = Math.max(0, e.touches[0].clientY - drag.y);
    drag.s.style.transform = drag.dy ? 'translateY(' + drag.dy + 'px)' : '';
  }, { passive: true });
  const dropDrag = () => {
    if (!drag) return;
    const { s, dy } = drag; drag = null;
    s.style.transition = 'transform .2s ease-out';
    const done = () => { s.style.transition = ''; s.style.transform = ''; };
    if (dy > 90) { s.style.transform = 'translateY(100%)'; setTimeout(() => { const x = s.querySelector('#dclose'); if (x) x.click(); done(); }, 200); }
    else { s.style.transform = ''; setTimeout(done, 200); }
  };
  document.addEventListener('touchend', dropDrag);
  document.addEventListener('touchcancel', dropDrag);
  window.EarlyCard = { render, identicon, recent: all => { const h = tokensHtml(all, null); return h ? '<div class="dtv">' + h + '</div>' : ''; } };
})();
