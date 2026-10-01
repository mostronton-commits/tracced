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
    return '<svg class="dspark ' + (cum >= 0 ? 'up' : 'down') + '" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" aria-hidden="true">'
      + '<path class="a" d="' + line + ' L' + W + ' ' + zero + ' L0 ' + zero + ' Z"/><path class="z" d="M0 ' + zero + ' H' + W + '"/><path class="l" d="' + line + '"/></svg>'
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
  function recentHtml(list) {
    if (!list || !list.length) return '';
    const ago = ms => { const m = (Date.now() - ms) / 60000; return m < 60 ? Math.max(1, Math.round(m)) + 'm' : m < 1440 ? Math.round(m / 60) + 'h' : Math.round(m / 1440) + 'd'; };
    return '<table class="drecent"><thead><tr><th>Token</th><th class="num">PnL</th><th class="num">ROI</th><th></th><th class="num">Last</th></tr></thead><tbody>'
      + list.slice(0, 8).map(t => '<tr><td><a href="/token?mint=' + encodeURIComponent(t.mint) + '" title="Open ' + esc(t.symbol || t.mint) + ' in tracced">' + esc(t.symbol || short(t.mint)) + '</a></td>'
        + '<td class="num mono ' + (t.realized_usd > 0 ? 'pos' : (t.realized_usd < 0 ? 'neg' : '')) + '">' + (t.realized_usd == null ? '—' : money(t.realized_usd)) + '</td>'
        + '<td class="num mono">' + (t.roi == null ? '—' : (t.roi > 0 ? '+' : '') + Math.round(t.roi) + '%') + '</td>'
        + '<td><span class="st st-' + t.state.replace(' ', '-') + '">' + t.state + '</span></td>'
        + '<td class="num muted">' + ago(t.last_ms) + '</td></tr>').join('') + '</tbody></table>';
  }
  // box: where the block goes; info: the i beside the heading, which carries how it was counted
  function render(all, period, box, info) {
    const p = (all.periods && all.periods[period]) || all;
    const sol = (window.EarlyCur && EarlyCur.get()) === 'sol' && p.pnl_sol != null;
    const cls = p.pnl_usd > 0 ? 'pos' : (p.pnl_usd < 0 ? 'neg' : '');
    const day = x => x ? '<b class="' + (x.usd >= 0 ? 'pos' : 'neg') + '">' + money(x.usd) + '</b><small>' + utcDay(x.ms) + '</small>' : '<b>—</b>';
    if (info) {
      info.title = 'Counted by tracced from ' + nf(p.swaps) + ' swaps on every token' + (all.partial ? ', the latest ones only, back to ' + EarlyTZ.fmt(all.oldest_ms || p.since_ms, false) : '')
        + '. A position counts as closed once 99% of it is sold.'
        + (p.unbacked_tokens ? ' ' + plural(p.unbacked_tokens, 'token') + ' sold without a buy in these days ' + (p.unbacked_tokens === 1 ? 'is' : 'are') + ' left out: the cost is unknown.' : '');
      info.hidden = !p.swaps;
      info.classList.toggle('warn', !!(all.partial || p.unbacked_tokens));
    }
    box.innerHTML = !p.swaps ? '<p class="dline muted small">No swaps in ' + p.days + ' days.</p>' :
      '<div class="dhero"><div><span class="lbl">PnL</span><b class="big ' + cls + '">' + (sol ? EarlyCur.solHtml(p.pnl_sol) : money(p.pnl_usd)) + '</b></div>'
      + '<div class="r" title="' + p.closed + ' closed positions · win streak ' + p.win_streak + ' d, loss streak ' + p.loss_streak + ' d"><span class="lbl">Win rate</span><b class="big">' + (p.win_rate == null ? '—' : Math.round(p.win_rate * 100) + '%') + '</b>'
      + '<span class="sub"><span class="pos">' + p.wins + 'W</span> <span class="neg">' + p.losses + 'L</span></span></div></div>'
      + spark(p)
      + '<div class="dgrid">'
      + '<div><span>Volume</span><b>' + money(p.volume_usd) + '</b></div>'
      + '<div><span>Buys / sells</span><b>' + nf(p.buys) + ' / ' + nf(p.sells) + '</b></div>'
      + '<div><span>Avg hold</span><b>' + holdText(p.avg_hold_min) + '</b></div>'
      + '<div><span>Best day</span>' + day(p.best_day) + '</div>'
      + '<div><span>Worst day</span>' + day(p.worst_day) + '</div>'
      + '<div title="The deepest fall of the running PnL in these days"><span>Drawdown</span><b class="' + (p.max_drawdown_usd ? 'neg' : '') + '">' + (p.max_drawdown_usd ? money(-p.max_drawdown_usd) : '$0') + '</b></div>'
      + '</div>'
      + (distHtml(p) ? '<h5>Closed positions <span class="muted">' + ((p.wins || 0) + (p.losses || 0) || '') + '</span></h5>' + distHtml(p) : '')
      + (all.heat ? '<h5>Active hours · ' + ((window.EarlyTZ && EarlyTZ.get() === 'local') ? 'your time' : 'UTC') + '</h5>' + heatHtml(all.heat) : '')
      + (all.recent && all.recent.length ? '<h5>Recent tokens <span class="muted">' + nf(p.tokens) + ' · ' + nf(p.open) + ' open</span></h5>' + recentHtml(all.recent) : '');
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
  window.EarlyCard = { render, identicon };
})();
