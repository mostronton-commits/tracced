/* The result under the token's chart (owner, 09.10: «щоб все було без оновлення сторінки»). The page mounts one result
   at a time, when its tab opens or its run ends, and unmounts it when another tab opens: listeners on the document, the
   pop-ups, the timers and the background checks of the last one stop with it, so a weak computer runs one result, never
   three. This was the inline script of the old result page; what it took from the server comes from #rcfg now. */
(function () {
  function mount(root, ch) {
    const CFG = JSON.parse(root.querySelector('#rcfg').textContent);
    const V2 = document.documentElement.dataset.design === 'v2';   // design v2 (26.10): its own rows, head, toolbar and card
    const off = []; let alive = true;
    const on = (t, ev, fn, o) => { t.addEventListener(ev, fn, o); off.push(() => t.removeEventListener(ev, fn, o)); };
    const later = (fn, ms) => { const id = setTimeout(() => { if (alive) fn(); }, ms); off.push(() => clearTimeout(id)); return id; };
    const table = document.getElementById('facts'), tbody = table.tBodies[0], jobId = table.dataset.id;
    const shown = document.getElementById('shown');
    /* The rows arrive as data, not as markup: the page draws the ones on screen, a hundred at a time, and sorts,
       filters, selects and exports on the numbers. Drawn in full, 2,500 wallets were 75,000 elements, and a phone
       with little memory stalled on them. */
    const RAW = JSON.parse(document.getElementById('rowsdata').textContent);
    const all = RAW.r.map(a => { const o = {}; RAW.f.forEach((k, i) => { o[k] = a[i]; }); o.tags = o.tags ? o.tags.split(' ') : []; return o; });
    const byW = new Map(all.map(o => [o.w, o]));
    let order = all.slice(), pass = all.slice();                   // order: the current sort; pass: what the filters let through
    document.querySelectorAll('#filters [data-hide]').forEach(b => {                         // the filter chips double as the legend
      const ic = EarlyTags.ICON[b.dataset.hide]; if (ic) b.insertAdjacentHTML('afterbegin', ic);
    });
    const pinned = new Set();                                       // pinned = wallets shown on the chart: never hidden by filters
    const solnote = document.querySelector('.solnote');             // an older result has no SOL amounts; say so instead of showing dollars silently
    if (solnote && window.EarlyCur && EarlyCur.get() === 'sol') solnote.hidden = false;
    // no row checkboxes (owner, 02.10): a wallet goes to a list by its star, and Export takes what the filters show
    const FKEY = 'early:filters:' + jobId;
    try { localStorage.removeItem('early:sel:' + jobId); } catch (e) {}
    // filters (owner, 02.10): a funnel by each column with «from … to …», the tags under the Wallet funnel.
    // r: {column: [from, to]}, null = open on that side
    const RANGES = {
      inv: { t: 'Bought', u: '$', step: 10, hint: 'all its buys of this token, in dollars', get: o => +o.tot || +o.inv || 0 },   // the number the column shows (owner, 11.10)
      sold: { t: 'Sold', u: '%', step: 5, hint: 'share of its tokens sold', get: o => +o.sold || 0 },
      real: { t: 'PnL', u: '$', step: 10, hint: 'realized, in dollars; a loss is negative', get: o => +o.real || 0 },
      mult: { t: 'ROI', u: '×', step: 0.5, hint: 'average exit ÷ average entry', get: o => +o.mult || 0 },
      hold: { t: 'Held', u: 'min', step: 5, hint: 'how long it held what it sold, weighted by amount', get: o => o.hold == null ? null : +o.hold },
      buys: { t: 'Buys', u: '', step: 1, hint: 'its buys on this token', get: o => +o.buys || 0 },
    };
    const HIDE_TAGS = Object.keys(CFG.tags).filter(x => !['seen-before', 'pre-range', 're-bought'].includes(x));
    const FDEF = { r: {}, q: '', hide: [], funder: '', bundle: '', repeat: false, only: '', mine: false, profit: false, exits: false };
    const fresh0 = () => JSON.parse(JSON.stringify(FDEF));
    const f = fresh0();
    try {
      const saved = JSON.parse(localStorage.getItem(FKEY) || '{}');
      Object.keys(FDEF).forEach(k => { if (k in saved) f[k] = saved[k]; });
      // a filter kept from before the funnels (inv, invMax, pnl, sold, buysMax, hold, holdMax) still applies
      const num = v => (v === null || v === undefined || v === 0 || v === '') ? null : +v;
      if (!saved.r && Object.keys(saved).length) {
        f.r = { inv: [num(saved.inv), num(saved.invMax)], real: [saved.pnl === null || saved.pnl === undefined ? null : +saved.pnl, null],
                sold: [num(saved.sold), null], buys: [null, num(saved.buysMax)], hold: [num(saved.hold), num(saved.holdMax)] };
      }
    } catch (e) {}
    if (!f.r || typeof f.r !== 'object') f.r = {};
    Object.keys(f.r).forEach(k => { const v = f.r[k]; if (!RANGES[k] || !Array.isArray(v) || (v[0] == null && v[1] == null)) delete f.r[k]; });
    f.hide = (f.hide || []).filter(x => HIDE_TAGS.includes(x));     // a saved hide these chips no longer offer could not be undone
    f.exits = f.profit = f.repeat = f.mine = false; f.only = f.q = f.bundle = '';   // a finding's filter and a search are for this visit
    const saveF = () => { try { localStorage.setItem(FKEY, JSON.stringify(f)); } catch (e) {} };
    // saved sets of filters (owner, 12.10, after Phanes' «Views»): the numbers, the hidden tags, the toggles and the order,
    // kept in this browser for every analysis. The wallet search and a funder or bundle pick belong to one analysis: out
    const VKEY = 'early:views', MAX_VIEWS = 8;
    const loadViews = () => { try { const v = JSON.parse(localStorage.getItem(VKEY) || '[]'); return Array.isArray(v) ? v.filter(x => x && x.name && x.f && x.sort) : []; } catch (e) { return []; } };
    const saveViews = v => { try { localStorage.setItem(VKEY, JSON.stringify(v.slice(0, MAX_VIEWS))); } catch (e) {} };
    const viewOf = () => ({ f: { r: JSON.parse(JSON.stringify(f.r)), hide: f.hide.slice(), mine: !!f.mine, profit: !!f.profit, exits: !!f.exits,
      repeat: !!f.repeat, only: f.only || '' }, sort: [sortKey, sortDir] });
    const ftoggle = document.getElementById('ftoggle');
    const isOn = k => { const v = f.r[k]; return !!v && (v[0] != null || v[1] != null); };
    function syncHeads() {                                      // which funnels hold a filter, and the money unit's mark
      document.querySelectorAll('#facts .hfil').forEach(b => {
        const k = b.dataset.fil, on = k === 'hold' ? isOn('hold') || isOn('buys') : isOn(k);
        b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on));
      });
      const u = document.querySelector('#facts .hcur');
      if (u) u.innerHTML = (window.EarlyCur && EarlyCur.get() === 'sol') ? '<span class="insol"></span>' : '$';
      fillPanel();
    }
    function nActive() { return Object.keys(f.r).filter(isOn).length + [f.q, f.exits, f.profit, f.funder, f.bundle, f.repeat, f.only, f.mine].filter(Boolean).length + f.hide.length; }

    // what arrives after the page: the background checks (funders, ages, names) and the account (repeats, lists)
    let funders = {}, bundle = {}, crossings = {}, idents = {}, ages = {}, ageDone = false, palette = new Map();
    let LAUNCH = null;                                          // the launch check: its summary and tags, after the page
    let DORM = {};                                             // wallet → days it was quiet before its first buy here
    let services = new Set();                                  // funders that are exchanges or apps: they make no bundle
    // known exchange hot wallets: the funder column names the exchange, and one click shows every
    // wallet funded from it, all its addresses together
    const EXCH = CFG.exch || {};
    const FLAB = CFG.flab || {};                         // other named funders (InsightX): apps, casinos — the card only
    const KIND_TXT = { exchange: 'an exchange', dex: 'a trading app', gambling: 'a gambling site', bridge: 'a bridge', defi: 'a DeFi app', payments: 'a payments app', mev: 'an MEV bot' };
    const fundKey = w => { const x = funders[w]; return x && EXCH[x] ? 'x:' + EXCH[x][0] : (x || ''); };
    const fundLabel = k => k && k.startsWith('x:') ? k.slice(2) : short(k);
    const onChart = [], MAX_ON_CHART = 10, BUY_C = document.documentElement.dataset.design === 'v2' ? '#5AD46A' : '#34D399', SELL_C = document.documentElement.dataset.design === 'v2' ? '#FF6470' : '#F87171';
    // no violet: on this page it means a repeat; orange first, the bundle tag's own colour
    const BUNDLE_PAL = ['#FDBA74', '#7DD3FC', '#F9A8D4', '#FCD34D', '#5EEAD4', '#BEF264', '#93C5FD', '#FDA4AF'];
    const BUNDLE_MIN = CFG.bundle_min, BURST_MS = CFG.burst_ms, TAGDEF = CFG.tags;
    const CHAIN = EarlyIcon('link', 'lnk');   // two links: the repeat marker in the row and the heading of its block in the card
    const short = w => w.slice(0, 6) + '…' + w.slice(-4), esc = EarlyTags.esc, fm = EarlyUI.fmtShort;
    const money = v => (v == null || isNaN(v) ? '—' : (v < 0 ? '-$' : '$') + fm(Math.abs(v)));
    const holdText = m => m == null ? '—' : m < 60 ? Math.round(m) + ' min' : m < 1440 ? (m / 60).toFixed(m < 600 ? 1 : 0) + ' h' : Math.round(m / 1440) + ' d';
    const plural = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
    // ROI as a trader says it: 61.5× is +6,050%, the percent in the tooltip
    const roiX = m => m ? (m >= 100 ? Math.round(m).toLocaleString('en-US') : (+m).toFixed(1)) + '×' : '—';
    const roiPct = m => { const v = Math.round((m - 1) * 100); return (v > 0 ? '+' : '') + v.toLocaleString('en-US') + '%'; };
    const SOLON = !!(window.EarlyCur && EarlyCur.get() === 'sol');
    const MAXR = all.reduce((m, o) => Math.max(m, Math.abs(o.real || 0)), 0);     // the PnL bar is scaled to the largest one
    function burst(ws) {
      // the wallets with at least BUNDLE_MIN - 1 more of the same funder born within BURST_MS of them, as on the server
      const t = ws.filter(w => ages[w] && ages[w].exact && ages[w].ms).map(w => [ages[w].ms, w]).sort((a, b) => a[0] - b[0]);
      const out = []; let lo = 0, hi = 0;
      for (let i = 0; i < t.length; i++) {
        while (t[i][0] - t[lo][0] > BURST_MS) lo++;
        hi = Math.max(hi, i);
        while (hi + 1 < t.length && t[hi + 1][0] - t[i][0] <= BURST_MS) hi++;
        if (hi - lo + 1 >= BUNDLE_MIN) out.push(t[i][1]);
      }
      return out;
    }
    function rebundle() {
      // wallets whose first SOL came from one funder shared by BUNDLE_MIN or more wallets here; one colour per funder.
      // An exchange or an app funds strangers at random times, so from one of them only the wallets born together count
      const groups = {};
      Object.entries(funders).forEach(([w, x]) => { (groups[x] = groups[x] || []).push(w); });
      bundle = {};
      Object.entries(groups).forEach(([x, ws]) => {
        let keep = ws;
        if (services.has(x) || EXCH[x]) {                     // most of them born together: a bundler here, so all of them
          const b = burst(ws), dated = ws.filter(w => ages[w] && ages[w].exact && ages[w].ms).length;
          keep = b.length * 2 > dated ? ws : b;
        }
        if (keep.length >= BUNDLE_MIN) keep.forEach(w => { bundle[w] = { funder: x, n: keep.length }; });
      });
      palette = new Map([...new Set(Object.values(bundle).map(b => b.funder))].sort().map((x, i) => [x, BUNDLE_PAL[i % BUNDLE_PAL.length]]));
    }
    const bundleColor = w => bundle[w] ? palette.get(bundle[w].funder) : null;
    function amount(usd, sol, cls) {
      // one amount in the unit the footer switch shows; a result saved before SOL was recorded keeps its dollars, dimmed
      if (!SOLON) return '<b class="mono ' + cls + '">' + money(usd) + '</b>';
      if (sol == null) return '<b class="mono amt nosol ' + cls + '" title="This result was saved before tracced recorded SOL amounts">' + money(usd) + '</b>';
      return '<b class="mono insol ' + cls + '">' + EarlyCur.sol(sol) + '</b>';
    }
    const QUIET = new Set(['seen-before', 'pre-range', 're-bought']);   // kept in the data, not shown: seen-before has its own mark
    // your own tags for a saved wallet, in the table as in the watchlist (owner, 04.10); a declaration, so the first
    // draw may call it before the account arrives
    function userTags(w) { return (me && me.wallets && me.wallets[w] && me.wallets[w].my_tags) || []; }
    function tagsHtml(o) {
      // a repeat, who the wallet is, then our rules as pictures with the rule in the tooltip
      const cx = crossings[o.w], idn = idents[o.w], b = bundle[o.w];
      let h = cx && cx.length ? '<button type="button" class="tag ico t-seen-before seen" title="Also an early buyer in ' + cx.length
        + ' of your saved analyses — click for the list" aria-label="Seen in ' + cx.length + ' of your other analyses">' + CHAIN + '</button>' : '';
      const ids = idn ? EarlyTags.idMarks(idn) : '';
      if (ids) h += '<span class="ids">' + ids + '</span>';
      o.tags.forEach(t => {
        if (QUIET.has(t)) return;
        h += t === 'bundle' && b ? bundChip(o.w, b) : EarlyTags.chip(t, TAGDEF[t]);
      });
      userTags(o.w).forEach(x => { h += '<span class="tag own" title="Your tag">' + esc(x) + '</span>'; });
      return h;
    }
    // the Funded by column is gone (owner, 02.10): a bundle's colour tells its wallets apart, a click shows that bundle alone
    const bundChip = (w, b) => '<button type="button" class="tag ico t-bundle bundb" data-bund="' + esc(b.funder) + '" style="--c:' + bundleColor(w)
      + '" title="One funder, ' + plural(b.n, 'wallet') + ' here: likely one operator · click to show them" aria-label="Bundle of ' + b.n + '">' + EarlyTags.ICON.bundle + '</button>';
    const cells = new Map();                                   // wallet → the tags markup last drawn for it
    const cardW = () => { const d = document.getElementById('drawer'); return d && !d.hidden ? d.dataset.w : ''; };   // the wallet whose card is open
    const STAR = w => { const on = inList(w); return '<button type="button" class="star' + (on ? ' on' : '') + '" aria-pressed="' + on + '" title="'
      + (on ? 'In your watchlist · click to change' : 'Add to your watchlist') + '" aria-label="' + (on ? 'In your watchlist' : 'Add to your watchlist') + '">' + EarlyIcon(on ? 'star-on' : 'star') + '</button>'; };
    const CHARTIC = EarlyIcon('chart');
    // a phone shows a wallet as one line, like a trading app's list (owner, 07.10, «like FOMO»): its picture, the
    // address and its marks, under them what it put in and how much it sold; PnL and ROI on the right. The picture is
    // drawn from the address once; the line is hidden on a wider screen, where the columns say the same
    const FACES = new Map(), face = w => { let f = FACES.get(w); if (!f) { f = EarlyCard.identicon(w); FACES.set(w, f); } return f; };
    const extra = o => o.tot > o.inv + 0.01;                   // it bought outside the range too: before it, after it or both
    const msub = o => (SOLON && o.totsol != null ? '<span class="insol">' + EarlyCur.sol(o.totsol) + '</span>' : money(o.tot || o.inv))
      + (extra(o) ? ' · ' + money(o.inv) + ' in range' : ' at ' + (o.entry ? fm(o.entry) : '—') + ' cap')
      + (o.sells == null ? '' : o.sold >= 99 ? ' · sold out' : o.sold > 0 ? ' · sold ' + soldPct(o.sold) : ' · holding all');
    /* ── design v2 (canvas Analysis4, 26.10) ──
       A row: the wallet's fingerprint, its name and address, its marks as small drawings; its trip from the average
       entry to the average exit on one log scale of caps for the whole result, the cap now as a tick; Bought, Sold, PnL
       with its bar, the multiple. Held, Buys / sells, First buy and Funded by come from Columns, which keeps the
       columns and their order in this browser. Nothing here runs without the v2 cookie */
    const AG = {
      clock: '<circle cx="8" cy="8" r="5.6"/><path d="M8 4.9 V8 L6 9.4"/>',
      renew: '<path d="M12.6 7 A4.8 4.8 0 1 0 12.4 10"/><path d="M12.8 3.8 V7 H9.6"/>',
      bot: '<rect x="3" y="5.4" width="10" height="7.8" rx="2"/><path d="M8 5.4 V2.8"/><circle cx="6.2" cy="9.2" r="0.9" fill="currentColor" stroke="none"/><circle cx="9.8" cy="9.2" r="0.9" fill="currentColor" stroke="none"/>',
      transfer: '<path d="M8 2.6 V9.4"/><path d="M5.3 6.8 L8 9.5 L10.7 6.8"/><path d="M3 10.8 V13.2 H13 V10.8"/>',
      dev: '<path d="M5.8 4.6 L2.6 8 L5.8 11.4"/><path d="M10.2 4.6 L13.4 8 L10.2 11.4"/>',
      sniper: '<circle cx="8" cy="8" r="4.6"/><path d="M8 1.8 V4.4 M8 11.6 V14.2 M1.8 8 H4.4 M11.6 8 H14.2"/>',
      fresh: '<path d="M8 13.4 V7.6"/><path d="M8 7.6 C8 4.8 9.8 3 12.8 3 C12.8 5.8 11 7.6 8 7.6 Z"/><path d="M8 9.6 C8 7.8 6.6 6.4 3.6 6.4 C3.6 8.4 5.2 9.6 8 9.6 Z"/>',
      bundle: '<path d="M2.8 5.2 L8 2.6 L13.2 5.2 V10.8 L8 13.4 L2.8 10.8 Z"/><path d="M2.8 5.2 L8 7.8 L13.2 5.2 M8 7.8 V13.4"/>',
      gem: '<path d="M4.6 3.2 H11.4 L13.6 6.4 L8 13 L2.4 6.4 Z"/><path d="M2.4 6.4 H13.6"/>',
      moon: '<path d="M12.8 9.8 A5.4 5.4 0 1 1 6.2 3.2 A4.4 4.4 0 0 0 12.8 9.8 Z"/>',
      link: '<path d="M7 4.6 L8.4 3.2 A2.5 2.5 0 0 1 12.8 7.6 L11.4 9"/><path d="M9 11.4 L7.6 12.8 A2.5 2.5 0 0 1 3.2 8.4 L4.6 7"/><path d="M6.4 9.6 L9.6 6.4"/>',
      filter: '<path d="M2.6 3.6 H13.4 L9.4 8.4 V12.6 L6.6 13.4 V8.4 Z"/>',
      star: '<path d="M8 2.4 L9.7 6 L13.6 6.4 L10.7 9 L11.5 12.9 L8 10.9 L4.5 12.9 L5.3 9 L2.4 6.4 L6.3 6 Z"/>',
      grip: '<circle cx="6" cy="4" r="0.9" fill="currentColor" stroke="none"/><circle cx="10" cy="4" r="0.9" fill="currentColor" stroke="none"/><circle cx="6" cy="8" r="0.9" fill="currentColor" stroke="none"/><circle cx="10" cy="8" r="0.9" fill="currentColor" stroke="none"/><circle cx="6" cy="12" r="0.9" fill="currentColor" stroke="none"/><circle cx="10" cy="12" r="0.9" fill="currentColor" stroke="none"/>',
      close: '<path d="M4.4 4.4 L11.6 11.6 M11.6 4.4 L4.4 11.6"/>',
    };
    const ag = (n, s) => '<svg class="ag ag-' + n + '" width="' + (s || 14) + '" height="' + (s || 14) + '" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + AG[n] + '</svg>';
    // our rules as drawings, each in the hue of its meaning (DESIGN-v2.md «Colors»), the rule in the tooltip
    const TGL = { 'pre-range': 'clock', 're-bought': 'renew', 'bot-like': 'bot', 'transfer-in': 'transfer', dev: 'dev', sniper: 'sniper',
      fresh: 'fresh', bundle: 'bundle', 'never-sold': 'gem', dormant: 'moon', 'launch-bundle': 'bundle', 'own-bundle': 'transfer' };
    function tagsHtmlV2(o) {
      const cx = crossings[o.w], idn = idents[o.w], b = bundle[o.w];
      let h = cx && cx.length ? '<button type="button" class="tag tg t-seen-before seen" title="Also an early buyer in ' + cx.length
        + ' of your saved analyses · click for the list" aria-label="Seen in ' + cx.length + ' of your other analyses">' + ag('link') + '</button>' : '';
      const ids = idn ? EarlyTags.idMarks(idn) : '';
      if (ids) h += '<span class="ids">' + ids + '</span>';
      o.tags.forEach(t => {
        if (t === 'seen-before') return;
        if (t === 'bundle' && b) { h += '<button type="button" class="tag tg t-bundle bundb" data-bund="' + esc(b.funder) + '" style="--c:' + bundleColor(o.w)
          + '" title="One funder, ' + plural(b.n, 'wallet') + ' here: likely one operator · click to show them" aria-label="Bundle of ' + b.n + '">' + ag('bundle') + '<i class="bdot"></i></button>'; return; }
        const g = TGL[t];
        h += g ? '<span class="tag tg t-' + esc(t) + '" title="' + esc(TAGDEF[t] || t) + '" aria-label="' + esc(t) + '">' + ag(g) + '</span>'
          : '<span class="tag t-' + esc(t) + '" title="' + esc(TAGDEF[t] || t) + '">' + esc(t) + '</span>';
      });
      userTags(o.w).forEach(x => { h += '<span class="tag own" title="Your tag">' + esc(x) + '</span>'; });
      return h;
    }
    const tokEl = document.getElementById('token'), NOWCAP = tokEl ? +tokEl.dataset.mcap || 0 : 0;
    const TRIPS = (() => {                                     // one log scale of caps for every row of this result
      const v = [];
      all.forEach(o => { const a = +o.eavg || +o.entry; if (a > 0) v.push(a); if (+o.exitcap > 0) v.push(+o.exitcap); });
      if (!v.length) return null;
      let lo = Math.log10(Math.min(...v)), hi = Math.log10(Math.max(...v, NOWCAP || 0));   // every row on it, none pinned to an edge
      if (hi - lo < 0.3) { const m = (hi + lo) / 2; lo = m - 0.15; hi = m + 0.15; }
      const pad = (hi - lo) * 0.04;
      return { lo: lo - pad, hi: hi + pad };
    })();
    const tripX = (v, W, sc) => { sc = sc || TRIPS; if (!sc || !(v > 0)) return null; const t = (Math.log10(v) - sc.lo) / (sc.hi - sc.lo); return Math.max(4, Math.min(W - 4, t * W)); };
    function tripSvg(o, W, H, sc, big) {
      W = W || 120; H = H || 12;
      const a = +o.eavg || +o.entry, b = +o.exitcap, y = H / 2, xa = tripX(a, W, sc), xb = b > 0 ? tripX(b, W, sc) : null, xn = NOWCAP ? tripX(NOWCAP, W, sc) : null;
      const up = b >= a, f = v => v.toFixed(1);
      let s = '<svg class="trip' + (big ? ' big' : '') + '" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" aria-hidden="true"><line class="t-base" x1="0" y1="' + y + '" x2="' + W + '" y2="' + y + '"/>';
      if (xn != null) s += '<line class="t-now" x1="' + f(xn) + '" y1="' + (big ? 6 : 2) + '" x2="' + f(xn) + '" y2="' + (H - (big ? 6 : 2)) + '"/>';
      if (xa != null && xb != null) s += '<line class="t-run ' + (up ? 'up' : 'dn') + '" x1="' + f(xa) + '" y1="' + y + '" x2="' + f(xb) + '" y2="' + y + '"/>';
      if (xa != null) s += '<circle class="t-in" cx="' + f(xa) + '" cy="' + y + '" r="' + (big ? 5 : 3) + '"/>';
      if (xb != null) s += '<circle class="t-out ' + (up ? 'up' : 'dn') + '" cx="' + f(xb) + '" cy="' + y + '" r="' + (big ? 6 : 3.5) + '"/>';
      return s + '</svg>';
    }
    const tripText = o => { const a = +o.eavg || +o.entry;
      return (a ? fm(a) : '—') + (o.exitcap ? ' → ' + fm(o.exitcap) + (o.hold != null ? ' · ' + holdText(o.hold) : '') : o.sells == null ? ' · exits not read' : ' · holding'); };
    const sgn = v => v == null || isNaN(v) ? '—' : (v > 0 ? '+$' : v < 0 ? '−$' : '$') + fm(Math.abs(v));   // a real minus (DESIGN-v2.md «Typography»)
    const NOSOL = 'This result was saved before tracced recorded SOL amounts';
    function amt2(usd, sol, cls, signed) {                     // an amount in the unit the toolbar shows, in the numbers' face
      const m = signed ? sgn : money;
      if (!SOLON) return '<b class="' + (cls || '') + '">' + m(usd) + '</b>';
      if (sol == null) return '<b class="amt nosol ' + (cls || '') + '" title="' + NOSOL + '">' + m(usd) + '</b>';
      return '<b class="insol ' + (cls || '') + '">' + (signed && sol > 0 ? '+' : '') + EarlyCur.sol(sol) + '</b>';
    }
    const fmtHM = ms => (window.EarlyTZ ? EarlyTZ.fmt(ms) : new Date(ms).toISOString().slice(5, 16).replace('T', ' '));
    function fundHtml(w) {
      const x = funders[w];
      if (!x) return '<span class="none" title="' + (ageDone ? 'Its first funder was not checked: only the top wallets by PnL are' : 'Checking…') + '">' + (ageDone ? '—' : '…') + '</span>';
      if (EXCH[x]) return '<span title="First SOL straight from ' + esc(EXCH[x][1] || EXCH[x][0]) + ', an exchange">' + esc(EXCH[x][0]) + '</span>';
      if (FLAB[x]) return '<span title="First SOL from ' + esc(FLAB[x][1] || FLAB[x][0]) + ', ' + esc(FLAB[x][2] || 'a known service') + '">' + esc(FLAB[x][0]) + '</span>';
      return '<span class="mono" title="First SOL from ' + x + (bundle[w] ? ', which funded ' + bundle[w].n + ' wallets here' : '') + '">' + short(x) + '</span>';
    }
    const COLS = {
      trip: { h: 'Trip', sub: 'cap in → out · held', key: 'entry', dir: 1, menu: 'Trip' },
      inv: { h: 'Bought', key: 'inv', fil: 'inv', num: 1, menu: 'Bought', fl: 'what it bought' },
      got: { h: 'Sold', key: 'got', fil: 'sold', num: 1, menu: 'Sold', fl: 'the share sold' },
      real: { h: 'PnL', key: 'real', fil: 'real', num: 1, menu: 'PnL', fl: 'PnL' },
      mult: { h: '×', key: 'mult', fil: 'mult', num: 1, menu: '× <span>multiple</span>', fl: 'the multiple' },
      hold: { h: 'Held', key: 'hold', fil: 'hold', num: 1, menu: 'Held', fl: 'hold time and buys' },
      buys: { h: 'Buys / sells', key: 'buys', fil: 'buys', num: 1, menu: 'Buys / sells', fl: 'its buys' },
      first: { h: 'First buy', key: 'etime', dir: 1, num: 1, menu: 'First buy' },
      fund: { h: 'Funded by', key: 'funder', text: 1, menu: 'Funded by' },
    };
    const CKEY = 'early:cols', CDEF = ['trip', 'inv', 'got', 'real', 'mult', 'hold', 'buys', 'first', 'fund'], CON = new Set(['trip', 'inv', 'got', 'real', 'mult']);
    let cols = (() => {
      let v = null; try { v = JSON.parse(localStorage.getItem(CKEY) || 'null'); } catch (e) {}
      const list = (Array.isArray(v) ? v : []).filter((x, i, a) => x && COLS[x.k] && a.findIndex(y => y && y.k === x.k) === i).map(x => ({ k: x.k, on: !!x.on }));
      CDEF.forEach(k => { if (!list.some(x => x.k === k)) list.push({ k, on: CON.has(k) }); });   // a column added later joins the list
      if (!list.some(x => x.on)) list.forEach(x => { x.on = CON.has(x.k); });
      return list;
    })();
    const saveCols = () => { try { localStorage.setItem(CKEY, JSON.stringify(cols)); } catch (e) {} };
    const shownCols = () => cols.filter(x => x.on).map(x => x.k);
    function cellV2(k, o) {
      const unk = o.sells == null, UNK = 'Its sells were not read: only the largest buyers\' are', cap = v => v ? fm(v) : '—';
      if (k === 'trip') { const a = +o.eavg || +o.entry;
        return '<td class="c-trip" data-h="Trip" title="Average entry ' + cap(a) + (o.exitcap ? ' → average exit ' + cap(o.exitcap) : unk ? ' · ' + UNK : ' · nothing sold yet')
          + (o.hold != null ? ' · held ' + holdText(o.hold) + ' on average' : '') + (NOWCAP ? ' · the tick: the cap now, ' + fm(NOWCAP) : '') + '">' + tripSvg(o) + '<small>' + tripText(o) + '</small></td>'; }
      if (k === 'inv') return '<td class="num two c-inv" data-h="Bought" title="' + money(o.tot || o.inv) + ' bought of this token in all'
        + (extra(o) ? ', ' + money(o.inv) + ' of it inside the range' : ', all of it inside the range') + ' · its first buy in the range at a ' + cap(o.entry) + ' market cap">'
        + amt2(o.tot || o.inv, o.totsol != null ? o.totsol : o.invsol) + '<small>' + (extra(o) ? money(o.inv) + ' in range' : '') + '</small></td>';
      if (k === 'got') return '<td class="num two c-sold" data-h="Sold"' + (o.exitcap ? ' title="Sold at a ' + fm(o.exitcap) + ' market cap on average · ' + soldPct(o.sold) + ' of its tokens sold"' : unk ? ' title="' + UNK + '"' : '') + '>'
        + (o.got ? amt2(o.got, o.gotsol) : '<b>—</b>') + '<small>' + (unk ? '' : soldPct(o.sold)) + '</small></td>';
      if (k === 'real') {
        const w = MAXR ? Math.round(100 * Math.abs(o.real) / MAXR) : 0, c = o.real > 0 ? 'pos' : o.real < 0 ? 'neg' : '';   // under 3% a bar is a stray line: none
        return '<td class="num two c-pnl' + (o.real < 0 ? ' neg' : '') + '" data-h="PnL"' + (unk ? ' title="' + UNK + '"' : ' title="Profit on what it sold: received minus what those tokens cost"') + '>'
          + '<span class="pcell">' + (unk || w < 3 ? '' : '<i class="pbar" style="width:' + w + '%"></i>') + (unk ? '<b>—</b>' : amt2(o.real, o.realsol, c, true))
          + '<small>' + (o.unreal ? '<span class="' + (o.unreal > 0 ? 'pos' : 'neg') + '">' + sgn(o.unreal) + '</span> on ' + leftPct(o.sold) + ' left' : !unk && o.sold >= 99 ? '<span class="none">sold out</span>' : '') + '</small></span></td>';
      }
      if (k === 'mult') return '<td class="num c-roi" data-h="×"' + (o.mult ? ' title="' + roiPct(o.mult) + ' · average exit ' + cap(o.exitcap) + ' ÷ average entry ' + cap(o.eavg) + '"' : ' title="' + (unk ? UNK : 'Nothing sold yet') + '"') + '>'
        + '<b class="' + (o.mult && o.mult < 1 ? 'neg' : '') + '">' + roiX(o.mult) + '</b></td>';
      if (k === 'hold') return '<td class="num two c-held" data-h="Held" title="How long it held what it sold, on average, weighted by amount"><b>' + holdText(o.hold) + '</b></td>';
      if (k === 'buys') return '<td class="num c-buys" data-h="Buys / sells" title="' + plural(o.buys, 'buy') + ', ' + (unk ? 'sells unknown' : plural(o.sells, 'sell')) + '">'
        + '<b><span class="up">' + o.buys + '</span> <span class="sl">/</span> <span class="dn">' + (unk ? '—' : o.sells) + '</span></b></td>';
      if (k === 'first') { const d = +o.etime - +CFG.from;
        return '<td class="num two c-first" data-h="First buy" title="' + (o.etime ? fmtHM(o.etime) : '') + '"><b>' + (o.etime ? fmtHM(o.etime).replace(/^.*, /, '') : '—') + '</b><small>'
          + (o.etime ? (d >= 0 ? '+' + holdText(d / 60000) : holdText(-d / 60000) + ' before') : '') + '</small></td>'; }
      if (k === 'fund') return '<td class="c-fund" data-h="Funded by">' + fundHtml(o.w) + '</td>';
      return '<td></td>';
    }
    function rowHtmlV2(o, n, i) {
      const oc = onChart.find(x => x.wallet === o.w), tg = tagsHtmlV2(o);
      cells.set(o.w, { tg });
      const style = (oc ? '--c:' + (oc.bundleColor || BUY_C) + ';' : '') + (i >= 0 ? '--i: ' + i : '');
      const cd = cardW() === o.w, out = n === '';
      const cl = [oc && 'onchart', cd && 'carded', out && 'outside', o.tags.includes('bot-like') && 'botlike'].filter(Boolean).join(' ');
      const nm = EarlyTags.displayName(idents[o.w]);
      return '<tr data-w="' + o.w + '"' + (cl ? ' class="' + cl + '"' : '') + (out ? ' title="On the chart; the filters would hide it"' : '') + (style ? ' style="' + style + '"' : '') + '>'
        + '<td class="wcell"><div class="wbox"><span class="wid">' + STAR(o.w) + '<span class="wface" aria-hidden="true">' + face(o.w) + '</span>'
        + '<button type="button" class="mk" title="Show its buys and sells on the chart" aria-label="Show on the chart">' + CHARTIC + '</button>'
        + '<button type="button" class="wname" data-nm="' + esc(nm || '') + '" title="Open the wallet\'s card: its trades here, its PnL on every token, its funder">' + (nm ? '<b class="wn">' + esc(nm) + '</b>' : '') + '<span class="mono">' + short(o.w) + '</span></button>'
        + '</span><span class="tags">' + tg + '</span><span class="msub">' + msub(o) + '</span></div></td>'
        + shownCols().map(k => cellV2(k, o)).join('') + '</tr>';
    }
    const FILG = ag('filter', 12);
    function headV2() {                                        // the head follows Columns: name, sort mark, funnel on one line
      const th = k => { const c = COLS[k];
        return '<th class="' + (c.num ? 'num ' : '') + 'sortable h-' + k + '" data-key="' + c.key + '"' + (c.dir ? ' data-dir="' + c.dir + '"' : '') + (c.text ? ' data-type="text"' : '')
          + '><span class="thc"><span class="hl">' + c.h + '</span>' + (c.sub ? '<span class="hsub">' + c.sub + '</span>' : '')
          + (c.fil ? '<button type="button" class="hfil" data-fil="' + c.fil + '" title="Filter by ' + c.fl + '" aria-label="Filter by ' + c.fl + '">' + FILG + '</button>' : '') + '</span></th>'; };
      table.tHead.innerHTML = '<tr><th class="wh">Wallet</th>' + shownCols().map(th).join('') + '</tr>';
    }
    function rowHtml(o, n, i) {
      if (V2) return rowHtmlV2(o, n, i);
      const oc = onChart.find(x => x.wallet === o.w), tg = tagsHtml(o);
      cells.set(o.w, { tg });
      const vs = o.mult ? Math.round((o.mult - 1) * 100) : null;
      const cls = v => v > 0 ? 'pos' : (v < 0 ? 'neg' : ''), cap = v => v ? fm(v) : '—';
      const style = (oc ? '--c:' + (oc.bundleColor || BUY_C) + ';' : '') + (i >= 0 ? '--i: ' + i : '');
      const cd = cardW() === o.w;
      const out = n === '';                                     // on the chart, though the filters would hide it
      const cl = [oc && 'onchart', cd && 'carded', out && 'outside'].filter(Boolean).join(' ');
      const unk = o.sells == null, UNK = 'Its sells were not read: only the largest buyers\' are';   // entry-only, beyond the cap
      return '<tr data-w="' + o.w + '"' + (cl ? ' class="' + cl + '"' : '') + (out ? ' title="On the chart; the filters would hide it"' : '') + (style ? ' style="' + style + '"' : '') + '>'
        + '<td class="wcell"><span class="wid">' + STAR(o.w) + '<span class="wface" aria-hidden="true">' + face(o.w) + '</span>'
        + '<button type="button" class="mk" title="Show its buys and sells on the chart" aria-label="Show on the chart">' + CHARTIC + '</button>'
        + '<button type="button" class="wname" title="Open the wallet\'s card: its trades here, its PnL on every token, its funder"><span class="mono">' + short(o.w) + '</span></button>'
        + '</span><span class="tags">' + tg + '</span><span class="msub">' + msub(o) + '</span></td>'
        + '<td class="num two c-inv" data-h="Bought" title="' + money(o.tot || o.inv) + ' bought of this token in all'
        + (extra(o) ? ', ' + money(o.inv) + ' of it inside the range' : ', all of it inside the range') + ' · its first buy in the range at a ' + cap(o.entry) + ' market cap">'
        + amount(o.tot || o.inv, o.totsol != null ? o.totsol : o.invsol, '')
        + '<small>' + (extra(o) ? money(o.inv) + ' in range · ' : '') + cap(o.entry) + '</small></td>'
        + '<td class="num two c-sold" data-h="Sold"' + (o.exitcap ? ' title="Sold at a ' + fm(o.exitcap) + ' market cap on average'
          + (vs != null ? ', ' + (vs > 0 ? '+' : '') + vs + '% against its average entry' : '') + ' · ' + soldPct(o.sold) + ' of its tokens sold"' : unk ? ' title="' + UNK + '"' : '') + '>'
        + (o.got ? amount(o.got, o.gotsol, '') : '<b class="mono">—</b>') + '<small>' + (o.exitcap ? fm(o.exitcap) + ' · ' + soldPct(o.sold) : '') + '</small></td>'
        + '<td class="num two bar c-pnl' + (o.real < 0 ? ' neg' : '') + '" data-h="PnL" style="--w: ' + (MAXR ? Math.round(100 * Math.abs(o.real) / MAXR) : 0) + '%"' + (unk ? ' title="' + UNK + '"' : '') + '>'
        + (unk ? '<b class="mono">—</b>' : amount(o.real, o.realsol, cls(o.real))) + '<small class="' + cls(o.unreal) + '">' + (o.unreal ? money(o.unreal) + ' on ' + leftPct(o.sold) + ' left' : '') + '</small></td>'
        + '<td class="num c-roi" data-h="ROI"' + (o.mult ? ' title="' + roiPct(o.mult) + ' · average exit ' + cap(o.exitcap) + ' ÷ average entry ' + cap(o.eavg) + '"' : ' title="' + (unk ? UNK : 'Nothing sold yet') + '"') + '>'
        + '<b class="mono ' + (o.mult ? (o.mult >= 1 ? 'pos' : 'neg') : '') + '">' + roiX(o.mult) + '</b></td>'
        + '<td class="num two c-held" data-h="Held" title="' + plural(o.buys, 'buy') + ', ' + (o.sells == null ? 'sells unknown' : plural(o.sells, 'sell')) + '"><b class="mono">' + holdText(o.hold) + '</b>'
        + '<small class="bs"><span class="up">↑' + o.buys + '</span> <span class="dn">↓' + (o.sells == null ? '—' : o.sells) + '</span></small></td></tr>';
    }

    // the page shows a window of the rows that pass the filters (LIMIT, then "Show more"); Export and the agent work on
    // all passing rows, shown or not
    const LIMIT = 100; let limit = LIMIT, drawn = [], first = true;
    const more = document.getElementById('more');
    const inRange = o => Object.keys(f.r).every(k => { const v = f.r[k], x = RANGES[k].get(o);
      return (v[0] == null || (x != null && x >= v[0])) && (v[1] == null || (x != null && x <= v[1])); });
    const qOk = o => { if (!f.q) return true; const q = f.q.toLowerCase();
      return o.w.toLowerCase().includes(q) || (EarlyTags.displayName(idents[o.w]) || '').toLowerCase().includes(q)
        || userTags(o.w).some(x => x.toLowerCase().includes(q)); };
    const okRow = o => inRange(o) && qOk(o) && (!f.profit || o.real > 0) &&
      (!f.exits || o.exit) && (!f.mine || inList(o.w)) &&
      (!f.funder || fundKey(o.w) === f.funder) && (!f.bundle || (!!bundle[o.w] && bundle[o.w].funder === f.bundle)) && (!f.repeat || !!crossings[o.w]) && !f.hide.some(t => o.tags.includes(t)) &&
      (!f.only || (f.only === 'cex' ? !!(funders[o.w] && EXCH[funders[o.w]])
        : f.only === 'launch' ? (o.tags.includes('own-bundle') || o.tags.includes('launch-bundle')) : o.tags.includes(f.only)));
    function draw() {
      // the first `limit` rows that pass, plus any wallet pinned to the chart further down; a pinned wallet the
      // filters reject is drawn last and without a number, and is not in `pass`, so no action counts it. The same
      // rows as last time are patched in place, so a background update never replaces a button under the pointer
      const rows = [];
      pass.forEach((o, i) => { if (i < limit || pinned.has(o.w)) rows.push([o, i + 1]); });
      pinned.forEach(w => { const o = byW.get(w); if (o && !okRow(o)) rows.push([o, '']); });
      const ws = rows.map(x => x[0].w), nums = rows.map(x => x[1]);
      if (!first && ws.length === drawn.length && ws.every((w, k) => w === drawn[k])) { refreshRows(nums); return; }
      tbody.innerHTML = rows.map(([o, n]) => rowHtml(o, n, first && n && n <= 40 ? n - 1 : -1)).join('');
      drawn = ws; first = false;
    }
    function refreshRows(nums) {
      [...tbody.rows].forEach((tr, k) => {
        const o = byW.get(tr.dataset.w); if (!o) return;
        if (nums) { tr.classList.toggle('outside', nums[k] === ''); tr.title = nums[k] === '' ? 'On the chart; the filters would hide it' : ''; }
        const c = cells.get(o.w) || {}, tg = V2 ? tagsHtmlV2(o) : tagsHtml(o);
        if (c.tg !== tg) tr.querySelector('.tags').innerHTML = tg;
        cells.set(o.w, { tg });
        if (V2) {                                               // names and funders arrive after the page
          const nm = EarlyTags.displayName(idents[o.w]) || '', wn = tr.querySelector('.wname');
          if (wn && (wn.dataset.nm || '') !== nm) { wn.dataset.nm = nm; const s = wn.querySelector('.mono'); const b = wn.querySelector('.wn');
            if (nm) { if (b) b.textContent = nm; else s.insertAdjacentHTML('beforebegin', '<b class="wn">' + esc(nm) + '</b>'); } else if (b) b.remove(); }
          const fc = tr.querySelector('.c-fund'); if (fc) { const h = fundHtml(o.w); if (fc.dataset.h !== h) { fc.innerHTML = h; fc.dataset.h = h; } }
        }
        const oc = onChart.find(x => x.wallet === o.w);
        tr.classList.toggle('onchart', !!oc);
        if (oc) tr.style.setProperty('--c', oc.bundleColor || BUY_C); else tr.style.removeProperty('--c');
      });
    }
    // "nothing to dig here": when nearly all of the top wallets by PnL (the ones checked for age and funder) are fresh or
    // in bundles, the launch was organised and the list holds few organic buyers. Said once the check is done
    const VERDICT_PCT = CFG.verdict_pct, VERDICT_TOP = CFG.age_n;   // not AGE_N: apply() runs before it is declared
    // the word follows what the top is made of: the creator in it — Rigged; one operator's wallets — Bundled;
    // wallets made for the launch — Staged; both at once — Cabal. The numbers are in the tooltip
    let verdictNote = '', verdictWord = '';
    function verdict() {
      const top = all.slice(0, VERDICT_TOP), has = t => top.filter(o => o.tags.includes(t)).length;
      const n = top.filter(o => o.tags.includes('fresh') || o.tags.includes('bundle')).length, nb = has('bundle'), nf = has('fresh');
      const pct = top.length >= 20 ? Math.floor(100 * n / top.length) : 0;   // 199 of 200 is 99%, not 100%
      const dev = all.some(o => o.tags.includes('dev'));
      const on = ageDone && VERDICT_PCT && pct >= VERDICT_PCT;
      verdictWord = !on ? '' : dev ? 'Rigged' : nb >= 0.6 * top.length && nf < 0.6 * top.length ? 'Bundled'
        : nf >= 0.6 * top.length && nb < 0.6 * top.length ? 'Staged' : 'Cabal';
      verdictNote = on ? n + ' of the top ' + top.length + ' by PnL (' + pct + '%) are fresh or bundled: ' + nb + ' in bundles, ' + nf + ' fresh'
        + (dev ? ', and the creator bought in the range' : '') + '. One hand ran this launch; little here is organic buying' : '';
    }
    // Insights (trader, 01.10: «conclusions about the token, in percent, not bare numbers»): at most four, each only when
    // it says something, each a click into exactly those wallets where there is a filter for them; the counts are in the
    // tooltip. Bundles, fresh wallets and funders come after the page, so this runs again as they do
    const FIND_MAX = 4; let findActs = [];
    // a share of tokens sold: «100%» only when all of it went, 99.7% stays 99.7% (owner, 02.10: «sold 100%, still held?»)
    const soldPct = v => { v = +v || 0; return (v >= 99.5 && v < 100 ? v.toFixed(1) : Math.round(v)) + '%'; };
    const leftPct = v => { const l = 100 - (+v || 0); return (l < 1 ? l.toFixed(1) : Math.round(l)) + '%'; };
    const pc = (a, b) => { if (!b) return 0; const p = Math.round(100 * a / b); return a < b && p >= 100 ? 99 : p; };   // 299 of 300 is 99%, not 100%
    function findings() {
      const el = document.getElementById('finds'); if (!el) return;
      const inv = o => +o.inv || 0, tot = all.reduce((s, o) => s + inv(o), 0) || 1, n = all.length, out = [];
      // an organised launch (owner, 14.10): wallets on both sides of one Jito bundle, the creator's own bundle, the
      // creator fee sent elsewhere. Facts in the tooltip, a click shows exactly those wallets
      const ls = LAUNCH && LAUNCH.summary;
      if (ls && (ls.pairs || ls.launch_wallets || ls.fee_to)) {
        const nOwn = all.filter(o => o.tags.includes('own-bundle') || o.tags.includes('launch-bundle')).length;
        const bits = [];
        if (ls.pairs) bits.push(ls.pairs + ' Jito bundles where one wallet sold and another bought' + (ls.bought_back_pct ? ': ' + ls.bought_back_pct + '% of the supply' : ''));
        if (ls.launch_wallets) bits.push(plural(ls.launch_wallets, 'wallet') + " in the creator's own launch bundle");
        if (ls.fee_to) bits.push('the creator fee goes to ' + ls.fee_to.map(x => x[0].slice(0, 4) + '…' + x[0].slice(-4) + (x[1] < 10000 ? ' (' + x[1] / 100 + '%)' : '')).join(', ')
          + (ls.fee_sol ? ', ' + (+ls.fee_sol).toFixed(1) + ' SOL paid out so far' : ''));
        out.push({ k: 'launch', sev: 'bad', act: nOwn ? ['only', 'launch'] : null, v: ls.bought_back_pct ? ls.bought_back_pct + '%' : String(nOwn || '✓'),
          l: 'organised launch', tip: 'Organised launch: ' + bits.join('; ') + '.' });
      }
      const dev = all.find(o => o.tags.includes('dev'));
      if (dev) out.push({ k: 'dev', sev: 'bad', act: ['only', 'dev'], v: money(dev.inv), l: 'creator bought',
        tip: "The token's creator bought here: " + money(dev.inv) + ' in' + (dev.got ? ', ' + money(dev.got) + ' out' : ', nothing sold yet') });
      const bw = all.filter(o => bundle[o.w]);                                  // wallets that share a funder here
      if (bw.length) {
        const ops = new Set(bw.map(o => funders[o.w] || bundle[o.w].funder)).size, sh = pc(bw.reduce((s, o) => s + inv(o), 0), tot);
        if (sh >= 10) out.push({ k: 'bundle', sev: 'warn', act: ['only', 'bundle'], v: sh + '%', p: sh, l: 'bundled',
          tip: plural(ops, 'operator') + ' bought ' + sh + '% of the range through ' + plural(bw.length, 'wallet') + ' that share a funder' });
        // «bundle out» (bbb.community): nearly every wallet of the bundles has sold out
        const outN = bw.filter(o => (+o.sold || 0) >= 99).length, po = pc(outN, bw.length);
        if (bw.length >= 3 && po >= 90) out.push({ k: 'bout', sev: 'warn', act: ['only', 'bundle'], v: po + '%', p: po, l: 'bundles out',
          tip: outN + ' of the ' + bw.length + ' bundled wallets sold 99% or more' });
      }
      // fresh among the wallets whose age is known: an older result checked all of them, not only the first VERDICT_TOP
      const fr = all.filter(o => o.tags.includes('fresh')).length, checked = Math.max(Object.keys(ages).length || Math.min(n, VERDICT_TOP || n), fr) || 1;
      if (fr >= 10 && fr / checked >= 0.1) out.push({ k: 'fresh', sev: 'warn', act: ['only', 'fresh'], v: pc(fr, checked) + '%', p: pc(fr, checked), l: 'fresh',
        tip: fr + ' of the ' + checked + ' wallets checked were under a day old when they bought' });
      const prof = all.map(o => +o.real || 0).filter(v => v > 0).sort((a, b) => b - a), ptot = prof.reduce((a, b) => a + b, 0);
      if (prof.length >= 20 && ptot > 0) {
        const s10 = pc(prof.slice(0, 10).reduce((a, b) => a + b, 0), ptot);
        if (s10 >= 40) out.push({ k: 'top', sev: 'info', act: ['sort', 'real'], v: s10 + '%', p: s10, l: 'to top 10',
          tip: 'The 10 most profitable wallets took ' + s10 + '% of all the profit made here' });
      }
      const rep = all.filter(o => crossings[o.w]).length;
      if (rep >= 3) out.push({ k: 'repeat', sev: 'rep', act: ['repeat'], v: String(rep), l: 'seen before',
        tip: rep + ' wallets were early in your other saved pumps too' });
      const ex = {}; all.forEach(o => { const x = funders[o.w]; if (x && EXCH[x]) { const nm = EXCH[x][2] ? 'other exchanges' : EXCH[x][0]; ex[nm] = (ex[nm] || 0) + 1; } });
      const exN = Object.values(ex).reduce((a, b) => a + b, 0), funded = all.filter(o => funders[o.w]).length;
      if (exN >= 10 && funded && exN / funded >= 0.05) out.push({ k: 'cex', sev: 'info', act: ['only', 'cex'], v: pc(exN, funded) + '%', p: pc(exN, funded), l: 'from exchanges',
        tip: exN + ' of ' + funded + ' wallets got their first SOL straight from an exchange: ' + Object.entries(ex).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([nm, c]) => nm + ' ' + c).join(', ') });
      if (n >= 20) {
        const won = pc(all.filter(o => (+o.real || 0) > 0).length, n);
        out.push({ k: 'won', sev: 'good', act: ['profit'], v: won + '%', p: won, l: 'in profit', tip: won + '% of the wallets have a realized profit here' });
      }
      if (V2) {
        // v2: the share in profit is one of the three large counts, the rest a line of words, each a click into its wallets
        findActs = out.filter(x => x.k !== 'won').slice(0, FIND_MAX);
        const W = { launch: () => 'organised launch', dev: x => 'creator bought <b>' + x.v + '</b>', bout: x => '<b>' + x.v + '</b> of bundles out',
          cex: x => '<b>' + x.v + '</b> funded from exchanges', top: x => '<b>' + x.v + '</b> of the profit to the top 10', repeat: x => '<b>' + x.v + '</b> seen before' };
        const words = x => (W[x.k] ? W[x.k](x) : '<b>' + x.v + '</b> ' + x.l);
        const SEP = '<span class="tsep" aria-hidden="true">·</span>';
        const v2html = (verdictNote ? SEP + '<span class="tc bad tipt" tabindex="0" title="' + esc(verdictNote) + '"><b>' + verdictWord + '</b> launch</span>' : '')
          + findActs.map((x, i) => SEP + (x.act ? '<button type="button" class="tc ' + x.sev + '" data-i="' + i + '" title="' + esc(x.tip) + ' · click to show them">'
            : '<span class="tc ' + x.sev + '" title="' + esc(x.tip) + '">') + words(x) + (x.act ? '</button>' : '</span>')).join('');
        if (el.dataset.h !== v2html) { el.innerHTML = v2html; el.dataset.h = v2html; }
        return;
      }
      findActs = out.slice(0, FIND_MAX);
      const cell = (x, i) => (x.act ? '<button type="button" class="tc ' + x.sev + '" data-i="' + i + '" title="' + esc(x.tip) + ' · click to show them">'
        : '<span class="tc ' + x.sev + '" title="' + esc(x.tip) + '">') + '<b>' + x.v + '</b><i>' + x.l + '</i>' + (x.p != null ? '<span class="tm" style="--p:' + x.p + '%"></span>' : '') + (x.act ? '</button>' : '</span>');
      const html = (verdictNote ? '<span class="tc bad tipt" tabindex="0" title="' + esc(verdictNote) + '"><b>' + verdictWord + '</b><i>launch</i></span>' : '')
        + findActs.map(cell).join('');
      if (el.dataset.h !== html) { el.innerHTML = html; el.dataset.h = html; }
    }
    // a count or a finding is a click into exactly its wallets, or into its order
    document.getElementById('tally').addEventListener('click', e => {
      const s = e.target.closest('.tc[data-act]'), b = e.target.closest('.tc[data-i]'), x = b && findActs[+b.dataset.i];
      if (!s && !x) return;
      const act = s ? [s.dataset.act] : x.act;
      Object.assign(f, fresh0());                                         // exactly its wallets: other filters would hide some of them
      if (act[0] === 'only') f.only = act[1];
      if (act[0] === 'repeat') f.repeat = true;
      if (act[0] === 'sold') f.r.sold = [99, null];
      if (act[0] === 'holding') f.r.sold = [null, 49.9];
      if (act[0] === 'profit') f.profit = true;
      saveF(); syncHeads(); limit = LIMIT;
      if (act[0] === 'sort') sortBy('real', -1); else if (act[0] === 'best') sortBy('mult', -1); else apply();
      EarlyUI.use('finding', { k: s ? s.dataset.act : x.k });
      // to the toolbar, not the table: the note of what is shown and its × sit there (review 01.10)
      (document.querySelector('.row.toolbar') || document.getElementById('facts')).scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    if (V2) {                                                   // the third large count: the share of wallets in profit
      const tp = document.getElementById('tprofit');
      if (tp && all.length) { tp.querySelector('b').dataset.count = pc(all.filter(o => (+o.real || 0) > 0).length, all.length); tp.hidden = false; }
    }
    // the one filter a click can set without the panel open is named beside the count, with its own ×
    const ONLY = { bundle: 'Only bundles', dev: 'Only the creator', fresh: 'Only fresh wallets', cex: 'Only funded from exchanges',
      launch: "Only the launch's own wallets" };
    function activeNote() {
      const el = document.getElementById('factive'); if (!el) return;
      const n = f.only ? ONLY[f.only] : f.repeat ? 'Only early in your other pumps' : f.funder ? 'Funded by ' + fundLabel(f.funder)
        : f.bundle ? 'One bundle: ' + plural(all.filter(o => bundle[o.w] && bundle[o.w].funder === f.bundle).length, 'wallet')
        : f.profit ? 'Only wallets in profit' : (isOn('sold') && f.r.sold[0] >= 99 && f.r.sold[1] == null) ? 'Only sold out'
        : (isOn('sold') && f.r.sold[0] == null && f.r.sold[1] < 50) ? 'Only still holding' : '';
      el.hidden = !n; el.innerHTML = n ? esc(n) + ' <button type="button" class="ghost" aria-label="Clear">×</button>' : '';
    }
    document.getElementById('factive').addEventListener('click', e => {
      if (!e.target.closest('button')) return;
      f.only = f.funder = f.bundle = ''; f.repeat = f.profit = false;
      if (isOn('sold') && (f.r.sold[0] >= 99 || (f.r.sold[0] == null && f.r.sold[1] < 50))) delete f.r.sold;
      saveF(); syncHeads(); limit = LIMIT; apply();
    });
    function apply() {
      pass = order.filter(okRow);
      draw();
      verdict(); findings(); activeNote();
      const na = nActive(), n = pass.length, left = Math.max(0, n - limit);
      shown.textContent = (left ? Math.min(n, limit) + ' of ' + n + ' shown' : n + ' of ' + all.length) + (na ? ' · filtered' : '');
      more.hidden = !left; document.getElementById('more100').hidden = left <= 100; document.getElementById('moren').textContent = n;
      if (V2) {                                                 // the label beside its drawing; the toolbar's own search and bot switch
        document.getElementById('ftext').textContent = na ? 'Filters · ' + na : 'Filters';
        const q = document.getElementById('tfind'); if (q && document.activeElement !== q && q.value !== f.q) q.value = f.q;
        const hb = document.getElementById('hidebots'); if (hb) { const on = f.hide.includes('bot-like'); hb.classList.toggle('on', on); hb.setAttribute('aria-pressed', String(on)); }
      } else ftoggle.textContent = na ? 'Filters · ' + na : 'Filters';
      ftoggle.classList.toggle('on', !!na);
      const fr = document.getElementById('freset'); if (fr) fr.hidden = !na && sortKey === 'real' && sortDir === -1;
      syncExport();
    }
    document.getElementById('more100').addEventListener('click', () => { EarlyUI.track('show-more'); limit += LIMIT; apply(); });
    document.getElementById('moreall').addEventListener('click', () => { EarlyUI.track('show-more', { all: 1 }); limit = Infinity; apply(); });
    function syncExport() {                                     // Export takes what the filters let through, every row of it
      const what = pass.length + (na() ? ' filtered' : ' wallets');
      document.getElementById('xcsv').textContent = '— ' + what + ', all columns';
      document.getElementById('xtxt').textContent = '— ' + pass.length + ' addresses';
      document.getElementById('xjson').textContent = '— ' + what + ' + coverage';
    }
    const na = nActive;
    // one small window per filter: «from … to …», Reset and Apply; the Wallet funnel finds a wallet and hides tags.
    // The Filters button lists them all (the only way in on a phone, where the table has no head)
    const fpop = document.createElement('div'); fpop.className = 'fpop'; fpop.hidden = true; fpop.setAttribute('role', 'dialog'); document.body.appendChild(fpop);
    let fpopFor = null, hasLists = false;
    const numIn = (k, i, v) => '<input type="number" inputmode="decimal" step="' + RANGES[k].step + '" data-k="' + k + '" data-i="' + i + '" placeholder="' + (i ? 'max' : 'min')
      + '" value="' + (v == null ? '' : v) + '" aria-label="' + RANGES[k].t + (i ? ', at most' : ', at least') + '">';
    const rangeRow = k => { const v = f.r[k] || [null, null];
      return '<div class="fph">' + RANGES[k].t + (RANGES[k].u ? ', ' + RANGES[k].u : '') + '<small>' + RANGES[k].hint + '</small></div>'
        + '<div class="fprow">' + numIn(k, 0, v[0]) + '<span>to</span>' + numIn(k, 1, v[1]) + '</div>'; };
    function placeUnder(el, anchor, w) {                         // under its funnel: right-aligned, or from its left edge near the page's left
      const r = anchor.getBoundingClientRect(), cw = document.documentElement.clientWidth;
      let x = r.right - w; if (x < 8) x = r.left;
      el.style.top = (window.scrollY + r.bottom + 6) + 'px';
      el.style.left = (window.scrollX + Math.max(8, Math.min(x, cw - w - 8))) + 'px';
    }
    function openFilter(key, anchor) {
      fpopFor = key;
      const body = key === 'hold' ? rangeRow('hold') + rangeRow('buys') : rangeRow(key);
      fpop.innerHTML = body + '<div class="fpf"><button type="button" class="ghost" data-reset>Reset</button><button type="button" class="primary" data-apply>Apply</button></div>';
      placeUnder(fpop, anchor, 290); fpop.hidden = false;
      const first = fpop.querySelector('input'); if (first) first.focus();
    }
    const closeFilter = () => { fpop.hidden = true; fpopFor = null; };
    function applyFilter() {
      const key = fpopFor; if (!key) return;
      (key === 'hold' ? ['hold', 'buys'] : [key]).forEach(k => {
        const v = [0, 1].map(i => { const x = fpop.querySelector('input[data-k="' + k + '"][data-i="' + i + '"]').value.trim(); return x === '' || isNaN(+x) ? null : +x; });
        if (v[0] == null && v[1] == null) delete f.r[k]; else f.r[k] = v;
      });
      closeFilter(); saveF(); syncHeads(); limit = LIMIT; apply(); EarlyUI.use('filter', { k: key });
    }
    function resetFilter() {
      const key = fpopFor; if (!key) return;
      (key === 'hold' ? ['hold', 'buys'] : [key]).forEach(k => { delete f.r[k]; });
      closeFilter(); saveF(); syncHeads(); limit = LIMIT; apply();
    }
    fpop.addEventListener('click', e => { if (e.target.closest('[data-apply]')) applyFilter(); else if (e.target.closest('[data-reset]')) resetFilter(); });
    fpop.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); applyFilter(); } else if (e.key === 'Escape') { e.stopPropagation(); closeFilter(); } });
    on(document, 'click', e => {
      if (!fpop.hidden && !e.target.closest('.fpop, .hfil, #ftoggle')) closeFilter();
    });
    on(document, 'keydown', e => { if (e.key === 'Escape') closeFilter(); });
    // the panel: find a wallet, your watchlist, every number from and to, the tags to hide; all of it applies as you type.
    // The funnels in the head edit the same numbers, so either one shows what the other set
    const PANEL_NUMS = ['inv', 'sold', 'real', 'mult', 'hold', 'buys'];
    function drawPanel() {
      const fp = document.getElementById('fpanel');
      fp.innerHTML = '<div class="fp-top"><input type="text" class="fq" maxlength="44" placeholder="Find a wallet: address or name" aria-label="Find a wallet">'
        + '<label class="fck fmine" hidden><input type="checkbox" data-mine>' + EarlyIcon('star-on') + 'Only my watchlist</label></div>'
        + '<div class="fp-nums">' + PANEL_NUMS.map(k => '<label class="fnum" title="' + esc(RANGES[k].hint) + '"><span>' + RANGES[k].t + (RANGES[k].u ? ', ' + RANGES[k].u : '')
          + '</span>' + numIn(k, 0, null) + '<i>–</i>' + numIn(k, 1, null) + '</label>').join('') + '</div>'
        + '<div class="fp-hide"><span class="fph">Hide</span>' + HIDE_TAGS.map(x => '<button type="button" class="tagchip t-' + x + '" data-hide="' + x + '" aria-pressed="false" title="Hide wallets tagged '
          + x + ': ' + esc(TAGDEF[x] || '') + '">' + (EarlyTags.ICON[x] || '') + x + '</button>').join('') + '</div>'
        + '<div class="fp-views"><span class="fph">Views</span><span class="fvlist"></span>'
        + '<button type="button" class="ghost fvsave" title="Keep these filters and this order under a name, for any analysis">Save these filters</button>'
        + '<input type="text" class="fvname" maxlength="24" placeholder="Name, then Enter" aria-label="Name of the saved filters" hidden></div>';
      fillPanel();
    }
    function fillPanel() {                                     // the values from the state, never under the field being typed in
      const fp = document.getElementById('fpanel'); if (!fp || fp.hidden || !fp.firstChild) return;
      const q = fp.querySelector('.fq'); if (q !== document.activeElement) q.value = f.q;
      const m = fp.querySelector('.fmine'); m.hidden = !(hasLists || f.mine); m.querySelector('input').checked = !!f.mine;
      fp.querySelectorAll('input[data-k]').forEach(x => { if (x !== document.activeElement) { const v = (f.r[x.dataset.k] || [null, null])[+x.dataset.i]; x.value = v == null ? '' : v; } });
      fp.querySelectorAll('[data-hide]').forEach(b => { const on = f.hide.includes(b.dataset.hide); b.classList.toggle('off', on); b.setAttribute('aria-pressed', String(on)); });
      const vs = loadViews(), cur = JSON.stringify(viewOf());
      fp.querySelector('.fvlist').innerHTML = vs.map((v, i) => '<span class="vchip' + (JSON.stringify({ f: v.f, sort: v.sort }) === cur ? ' on' : '') + '">'
        + '<button type="button" data-view="' + i + '" title="Apply these filters and this order">' + esc(v.name) + '</button>'
        + '<button type="button" class="vx" data-vdel="' + i + '" title="Delete" aria-label="Delete ' + esc(v.name) + '">×</button></span>').join('');
      const plain = !nActive() && sortKey === 'real' && sortDir === -1;   // nothing set: nothing to save
      fp.querySelector('.fvsave').hidden = plain || vs.length >= MAX_VIEWS || !fp.querySelector('.fvname').hidden;
    }
    const fpanel = document.getElementById('fpanel');
    ftoggle.addEventListener('click', () => {
      const open = fpanel.hidden;
      if (open && !fpanel.firstChild) drawPanel();
      fpanel.hidden = !open; ftoggle.setAttribute('aria-expanded', String(open));
      if (open) { closeFilter(); fillPanel(); }
      EarlyUI.use('filters-toggle', { on: open });
    });
    let qT = 0, nT = 0;
    fpanel.addEventListener('input', e => {
      const x = e.target;
      if (x.classList.contains('fq')) { clearTimeout(qT); qT = later(() => { f.q = x.value.trim(); saveF(); limit = LIMIT; apply(); }, 250); return; }
      if (!x.dataset.k) return;
      clearTimeout(nT); nT = later(() => {
        const k = x.dataset.k, v = [0, 1].map(i => { const y = fpanel.querySelector('input[data-k="' + k + '"][data-i="' + i + '"]').value.trim(); return y === '' || isNaN(+y) ? null : +y; });
        if (v[0] == null && v[1] == null) delete f.r[k]; else f.r[k] = v;
        saveF(); syncHeads(); limit = LIMIT; apply(); EarlyUI.use('filter', { k });
      }, 400);
    });
    fpanel.addEventListener('keydown', e => {
      const inp = e.target; if (!inp.classList || !inp.classList.contains('fvname')) return;
      if (e.key === 'Escape') { e.stopPropagation(); inp.hidden = true; fillPanel(); return; }
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const name = inp.value.trim().slice(0, 24); if (!name) return;
      const vs = loadViews().filter(v => v.name !== name);     // the same name again replaces it
      vs.unshift(Object.assign({ name }, viewOf())); saveViews(vs);
      inp.hidden = true; fillPanel(); EarlyUI.use('view-save', { count: Math.min(vs.length, MAX_VIEWS) });
    });
    fpanel.addEventListener('focusout', e => {
      const inp = e.target; if (inp.classList && inp.classList.contains('fvname')) setTimeout(() => { if (document.activeElement !== inp) { inp.hidden = true; fillPanel(); } }, 150);
    });
    fpanel.addEventListener('change', e => {
      if (!e.target.matches('[data-mine]')) return;
      f.mine = e.target.checked; saveF(); limit = LIMIT; apply();
    });
    fpanel.addEventListener('click', e => {
      const vb = e.target.closest('[data-view]');
      if (vb) {
        const v = loadViews()[+vb.dataset.view]; if (!v) return;
        Object.assign(f, fresh0(), JSON.parse(JSON.stringify(v.f))); saveF(); syncHeads(); closeFilter();
        sortBy(v.sort[0], v.sort[1], v.sort[0] === 'funder'); fillPanel(); EarlyUI.use('view-apply');
        return;
      }
      const vd = e.target.closest('[data-vdel]');
      if (vd) { const vs = loadViews(); vs.splice(+vd.dataset.vdel, 1); saveViews(vs); fillPanel(); EarlyUI.use('view-delete'); return; }
      if (e.target.closest('.fvsave')) {
        const inp = fpanel.querySelector('.fvname'); inp.hidden = false; inp.value = 'View ' + (loadViews().length + 1);
        fillPanel(); inp.focus(); inp.select(); return;
      }
      const b = e.target.closest('[data-hide]'); if (!b) return;
      const tg = b.dataset.hide, on = !f.hide.includes(tg);
      f.hide = on ? f.hide.concat([tg]) : f.hide.filter(y => y !== tg);
      saveF(); limit = LIMIT; apply(); fillPanel(); EarlyUI.use('hide', { tag: tg, on });
    });
    // Reset beside Filters, there whenever filters or the order differ from how the table came (owner, 02.10)
    const freset = document.getElementById('freset');
    function resetAll() { Object.assign(f, fresh0()); saveF(); syncHeads(); closeFilter(); sortBy('real', -1); fillPanel(); EarlyUI.use('filters-reset'); }
    freset.addEventListener('click', resetAll);

    // the account: a wallet goes to a list by its star, the whole analysis to «My analyses»; no wallet yet → connect
    // first, then continue. An empty star adds the wallet to the Watchlist at once; a filled one opens its lists
    let acctOn = document.documentElement.dataset.acct === '1', me = null;   // the page's own: a wallet connected on it counts
    const sjob = document.getElementById('savejob');
    const inList = w => !!(me && me.wallets && me.wallets[w]);
    /* Several watchlists: the toolbar button and the card's star open the same small menu. For one wallet it shows
       which lists hold it and toggles them; for a selection it adds all of them to the list you pick. */
    const listpop = document.createElement('div');
    listpop.className = 'listpop'; listpop.hidden = true; document.body.appendChild(listpop);
    const listsOf = () => (me && me.lists) || { main: { name: 'Main' } };
    const listsOfWallet = w => (me && me.wallets && me.wallets[w] && me.wallets[w].lists) || [];
    // every add records which list took the wallet, so the star and its menu know it before the next reload
    const noteIn = (ws, lid) => { blank(); ws.forEach(w => { const x = me.wallets[w] = me.wallets[w] || { my_tags: [] }; x.lists = x.lists || []; if (!x.lists.includes(lid)) x.lists.push(lid); }); };
    async function addToList(lid, ws) {
      const d = await EarlyWallet.post('/me/wallets', { job: jobId, wallets: ws, list: lid });
      EarlyUI.track('list-add');
      noteIn(d.wallets, lid);
      markSaved();
      return d;
    }
    async function removeFromList(lid, w) {
      await EarlyWallet.post('/me/wallets/remove', { wallets: [w], list: lid });
      const x = me && me.wallets[w];
      if (x) { x.lists = (x.lists || []).filter(l => l !== lid); if (!x.lists.length) delete me.wallets[w]; }
      markSaved();
    }
    function openLists(anchor, ws) {
      const single = ws.length === 1 ? ws[0] : null, L = listsOf();
      listpop.innerHTML = '<div class="lh">' + (single ? 'Saved in' : 'Add ' + plural(ws.length, 'wallet') + ' to') + '</div>'
        + Object.entries(L).map(([id, v]) => {
            const on = single && listsOfWallet(single).includes(id);
            return '<button type="button" class="li' + (on ? ' on' : '') + '" data-id="' + id + '" aria-pressed="' + !!on + '">'
              + (single ? '<i class="ck">' + (on ? '✓' : '') + '</i>' : '') + esc(v.name) + '</button>';
          }).join('')
        + '<form class="lnew"><input type="text" maxlength="32" placeholder="New list" aria-label="Name of a new list"><button type="submit">Create</button></form>'
        + (!single && ws.some(inList) ? '<button type="button" class="li rm" data-rm="1">Remove from all lists</button>' : '');
      const r = anchor.getBoundingClientRect();
      listpop.style.top = (window.scrollY + r.bottom + 6) + 'px';
      listpop.style.left = Math.max(8, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - 248)) + 'px';
      listpop.hidden = false;
      listpop.onclick = async e => {
        const b = e.target.closest('.li'); if (!b) return;
        try {
          if (b.dataset.rm) { await removeWallets(ws); listpop.hidden = true; return; }
          const id = b.dataset.id, name = L[id].name;
          if (single && listsOfWallet(single).includes(id)) { await removeFromList(id, single); EarlyUI.toast('Removed from ' + esc(name)); }
          else { const d = await addToList(id, ws); EarlyUI.toast((single ? 'Added to ' : plural(d.added, 'wallet') + ' added to ') + esc(name) + ' · <a href="/me#list">Watchlist →</a>'); }
          if (single) { openLists(anchor, ws); if (drawer.dataset.w === single) { syncStar(single); renderTags(single); } } else listpop.hidden = true;
        } catch (x) { EarlyUI.toast(x.message); }
      };
      listpop.querySelector('.lnew').onsubmit = async e => {
        e.preventDefault();
        const name = e.target.querySelector('input').value.trim(); if (!name) return;
        try {
          const d = await EarlyWallet.post('/me/lists', { name });
          blank(); me.lists = d.lists;
          await addToList(d.id, ws);
          EarlyUI.toast((single ? 'Added' : plural(ws.length, 'wallet') + ' added') + ' to the new list ' + esc(d.name) + ' · <a href="/me#list">Watchlist →</a>');
          if (single) { openLists(anchor, ws); if (drawer.dataset.w === single) { syncStar(single); renderTags(single); } } else listpop.hidden = true;
        } catch (x) { EarlyUI.toast(x.message); }
      };
      if (!single) setTimeout(() => { const i = listpop.querySelector('.lnew input'); if (i && !Object.keys(L).length) i.focus(); }, 0);
    }
    on(document, 'click', e => { if (!listpop.hidden && !e.target.closest('.listpop, #dstar, .star')) listpop.hidden = true; });
    on(document, 'keydown', e => { if (e.key === 'Escape') listpop.hidden = true; });
    function markSaved() {
      for (const r of tbody.rows) {
        const st = r.querySelector('.star'); if (!st) continue;
        const on = inList(r.dataset.w);
        st.classList.toggle('on', on); st.innerHTML = EarlyIcon(on ? 'star-on' : 'star'); st.setAttribute('aria-pressed', String(on));
        st.title = on ? 'In your watchlist · click to change' : 'Add to your watchlist'; st.setAttribute('aria-label', on ? 'In your watchlist' : 'Add to your watchlist');
      }
      const card = document.getElementById('drawer');
      if (card && !card.hidden && card.dataset.w && typeof syncStar === 'function') syncStar(card.dataset.w);
      const saved = !!(me && me.analyses && me.analyses[jobId]);
      sjob.innerHTML = EarlyIcon(saved ? 'star-on' : 'star') + '<span>' + (saved ? 'Saved' : 'Save analysis') + '</span>'; sjob.classList.toggle('on', saved);
      sjob.title = saved ? 'In My analyses · click to remove' : 'Keep this analysis under My analyses';
      hasLists = !!(me && me.wallets && Object.keys(me.wallets).length);   // «Only my watchlist» appears with the first saved wallet
      fillPanel(); refreshRows();                                // your tags reach the rows with the account
      try { myChip(); } catch (e) {}                               // the agent's question about them, once the account is known
      if (f.mine) apply();                                     // «My lists» needs the account to know which rows stay
    }
    async function loadMe() {
      if (!acctOn) return;
      try { const r = await fetch('/me.json', { credentials: 'same-origin', cache: 'no-store' }); if (r.ok) me = await r.json(); } catch (e) {}
      markSaved();
    }
    const withAcct = fn => acctOn ? fn() : EarlyWallet.open(() => { acctOn = true; loadMe().then(fn); });
    const blank = () => { me = me || { wallets: {}, analyses: {} }; };
    // one click on an empty star: the wallet is in the Watchlist, and the star is filled (owner, 02.10)
    async function starWallet(w, star) {
      if (inList(w)) { openLists(star, [w]); return; }
      try {
        const d = await addToList('main', [w]);
        EarlyUI.use('star', { on: true });
        EarlyUI.toast((d.added ? 'Added to your watchlist' : 'Already in your watchlist') + ' · the star again picks its lists · <a href="/me#list">Watchlist →</a>');
      } catch (x) { EarlyUI.toast(x.message); }
    }
    async function removeWallets(ws) {
      if (!ws.length) return;
      try {
        const d = await EarlyWallet.post('/me/wallets/remove', { wallets: ws });
        blank(); ws.forEach(w => { delete me.wallets[w]; }); markSaved();
        EarlyUI.toast(d.removed ? plural(d.removed, 'wallet') + ' removed from your watchlist' : 'Not in your watchlist');
      } catch (e) { EarlyUI.toast(e.message); }
    }
    async function saveJob() {
      try {
        const d = await EarlyWallet.post('/me/analyses', { job: jobId });
        EarlyUI.track('save-analysis');
        blank(); me.analyses[jobId] = true; markSaved();
        EarlyUI.toast((d.added ? 'Analysis saved' : 'Already saved') + ' · <a href="/me#analyses">My analyses →</a>');
      } catch (e) { EarlyUI.toast(e.message); }
    }
    async function removeJob() {
      try {
        await EarlyWallet.post('/me/analyses/remove', { job: jobId });
        blank(); delete me.analyses[jobId]; markSaved();
        EarlyUI.toast('Removed from My analyses');
      } catch (e) { EarlyUI.toast(e.message); }
    }
    // the action is what the button said at click time — not what it turns into after a sign-in loads the account
    sjob.addEventListener('click', () => { const saved = !!(me && me.analyses && me.analyses[jobId]); withAcct(() => saved ? removeJob() : saveJob()); });
    loadMe();
    const mkdemo = document.getElementById('mkdemo');
    if (mkdemo) mkdemo.addEventListener('click', async () => {
      if (!confirm('Replace the demo token with this analysis? Its chart is captured now, about a dozen requests.')) return;
      mkdemo.disabled = true; mkdemo.textContent = 'Capturing…';
      try {
        const d = await EarlyWallet.post('/admin/demo', { job: mkdemo.dataset.job });
        mkdemo.textContent = 'This is the demo';
        EarlyUI.toast('The demo is now this analysis · <a href="/token?mint=' + d.mint + '">Open it →</a>', 8000);
      } catch (e) { mkdemo.disabled = false; mkdemo.textContent = 'Make it the demo'; EarlyUI.toast(e.message); }
    });

    let sortKey = 'real', sortDir = -1;                         // the server already sends the rows by PnL, highest first
    const msort = document.getElementById('msort');
    function markSort() {                                       // the head shows the order: its column's mark (v2 redraws the head)
      table.querySelectorAll('th.sortable').forEach(x => x.classList.toggle('desc', x.dataset.key === sortKey && sortDir < 0));
      table.querySelectorAll('th.sortable').forEach(x => x.classList.toggle('asc', x.dataset.key === sortKey && sortDir > 0));
    }
    function sortBy(k, dir, text) {
      sortKey = k; sortDir = dir;
      const val = o => k === 'funder' ? fundKey(o.w) : k === 'inv' ? (+o.tot || +o.inv || 0) : o[k];   // Bought sorts by the number it shows
      order.sort((a, b) => text ? String(val(a) || '').localeCompare(String(val(b) || '')) * dir : ((+val(a) || 0) - (+val(b) || 0)) * dir);
      limit = LIMIT;
      markSort();
      // the list names an order only when it is one of its own; otherwise it says Custom, so any real choice is a change
      const opt = [...msort.options].find(o => o.value === k);
      msort.value = opt && +(opt.dataset.dir || -1) === dir ? k : '';
      apply();
    }
    table.tHead.addEventListener('click', e => {
      const fb = e.target.closest('.hfil');
      if (fb) { if (fpopFor === fb.dataset.fil && !fpop.hidden) closeFilter(); else openFilter(fb.dataset.fil, fb); return; }
      if (e.target.closest('.hcur')) { EarlyCur.toggle(); return; }
      const th = e.target.closest('th.sortable'); if (!th) return;
      const k = th.dataset.key;
      sortBy(k, sortKey === k ? -sortDir : (V2 ? +(th.dataset.dir || -1) : -1), th.dataset.type === 'text');   // v2: First buy and Trip start from the earliest, the lowest
      EarlyUI.use('sort', { key: k, dir: sortDir > 0 ? 'asc' : 'desc', via: 'head' });
    });
    msort.addEventListener('change', () => {
      const o = msort.selectedOptions[0];
      sortBy(o.value, +(o.dataset.dir || -1), false);        // a choice in the list starts from its natural end
      EarlyUI.use('sort', { key: o.value, dir: sortDir > 0 ? 'asc' : 'desc', via: 'menu' });
    });

    const SCOPE = new URLSearchParams(location.search).get('scope') || 'all';
    let data = null;
    async function rowsData() { if (!data) { const r = await fetch('/job/' + jobId + '.json?scope=' + SCOPE); data = await r.json(); } return data; }
    function download(name, text, type) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000); }
    // a cell a spreadsheet would run as a formula (= + - @) starts with a quote, as in the server's CSV of the lists
    const csvCell = v => { if (v == null) return ''; let s = String(v); if (typeof v === 'string' && /^[=+\-@\t\r]/.test(s)) s = "'" + s;
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const WHO = ['name', 'x_handle', 'funder', 'funder_exchange', 'wallet_first_tx_utc'];
    const colsOut = cols => { const i = cols.indexOf('wallet') + 1; return cols.slice(0, i).concat(WHO, cols.slice(i).filter(c => !WHO.includes(c))); };
    function whoOf(w) {
      const idn = idents[w], fnd = funders[w], a = ages[w];
      return { name: EarlyTags.displayName(idn) || '', x_handle: EarlyTags.handle(idn), funder: fnd || '',   // no @: a spreadsheet reads it as a formula
        funder_exchange: fnd && EXCH[fnd] ? EXCH[fnd][0] : '', wallet_first_tx_utc: a && a.exact && a.ms ? new Date(a.ms).toISOString().slice(0, 19).replace('T', ' ') : '' };
    }
    document.getElementById('xpanel').addEventListener('click', async e => {   // by id: a signed-in header has its own .menu-panel first
      const x = e.target.closest('[data-x]'); if (!x) return;
      EarlyUI.track('export', { format: x.dataset.x });
      EarlyUI.use('export', { format: x.dataset.x, filtered: na() > 0 });
      const wallets = pass.map(o => o.w), want = new Set(wallets);
      const suffix = '-' + SCOPE + (na() ? '-filtered' : '');
      if (x.dataset.x === 'txt') { download(jobId + suffix + '.txt', wallets.join('\n') + '\n', 'text/plain'); return; }
      // who each wallet is, right after its address (custdev 01.10): what the page already knows, no new requests
      const d = await rowsData(), rowsOut = d.rows.filter(r => want.has(r.wallet)).map(r => Object.assign({}, r, whoOf(r.wallet)));
      if (x.dataset.x === 'json') { download(jobId + suffix + '.json', JSON.stringify({ ...d, columns: colsOut(d.columns), rows: rowsOut, exported: na() ? 'filtered' : 'all' }, null, 1), 'application/json'); return; }
      const cols = colsOut(d.columns), lines = [cols.join(',')];
      rowsOut.forEach(r => lines.push(cols.map(c => csvCell(r[c])).join(',')));
      download(jobId + suffix + '.csv', lines.join('\n') + '\n', 'text/csv');
    });

    if (V2) {
      headV2(); markSort();
      // the toolbar (canvas Analysis4): Find a wallet is the panel's search; Hide bots hides the bot-like tag, as the
      // panel's chip does; Columns shows, hides and orders the columns; ⋯ holds Export
      const tfind = document.getElementById('tfind'); let tfT = 0;
      tfind.addEventListener('input', () => { clearTimeout(tfT); tfT = later(() => { f.q = tfind.value.trim(); saveF(); limit = LIMIT; apply(); fillPanel(); }, 250); });
      tfind.addEventListener('keydown', e => { if (e.key === 'Escape' && tfind.value) { e.stopPropagation(); tfind.value = ''; f.q = ''; saveF(); limit = LIMIT; apply(); fillPanel(); } });
      document.getElementById('hidebots').addEventListener('click', () => {
        const on = !f.hide.includes('bot-like');
        f.hide = on ? f.hide.concat(['bot-like']) : f.hide.filter(y => y !== 'bot-like');
        saveF(); limit = LIMIT; apply(); fillPanel(); EarlyUI.use('hide', { tag: 'bot-like', on, via: 'toolbar' });
      });
      const colbtn = document.getElementById('colsbtn'), colpanel = document.getElementById('colpanel');
      const drawCols = () => {
        colpanel.innerHTML = '<div class="mh">Show columns</div>' + cols.map((x, i) => '<label class="colrow" draggable="true" data-i="' + i + '" title="Drag, or Alt and an arrow key, to move it">'
          + '<input type="checkbox" data-col="' + x.k + '"' + (x.on ? ' checked' : '') + '><i class="ck" aria-hidden="true"></i><span class="cname">' + COLS[x.k].menu + '</span>'
          + '<span class="grip" aria-hidden="true">' + ag('grip', 12) + '</span></label>').join('') + '<div class="mnote">Drag to reorder. Kept for next time.</div>';
      };
      const colsChanged = () => { saveCols(); headV2(); markSort(); syncHeads(); drawn = []; apply(); EarlyUI.use('columns', { on: shownCols().join(',') }, 1500); };
      const closeCols = () => { colpanel.hidden = true; colbtn.setAttribute('aria-expanded', 'false'); colbtn.classList.remove('open'); };
      colbtn.addEventListener('click', e => {
        e.stopPropagation();
        const open = colpanel.hidden; if (open) drawCols();
        colpanel.hidden = !open; colbtn.setAttribute('aria-expanded', String(open)); colbtn.classList.toggle('open', open);
      });
      colpanel.addEventListener('click', e => e.stopPropagation());
      colpanel.addEventListener('change', e => {
        const x = e.target.closest('[data-col]'); if (!x) return;
        const c = cols.find(y => y.k === x.dataset.col); c.on = x.checked;
        if (!cols.some(y => y.on)) { c.on = true; x.checked = true; return; }   // one column at least
        colsChanged();
      });
      let dragI = null;
      const move = (from, to) => { if (from === to || to < 0 || to >= cols.length) return false; const [c] = cols.splice(from, 1); cols.splice(to, 0, c); return true; };
      colpanel.addEventListener('dragstart', e => { const r = e.target.closest('.colrow'); if (!r) return; dragI = +r.dataset.i; r.classList.add('drag'); try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(dragI)); } catch (x) {} });
      colpanel.addEventListener('dragover', e => { const r = e.target.closest('.colrow'); if (!r || dragI == null) return; e.preventDefault();
        colpanel.querySelectorAll('.colrow.over').forEach(x => x.classList.remove('over')); r.classList.add('over'); });
      colpanel.addEventListener('drop', e => { const r = e.target.closest('.colrow'); if (!r || dragI == null) return; e.preventDefault();
        if (move(dragI, +r.dataset.i)) { drawCols(); colsChanged(); } dragI = null; });
      colpanel.addEventListener('dragend', () => { dragI = null; colpanel.querySelectorAll('.colrow.drag, .colrow.over').forEach(x => x.classList.remove('drag', 'over')); });
      colpanel.addEventListener('keydown', e => {
        if (e.key === 'Escape') { e.stopPropagation(); closeCols(); colbtn.focus(); return; }
        const r = e.target.closest('.colrow'); if (!r || !e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
        e.preventDefault(); const i = +r.dataset.i, j = i + (e.key === 'ArrowUp' ? -1 : 1);
        if (move(i, j)) { drawCols(); colsChanged(); const b = colpanel.querySelector('.colrow[data-i="' + j + '"] input'); if (b) b.focus(); }
      });
      on(document, 'click', () => { if (!colpanel.hidden) closeCols(); });
      on(document, 'keydown', e => { if (e.key === 'Escape' && !colpanel.hidden) closeCols(); });
      const xbtn = document.getElementById('xbtn'), xpanel = document.getElementById('xpanel');
      if (xbtn) {
        xbtn.addEventListener('click', e => { e.stopPropagation(); const open = xpanel.hidden; xpanel.hidden = !open; xbtn.setAttribute('aria-expanded', String(open)); xbtn.classList.toggle('open', open); });
        const shut = () => { xpanel.hidden = true; xbtn.setAttribute('aria-expanded', 'false'); xbtn.classList.remove('open'); };
        xpanel.addEventListener('click', e => { if (e.target.closest('[data-x]')) setTimeout(shut, 0); });
        on(document, 'click', e => { if (!xpanel.hidden && !e.target.closest('#xpanel')) shut(); });
        on(document, 'keydown', e => { if (e.key === 'Escape') shut(); });
      }
    }
    syncHeads(); apply();
    // the buying in the range as small bars under «bought»: when the wallets came in, in 24 steps
    (function buyBars() {
      if (V2) return;                                           // v2's strip has no bars (canvas Analysis4)
      const c = document.querySelector('#tally .tc'); if (!c) return;
      const a = +CFG.from, b = +CFG.to; if (!(b > a)) return;
      const N = 24, n = new Array(N).fill(0);
      all.forEach(o => { const x = +o.etime; if (x >= a && x <= b) n[Math.min(N - 1, Math.floor((x - a) / (b - a) * N))]++; });
      const mx = Math.max(...n); if (!mx) return;
      c.insertAdjacentHTML('beforeend', '<svg class="tsp" viewBox="0 0 ' + (N * 4) + ' 14" preserveAspectRatio="none" aria-hidden="true">'
        + n.map((v, i) => '<rect x="' + (i * 4) + '" y="' + (14 - Math.max(1, Math.round(v / mx * 14))) + '" width="3" height="' + Math.max(1, Math.round(v / mx * 14)) + '"/>').join('') + '</svg>');
      c.title += ' · the bars: when they bought, across the range';
    })();
    // a pointer comes to the first address and clicks it, the address rings, a label says what it does: once the first
    // row is on screen (the table sits under the chart), until the person has opened a card, at most on three visits;
    // gone at the first click or after a few seconds
    (function cardHint() {
      const seen = () => { try { return +localStorage.getItem('early:cardhint') || 0; } catch (e) { return 3; } };
      const a = seen() < 3 && tbody.rows[0] && tbody.rows[0].querySelector('.wname'); if (!a || !window.IntersectionObserver) return;
      const io = new IntersectionObserver(es => {
        if (!es.some(x => x.isIntersecting)) return;
        io.disconnect();
        const n = seen(); if (n >= 3 || !a.isConnected) return;
        try { localStorage.setItem('early:cardhint', String(n + 1)); } catch (e) {}
        const h = document.createElement('span'); h.className = 'chint'; h.setAttribute('aria-hidden', 'true');
        h.innerHTML = '<svg class="chint-cur" viewBox="0 0 16 22"><path d="M1.5 1.5v16.2l4.3-4.1 2.8 6.4 2.8-1.2-2.8-6.3h5.9z"/></svg><span class="chint-tip">' + (matchMedia('(max-width: 640px)').matches ? 'Tap a wallet: its card opens' : 'Click an address: its card opens') + '</span>';
        a.classList.add('hinted'); a.appendChild(h);
        const done = () => { h.remove(); a.classList.remove('hinted'); document.removeEventListener('pointerdown', done, true); };
        on(document, 'pointerdown', done, true); later(done, 7000);
      }, { threshold: 1, rootMargin: '0px 0px -12% 0px' });
      io.observe(a); off.push(() => io.disconnect());
    })();
    // the chart is the page's (owner, 09.10): this result puts its exit line and its wallets on it, and takes them off
    ch.setOnMarkers(m => { const h = document.getElementById('mhint'); if (!h) return; h.hidden = !m.total; h.textContent = m.inView > m.labeled ? 'Amounts for the ' + m.labeled + ' largest of ' + m.inView + ' trades in view — zoom in for all' : ''; if (!h.textContent) h.hidden = true; });
    ch.setExit(CFG.exit || null);

    // wallet story: markers on the chart (green bought, red sold; a ring when the wallet shares a funder) + the drawer
    // v2: the wallets on the chart stand in the chart's toolbar, the range line and Save in the tabs' row (canvas Analysis4)
    const ctw = V2 ? document.getElementById('ctw') : null;
    const bar = ctw || document.getElementById('onchart');
    const rheadEl = root.querySelector('.rhead'), tabsres = V2 ? document.getElementById('tabsres') : null;
    if (rheadEl && tabsres) { tabsres.innerHTML = ''; tabsres.appendChild(rheadEl); }
    if (ctw) { ctw.innerHTML = ''; ctw.hidden = true; }
    const drawer = document.getElementById('drawer'), dtrades = document.getElementById('dtrades');
    // the symbol is whatever the token's creator wrote, so it is escaped like every other one
    const crossLine = c => esc(c.symbol || c.mint.slice(0, 6)) + ' · ' + EarlyTZ.fmt(c.from, false) + ' → ' + EarlyTZ.fmt(c.to, false)
      + (c.mult ? ' · ' + (+c.mult).toFixed(1) + '×' : '') + (c.real ? ' · ' + money(c.real) : '');
    function fillCrossings() {
      // a repeat is a fact about this wallet, so it belongs with the other tags (and the Hide chips); the card holds the detail
      let n = 0;
      Object.keys(crossings).forEach(w => {
        const o = byW.get(w); if (!o || !crossings[w] || !crossings[w].length) return;
        n++;
        if (!o.tags.includes('seen-before')) o.tags.push('seen-before');
      });
      const wrap = document.getElementById('fseenwrap');
      if (wrap) wrap.hidden = !n;
    }
    function fillFunders() {
      // funders arrive after the page: the bundles are recounted and the drawn rows patched
      rebundle(); refreshRows();
    }
    async function loadCrossings() {
      if (!acctOn) return;
      try {
        const r = await fetch('/job/' + jobId + '/crossings.json', { credentials: 'same-origin' });
        if (!r.ok) return;
        const d = await r.json();
        if (!alive) return;
        crossings = d.wallets || {};
        fillCrossings(); apply();
      } catch (e) {}
    }
    function renderOnChart() {
      if (!alive) return;                                        // an answer that came after this result was closed
      bar.innerHTML = ''; bar.hidden = !onChart.length;
      pinned.clear(); onChart.forEach(o => pinned.add(o.wallet));
      if (onChart.length) {
        if (!V2) { const l = document.createElement('span'); l.className = 'muted small'; l.textContent = 'On the chart:'; bar.appendChild(l); }
        onChart.forEach(o => {
          const c = document.createElement('span'); c.className = 'chipw';
          const nm = V2 ? EarlyTags.displayName(idents[o.wallet]) : '';
          c.innerHTML = V2 ? face(o.wallet) + (nm ? '<span class="cn">' + esc(nm) + '</span>' : '<span class="mono">' + short(o.wallet) + '</span>')
            : '<span class="mono">' + short(o.wallet) + '</span> ';
          c.title = V2 ? 'Its trades are on the chart · click for its card' : 'Stays visible when filtered · click for the story';
          c.addEventListener('click', ev => { if (!ev.target.closest('.x')) { cardSrc = 'chart'; dropViaCard(o.wallet); openStory(o); } });
          const x = document.createElement('button'); x.type = 'button'; x.className = 'ghost x'; x.textContent = '×'; x.title = 'Remove from chart';
          if (V2) x.setAttribute('aria-label', 'Remove from the chart');
          x.addEventListener('click', () => { if (viaCard === o.wallet) viaCard = null; onChart.splice(onChart.indexOf(o), 1); if (drawer.dataset.w === o.wallet) closeCard(); renderOnChart(); });
          c.appendChild(x); bar.appendChild(c);
        });
      }
      ch.setWalletMarkers(onChart);
      apply();
    }
    // the wallet card: what this wallet did on this token, who it is if anyone knows, how it trades overall, where its SOL came from
    const rowOf = w => byW.get(w);
    const MAX_TAGS = CFG.max_tags;
    const PLUS = EarlyIcon('add');
    const dtags = document.getElementById('dtags'), dstar = document.getElementById('dstar'), dprof = document.getElementById('dprof');
    const profiles = new Map();
    const myTags = w => (me && me.wallets && me.wallets[w] && me.wallets[w].my_tags) || [];
    function closeCard() {                                     // the agent's panel under the card keeps the page still
      drawer.hidden = true;
      document.body.classList.toggle('drawer-open', !document.getElementById('apanel').hidden);
      markCarded('');
    }
    // the table row of the open card is marked
    function markCarded(w) {
      tbody.querySelectorAll('tr.carded').forEach(r => r.classList.remove('carded'));
      const tr = w ? tbody.querySelector('tr[data-w="' + CSS.escape(w) + '"]') : null;
      if (tr) tr.classList.add('carded');
    }
    function syncStar(w) {
      const on = inList(w);
      dstar.innerHTML = V2 ? ag('star', 16) + '<span>' + (on ? 'Watching' : 'Watch') + '</span>' : EarlyIcon(on ? 'star-on' : 'star'); dstar.classList.toggle('on', on);
      dstar.title = on ? 'In your watchlist · click to change' : 'Add to your watchlist'; dstar.setAttribute('aria-label', dstar.title);
    }
    // your tag goes only by its own × (owner, 02.10: a click on the word dropped it by accident)
    const MINE = t => '<span class="tag mine" title="Your tag"><span>' + esc(t) + '</span><button type="button" class="tagx" data-tag="' + esc(t)
      + '" title="Remove this tag" aria-label="Remove the tag ' + esc(t) + '">×</button></span>';
    function renderTags(w) {
      // our tags as picture and word, then the person's own; seen-before has its own block further down
      const row = rowOf(w), mine = myTags(w);
      const ours = row ? row.tags.filter(t => t && !QUIET.has(t))
        .map(t => EarlyTags.chip(t === 'bundle' && bundle[w] ? 'bundle ×' + bundle[w].n : t, TAGDEF[t], { text: true })).join('') : '';
      dtags.innerHTML = ours + mine.map(MINE).join('')
        + (mine.length < MAX_TAGS ? '<input type="text" class="tagin" maxlength="24" aria-label="New tag" hidden><button type="button" class="tagadd wide" title="Your own tag for this wallet" aria-label="Add your own tag">' + PLUS + '<span>tag</span></button>' : '');
    }
    function renderHead(w) {
      const idn = idents[w];
      document.getElementById('dav').innerHTML = idn && idn.avatar
        ? '<img src="' + esc(idn.avatar) + '" alt="" referrerpolicy="no-referrer">' : EarlyCard.identicon(w);
      document.getElementById('dname').textContent = EarlyTags.displayName(idn) || 'Wallet';
      document.getElementById('dids').innerHTML = EarlyTags.idMarks(idn);
      if (V2) {                                                 // no name: the address is the title; a long one a step smaller
        const nm = EarlyTags.displayName(idn) || '';
        drawer.classList.toggle('noname', !nm); document.getElementById('dname').classList.toggle('long', nm.length > 8);
      }
    }
    function renderIdent(w) {
      renderHead(w);
      const idn = idents[w];
      const shown = EarlyTags.displayName(idn);                // the other name it goes by, and its .sol domain, on hover
      document.getElementById('dname').title = idn ? [idn.name && idn.name !== shown ? idn.name : '', idn.sns || ''].filter(Boolean).join(' · ') : '';
    }
    const rankOf = new Map(all.map((o, i) => [o.w, i])), AGE_N = CFG.age_n, ageTried = new Map();
    const AGE_READ = CFG.age_read;                   // the age check reads this many of a wallet's latest transactions
    async function loadAge(w) {
      // the analysis checks every wallet cheaply and the first ones by PnL fully; what the cheap check left open
      // (a busy wallet's age, an app wallet's first SOL) and the wallets of older results are read when a card opens
      if (ageTried.has(w)) return;
      ageTried.set(w, 'busy');
      let r, d = {};
      try { r = await fetch('/wallet_age.json?' + new URLSearchParams({ job: jobId, wallet: w }), { credentials: 'same-origin' }); d = await r.json(); }
      catch (e) { if (!alive) return; ageTried.set(w, 'failed'); if (drawer.dataset.w === w) renderWalletInfo(w); return; }
      if (!alive) return;                                        // another tab is open now: its card has the same ids
      if (r.status === 401) { ageTried.set(w, 'connect'); if (drawer.dataset.w === w) renderWalletInfo(w); return; }
      if (!r.ok) { ageTried.set(w, 'failed'); if (drawer.dataset.w === w) renderWalletInfo(w); return; }
      if (d.age) ages[w] = d.age;
      if (d.funder) funders[w] = d.funder;
      const o = byW.get(w);
      if (d.fresh && o && !o.tags.includes('fresh')) o.tags.unshift('fresh');
      ageTried.set(w, d.paused ? 'paused' : d.capped ? 'capped' : d.checked === false ? 'unchecked' : 'done');   // unchecked: the server did not look, which says nothing about the wallet
      if (d.fresh || d.funder) fillFunders();
      if (drawer.dataset.w === w) renderWalletInfo(w);
    }
    const ageText = ms => { const d = (Date.now() - ms) / 86400000;
      return d >= 365 ? (d / 365).toFixed(d >= 3650 ? 0 : 1) + 'y' : d >= 1 ? Math.floor(d) + 'd' : Math.max(1, Math.floor(d * 24)) + 'h'; };
    function renderWalletInfo(w) {
      const a = ages[w], fnd = funders[w], bn = bundle[w], out = [];
      const queued = !ageDone && (rankOf.get(w) ?? 1e9) < AGE_N;
      if ((!(a && a.ms) || !a.exact || !fnd) && !queued && !ageTried.get(w) && AGE_N) loadAge(w);   // the server reads deeper, once, or answers from what it has
      const st = ageTried.get(w);                               // 'busy' from here on while that request runs
      if (a && a.ms && a.exact) {
        const young = Date.now() - a.ms < 86400000, row = byW.get(w), at = row && +row.etime;
        if (row && row.tags.includes('fresh') && at > a.ms)                 // fresh is about the buy: "17h at buy", not "15d" today
          out.push('<span class="dchip age young" title="' + ageText(Date.now() - (at - a.ms)) + ' old at its first buy here · created '
            + EarlyTZ.fmt(a.ms, true) + '">' + ageText(Date.now() - (at - a.ms)) + ' at buy</span>');
        else out.push('<span class="dchip age' + (young ? ' young' : '') + '" title="First transaction ' + EarlyTZ.fmt(a.ms, true) + '">' + ageText(a.ms) + ' old</span>');
      } else if (a && a.ms) {
        // a busy wallet: its latest transactions end before its first one, so the age is unknown, not "at least 12 days".
        // Opening the card reads deeper; until that answers, or when it cannot, the count says why
        const n = +a.n || AGE_READ, reading = st === 'busy';
        const why = reading ? 'Reading its whole history…'
          : 'Over ' + nf(n) + ' transactions, read back to ' + EarlyTZ.fmt(a.ms, true) + ': its first one is older.'
            + (st === 'connect' ? ' Connect a wallet to read all of it.' : st === 'capped' ? ' Card checks used up today.'
               : st === 'paused' ? ' Age checks paused till next month.' : st === 'failed' ? ' The node did not answer; reopen the card.' : '');
        const text = reading ? '…' : Math.floor(n / 1000) + 'k+ tx';
        out.push(st === 'connect' ? '<button type="button" class="dchip age" id="dagego" title="' + why + '">' + text + '</button>'
          : '<span class="dchip age' + (reading ? ' q' : '') + '" title="' + why + '">' + text + '</span>');
      } else if (AGE_N) {
        const busy = queued || st === 'busy' || !st;
        const why = busy ? 'Checking the wallet\'s age…' : st === 'connect' ? 'Connect a wallet to check its age and funder'
          : st === 'paused' ? 'Age checks are paused until next month: their budget is used up'
          : st === 'capped' ? 'Today\'s age checks from wallet cards are used up. More tomorrow'
          : st === 'failed' ? 'The chain node did not answer. Reopen the card to try again'
          : st === 'unchecked' ? 'Age not checked for this wallet' : 'No transaction history found';
        out.push(st === 'connect' ? '<button type="button" class="dchip age q" id="dagego" title="' + why + '">age?</button>'
          : '<span class="dchip age q" title="' + why + '">' + (busy ? '…' : '?') + '</span>');
      }
      if (DORM[w]) out.push('<span class="dchip dorm" title="Nothing touched the wallet for ' + DORM[w] + ' days before its first buy here">quiet ' + DORM[w] + 'd before</span>');
      if (fnd && EXCH[fnd]) out.push('<button type="button" class="dchip fund cex" id="dfund" data-fund="x:' + esc(EXCH[fnd][0]) + '" title="First SOL came straight from '
        + (EXCH[fnd][2] ? fnd + ', an exchange in InsightX\'s labels' : esc(EXCH[fnd][1]) + ' (' + fnd + '), an exchange') + (bn && bn.n > 1 ? ', together with ' + (bn.n - 1) + ' wallets born in the same minutes (bundle)' : '')
        + ' · click to show every wallet funded from ' + esc(EXCH[fnd][0]) + ' here"><span class="dl">funded by</span>' + esc(EXCH[fnd][0]) + (bn && bn.n > 1 ? '<small>×' + bn.n + '</small>' : '') + '</button>');
      else if (fnd && FLAB[fnd]) out.push('<button type="button" class="dchip fund cex" id="dfund" data-fund="' + fnd + '" title="First SOL came from '
        + (FLAB[fnd][1] ? esc(FLAB[fnd][1]) + ' (' + fnd + '), ' : fnd + ', ') + esc(FLAB[fnd][2] || 'a known service') + (FLAB[fnd][1] ? '' : ' in InsightX\'s labels') + ' · click to show every wallet it funded here"><span class="dl">funded by</span>'
        + esc(FLAB[fnd][0]) + (bn && bn.n > 1 ? '<small>×' + bn.n + '</small>' : '') + '</button>');
      else if (fnd) out.push('<button type="button" class="dchip fund" id="dfund" data-fund="' + fnd + '" title="First SOL came from '
        + fnd + (bn && bn.n > 1 ? ', which funded ' + bn.n + ' wallets here (bundle)' : services.has(fnd) ? ', an exchange or an app: over 1,000 transactions a day, so the wallets it funded are not a bundle' : '')
        + ' · click to show every wallet it funded here"><span class="dl">funded by</span><span class="mono">' + short(fnd) + '</span>' + (bn && bn.n > 1 ? '<small>×' + bn.n + '</small>' : '') + '</button>');
      document.getElementById('dchips').innerHTML = out.join('');
      const df = document.getElementById('dfund');
      if (df) df.addEventListener('click', () => {                   // the table shows who else this funder paid for
        f.funder = df.dataset.fund; saveF(); limit = LIMIT; apply(); closeCard();
        EarlyUI.use('funder', { on: true });
        EarlyUI.toast('Showing the wallets funded by ' + fundLabel(df.dataset.fund) + ' · Reset in the filters clears it');
      });
      const go = document.getElementById('dagego');
      if (go) go.addEventListener('click', () => EarlyWallet.open(() => { acctOn = true; ageTried.delete(w); loadMe().then(() => loadAge(w)); }));
    }
    const nf = v => (+v || 0).toLocaleString('en-US');
    let period = '30';
    function renderProfile(all) {                               // the same block as a ready list's card: static/card.js
      if (V2) dprof.closest('.dperf').classList.remove('guest');
      EarlyCard.render(all, period, dprof, document.getElementById('dprofi'));
      document.querySelectorAll('#dper [data-p]').forEach(b => b.classList.toggle('on', b.dataset.p === period));
    }
    document.getElementById('dper').addEventListener('click', e => {
      const b = e.target.closest('[data-p]'); if (!b) return;
      period = b.dataset.p;
      EarlyUI.use('card-period', { p: period });
      const p = profiles.get(drawer.dataset.w);
      if (p) renderProfile(p); else document.querySelectorAll('#dper [data-p]').forEach(x => x.classList.toggle('on', x.dataset.p === period));
    });
    async function loadProfile(w) {
      if (profiles.has(w)) { renderProfile(profiles.get(w)); return; }
      dprof.innerHTML = '<div class="dskel"><i></i><i></i><i></i></div>';
      document.getElementById('dprofi').hidden = true;
      let r;
      try { r = await fetch('/wallet_profile.json?' + new URLSearchParams({ job: jobId, wallet: w }), { credentials: 'same-origin' }); }
      catch (e) { if (alive && drawer.dataset.w === w) dprof.innerHTML = '<p class="dline muted small">Could not reach the server.</p>'; return; }
      if (!alive || drawer.dataset.w !== w) return;         // the card moved on to another wallet, or another tab is open
      if (r.status === 401) {
        dprof.innerHTML = V2 ? '<div class="dconnect"><span><b>Its 30 days on every token</b><small>PnL, win rate, hours it trades</small></span><button type="button" class="dcgo" id="dprofgo">Connect</button></div>'
          : '<div class="dconnect"><button type="button" class="primary" id="dprofgo">Connect wallet for more data</button>'
          + '<span class="muted small">PnL, win rate and active hours across all its tokens</span></div>';
        if (V2) dprof.closest('.dperf').classList.add('guest');
        document.getElementById('dprofgo').addEventListener('click', () => EarlyWallet.open(() => { acctOn = true; loadMe().then(() => loadProfile(w)); }, 'Connect a wallet to see all its tokens.'));
        return;
      }
      let d = {}; try { d = await r.json(); } catch (e) {}
      if (!alive) return;
      if (drawer.dataset.w !== w) { if (r.ok) profiles.set(w, d); return; }   // reading the body took time too: keep it, but not on another wallet's card
      if (!r.ok) { dprof.innerHTML = '<p class="dline muted small">' + esc(d.error || 'Could not load this wallet.') + '</p>'; return; }
      profiles.set(w, d); renderProfile(d);
    }
    async function saveMyTags(w, tags) {
      let ok = true;
      try {
        const d = await EarlyWallet.post('/me/wallets/tags', { wallet: w, tags });
        blank(); me.wallets[w] = me.wallets[w] || {}; me.wallets[w].my_tags = d.tags || [];
      } catch (e) { EarlyUI.toast(e.message); ok = false; }
      if (drawer.dataset.w === w) renderTags(w);
      refreshRows();
      return ok;
    }
    async function dropTag(w, tag) {                            // and one Undo brings it back
      const before = myTags(w).slice();
      if (!await saveMyTags(w, before.filter(t => t !== tag))) return;
      EarlyUI.toast('Tag «' + esc(tag) + '» removed · <button type="button" class="link" id="tagundo">Undo</button>', 6000);
      const u = document.getElementById('tagundo');
      if (u) u.addEventListener('click', () => { saveMyTags(w, before); const box = u.closest('.toast'); if (box) box.hidden = true; });
    }
    async function addOne(w) {
      try {
        const d = await EarlyWallet.post('/me/wallets', { job: jobId, wallets: [w] });
        noteIn([w], d.list || 'main'); markSaved(); return true;
      } catch (e) { EarlyUI.toast(e.message); return false; }
    }
    document.getElementById('dmore').addEventListener('click', e => {
      if (V2) {                                                 // v2: the line opens every trade and closes them again
        const dt = document.getElementById('dtable'), open = dt.hidden; dt.hidden = !open;
        e.currentTarget.textContent = open ? 'Hide the trades' : 'Show every trade'; e.currentTarget.setAttribute('aria-expanded', String(open));
        if (open) EarlyUI.use('card-trades-all');
        return;
      }
      document.getElementById('dtable').classList.remove('clip'); e.currentTarget.hidden = true;
      EarlyUI.use('card-trades-all');
    });
    // v2: Share copies a link that opens this analysis with this card (a phone's own share sheet where there is one)
    const dshare = document.getElementById('dshare');
    if (dshare) dshare.addEventListener('click', () => {
      const w = drawer.dataset.w; if (!w) return;
      const url = location.origin + '/job/' + encodeURIComponent(jobId) + '?w=' + encodeURIComponent(w);
      EarlyUI.use('card-share');
      if (navigator.share && matchMedia('(pointer: coarse)').matches) { navigator.share({ url, title: (CFG.symbol || 'tracced') + ' · a wallet on tracced' }).catch(() => {}); return; }
      if (!navigator.clipboard) { EarlyUI.toast(esc(url), 8000); return; }
      navigator.clipboard.writeText(url).then(() => EarlyUI.toast('Link copied: it opens this analysis with this card'), () => EarlyUI.toast(esc(url), 8000));
    });
    // what it did here, as the row says it, a number and a word each: on a phone the row is under the card
    function renderTokFacts(w) {
      const o = rowOf(w), el = document.getElementById('dtally'); if (!o) { el.innerHTML = ''; return; }
      const amt = (usd, sol) => SOLON && sol != null ? '<span class="insol">' + EarlyCur.sol(sol) + '</span>' : money(usd);
      const cell = (v, l, cls, tip) => '<span class="tc"' + (tip ? ' title="' + esc(tip) + '"' : '') + '><b class="' + (cls || '') + '">' + v + '</b><i>' + l + '</i></span>';
      const more = o.tot > o.inv + 0.01;                        // owner, 11.10: «bought $32, sold $13K» read as a mistake
      el.innerHTML = cell(amt(o.tot || o.inv, o.totsol != null ? o.totsol : o.invsol), 'bought', '',
          (more ? money(o.inv) + ' of it inside the range, at a ' : 'All of it inside the range, at a ') + (o.entry ? fm(o.entry) : '—') + ' market cap')
        + cell(o.got ? amt(o.got, o.gotsol) : '—', 'sold', '', soldPct(o.sold) + ' of its tokens' + (o.exitcap ? ', at a ' + fm(o.exitcap) + ' cap on average' : ''))
        + (o.sells == null ? cell('—', 'PnL', '', 'Its sells were not read: only the largest buyers\' are')
          : cell(amt(o.real, o.realsol), 'PnL', o.real > 0 ? 'pos' : o.real < 0 ? 'neg' : '', o.unreal ? money(o.unreal) + ' on ' + leftPct(o.sold) + ' left' : ''))
        + cell(roiX(o.mult), 'ROI', o.mult ? (o.mult >= 1 ? 'pos' : 'neg') : '', o.mult ? roiPct(o.mult) : 'Nothing sold yet')
        + cell(holdText(o.hold), 'held', '', 'How long it held what it sold, on average, weighted by amount');
    }
    // v2: what it did here is the card's first block (canvas Analysis4): its result large, the multiple and the hold, its
    // trip from the average entry to the average exit with the cap now, then its buys and its sells, each in one line
    const capRange = (a, b) => { const x = fm(a), y = fm(b); if (x === y) return x; const sx = x.slice(-1), sy = y.slice(-1);
      return /[KMB]/.test(sx) && sx === sy ? x.slice(0, -1) + '–' + y : x + '–' + y; };
    function renderPos(w, st) {
      const o = rowOf(w), el = document.getElementById('dpos'), gr = document.getElementById('dgroups');
      if (!o) { el.innerHTML = gr.innerHTML = ''; return; }
      const unk = o.sells == null, a = +o.eavg || +o.entry, b = +o.exitcap, vals = [a, b, NOWCAP].filter(v => v > 0);
      const sc = vals.length ? { lo: Math.log10(Math.min(...vals)) - 0.25, hi: Math.log10(Math.max(...vals)) + 0.25 } : null;
      const W = 320, X = v => { const x = tripX(v, W, sc); return x == null ? null : x / W * 100; };
      const lab = [];
      if (a) lab.push([X(a), fm(a) + ' in', 'in']);
      if (b) lab.push([X(b), fm(b) + ' out', b >= a ? 'out pos' : 'out neg']);
      if (NOWCAP) lab.push([X(NOWCAP), fm(NOWCAP) + ' now', 'now']);
      lab.sort((p, q) => p[0] - q[0]);                          // along the line, never one on top of another
      for (let i = 1; i < lab.length; i++) if (lab[i][0] - lab[i - 1][0] < 24) lab[i][0] = lab[i - 1][0] + 24;
      if (lab.length && lab[lab.length - 1][0] > 88) { lab[lab.length - 1][0] = 88; for (let i = lab.length - 2; i >= 0; i--) if (lab[i + 1][0] - lab[i][0] < 24) lab[i][0] = lab[i + 1][0] - 24; }
      lab.forEach(l => { l[0] = Math.max(10, l[0]); });
      const cls = o.real > 0 ? 'pos' : o.real < 0 ? 'neg' : '';
      el.innerHTML = '<div class="dp-top"><span class="dp-pnl" title="Profit on what it sold here">' + (unk ? '<b>—</b>' : amt2(o.real, o.realsol, cls, true)) + '</span>'
        + '<span class="dp-sub">' + (o.mult ? roiX(o.mult) : unk ? 'exits not read' : 'nothing sold yet') + (o.hold != null ? ' · ' + holdText(o.hold) : '') + '</span></div>'
        + (sc ? '<div class="dp-trip" title="Average entry → average exit' + (NOWCAP ? ' · the dashed tick: the cap now' : '') + '">' + tripSvg(o, W, 30, sc, true)
          + '<div class="dp-lab">' + lab.map(l => '<span class="' + l[2] + '" style="left:' + l[0].toFixed(1) + '%">' + l[1] + '</span>').join('') + '</div></div>' : '')
        + (o.unreal ? '<p class="dp-un"><span class="' + (o.unreal > 0 ? 'pos' : 'neg') + '">' + sgn(o.unreal) + '</span> on the ' + leftPct(o.sold) + ' it still holds</p>' : '');
      const tr = (st && st.trades) || [], A = +CFG.from, B = +CFG.to;
      const grp = side => {
        const ts = tr.filter(t => t.side === side); if (!ts.length) return '';
        const sum = ts.reduce((s, t) => s + (+t.usd || 0), 0), sol = ts.every(t => t.sol != null) ? ts.reduce((s, t) => s + (+t.sol || 0), 0) : null;
        const tt = ts.map(t => +t.t), t0 = Math.min(...tt), t1 = Math.max(...tt), caps = ts.map(t => +t.mcap).filter(v => v > 0);
        const inR = ts.filter(t => t.t >= A && t.t <= B).length;
        const where = side === 'buy' ? (inR === ts.length ? 'inside the range' : !inR ? (t1 < A ? 'before the range' : 'after the range') : inR + ' inside the range')
          : (t0 > B ? holdText((t0 - B) / 60000) + ' after the range' : inR === ts.length ? 'inside the range' : 'from inside the range');
        const f0 = fmtHM(t0), f1 = fmtHM(t1);
        const span = f0 + (t1 - t0 >= 60000 ? '–' + (f1.split(', ')[0] === f0.split(', ')[0] ? f1.replace(/^.*, /, '') : f1) : '');
        return '<div class="dg ' + side + '"><span class="dg-ic" aria-hidden="true">' + (side === 'buy' ? '▲' : '▼') + '</span><span class="dg-t"><b>' + plural(ts.length, side) + ' · '
          + (SOLON && sol != null ? '<span class="insol">' + EarlyCur.sol(sol) + '</span>' : money(sum)) + '</b><small>' + span + ' · ' + where + '</small></span>'
          + '<span class="dg-c" title="Market cap at these trades">' + (caps.length ? capRange(Math.min(...caps), Math.max(...caps)) : '') + '</span></div>';
      };
      gr.innerHTML = grp('buy') + grp('sell');
    }
    let cardSrc = 'row';                                       // where the card was opened from, for the owner's log
    function openStory(o) {
      if (drawer.hidden || drawer.dataset.w !== o.wallet) { EarlyUI.track('card-open'); EarlyUI.use('card-open', { src: cardSrc }); }
      cardSrc = 'row';
      const cur = (window.EarlyCur && EarlyCur.get()) === 'sol';
      const row = rowOf(o.wallet);
      drawer.dataset.w = o.wallet; drawer.hidden = false; document.body.classList.add('drawer-open');
      markCarded(o.wallet);
      const dw = document.getElementById('dw'); dw.textContent = short(o.wallet); dw.dataset.copy = o.wallet; dw.title = o.wallet + ' · click to copy';
      document.getElementById('dsol').href = 'https://solscan.io/account/' + o.wallet;
      syncStar(o.wallet); renderTags(o.wallet); renderIdent(o.wallet);
      // the first six on top, the rest behind «Show all»: a busy wallet's trades would push its card far down (owner, 08.10)
      const SHOW = 6, dmore = document.getElementById('dmore');
      if (V2) {                                                 // v2: every trade behind one line under the two groups
        const dt = document.getElementById('dtable'); dt.classList.remove('clip'); dt.hidden = true;
        dmore.hidden = !o.trades.length; dmore.textContent = 'Show every trade'; dmore.setAttribute('aria-expanded', 'false');
      } else {
      document.getElementById('dtable').classList.add('clip');
      dmore.hidden = o.trades.length <= SHOW; dmore.textContent = 'Show all ' + o.trades.length + ' trades';
      }
      dtrades.innerHTML = o.trades.map((t, i) => '<tr class="' + t.side + (i >= SHOW ? ' xtra' : '') + '"><td class="mono dtc" data-ms="' + t.t + '">' + EarlyTZ.fmt(t.t, false) + '</td><td>' + (t.side === 'buy' ? '<b class="buy">▲ buy</b>' : '<b class="sell">▼ sell</b>') + '</td><td class="num mono">' + (cur && t.sol != null ? EarlyCur.solHtml(t.sol) : money(t.usd)) + '</td><td class="num mono">' + (t.qty ? ch.fmtMcap(t.qty) : '—') + '</td><td class="num mono">' + ch.fmtMcap(t.mcap) + '</td></tr>').join('');
      const cx = crossings[o.wallet] || [];
      document.getElementById('dcross').innerHTML = cx.length
        ? '<b>' + CHAIN + ' Seen in ' + cx.length + ' of your other analyses</b><ul>' + cx.map(c =>
            '<li><a href="/job/' + encodeURIComponent(c.job) + '">' + crossLine(c) + '</a></li>').join('') + '</ul>'
        : '';
      document.getElementById('dwsec').hidden = !cx.length;
      renderWalletInfo(o.wallet);
      const sells = row && row.sells != null ? +row.sells : o.trades.filter(t => t.side === 'sell').length;   // the row counts every sell; the list stops at 200
      document.getElementById('dtcount').textContent = !row ? '' : V2 ? money(row.tot || row.inv) + ' in · ' + (row.got ? money(row.got) : '$0') + ' out · ' + plural((+row.buys || 0) + sells, 'trade')
        : plural(+row.buys || 0, 'buy') + ' · ' + plural(sells, 'sell');
      document.getElementById('dnote').textContent = (o.complete === false ? 'Exits not fetched (over the cap): only trades inside the range are known. ' : '')
        + (o.truncated ? 'First ' + o.trades.length + ' of ' + o.n + '.' : '');
      if (V2) renderPos(o.wallet, o); else renderTokFacts(o.wallet);
      loadProfile(o.wallet);
      try { localStorage.setItem('early:cardhint', '3'); } catch (e) {}   // found the card: the hint has done its job
      if (window.EarlyTZ) EarlyTZ.apply();
    }
    document.getElementById('dclose').addEventListener('click', () => { closeCard(); EarlyUI.use('card-close'); });
    on(document, 'keydown', e => { if (e.key === 'Escape' && !drawer.hidden) { closeCard(); EarlyUI.use('card-close'); } });
    dstar.addEventListener('click', () => { const w = drawer.dataset.w; withAcct(() => starWallet(w, dstar)); });   // the card's star works as the row's
    // your own tags: a tag is a reason to watch, so tagging a wallet that is not watched yet adds it to the watchlist
    dtags.addEventListener('click', e => {
      const w = drawer.dataset.w, x = e.target.closest('.tagx');
      if (x) { dropTag(w, x.dataset.tag); return; }
      if (!e.target.closest('.tagadd')) return;
      withAcct(async () => {
        if (!inList(w) && !(await addOne(w))) return;
        if (drawer.dataset.w !== w) return;
        renderTags(w); syncStar(w);
        const inp = dtags.querySelector('.tagin'), add = dtags.querySelector('.tagadd');
        if (inp) { inp.hidden = false; if (add) add.hidden = true; inp.focus(); }
      });
    });
    dtags.addEventListener('keydown', e => {
      const inp = e.target.closest('.tagin'); if (!inp) return;
      const w = drawer.dataset.w;
      if (e.key === 'Escape') { e.stopPropagation(); renderTags(w); return; }
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const v = inp.value.trim();
      if (!v) { renderTags(w); return; }
      saveMyTags(w, myTags(w).concat([v]));
    });
    dtags.addEventListener('focusout', e => { const inp = e.target.closest('.tagin'); if (inp && !inp.value.trim()) setTimeout(() => { if (document.activeElement !== inp) renderTags(drawer.dataset.w); }, 150); });
    let lastAsked = null;                                      // the card a click asked for last: a slower answer for an earlier one does not replace it
    // the wallet a card put on the chart, not one pinned with the row's chart icon: the next card takes its place, so
    // opening three cards in a row leaves one wallet's trades on the chart, not three (owner, 11.10)
    let viaCard = null;
    const dropViaCard = keep => {
      if (!viaCard || viaCard === keep) return;
      const j = onChart.findIndex(o => o.wallet === viaCard); viaCard = null;
      if (j >= 0) { onChart.splice(j, 1); renderOnChart(); }
    };
    async function toggleWallet(w, story) {
      if (story) { lastAsked = w; dropViaCard(w); }
      const i = onChart.findIndex(o => o.wallet === w);
      if (!story && w === viaCard) viaCard = null;             // the chart icon on that wallet: from now on it is the user's own choice
      if (i >= 0) { if (story) { openStory(onChart[i]); return; } onChart.splice(i, 1); if (drawer.dataset.w === w) closeCard(); renderOnChart(); return; }
      const full = onChart.length >= MAX_ON_CHART;
      if (full && !story) { EarlyUI.toast(MAX_ON_CHART + ' wallets on the chart is the limit — remove one to add another'); return; }   // before paying for the trades
      const r = await fetch('/wallet_trades.json?' + new URLSearchParams({ job: jobId, wallet: w }));
      if (!alive) return;                                      // another tab is open now: nothing of this one lands there
      if (!r.ok) {                                             // say why, never a dead click
        let err = {}; try { err = await r.json(); } catch (e) {}
        if (r.status === 401) EarlyWallet.open(null, 'Connect a wallet to load its trades.'); else EarlyUI.toast(err.error || 'Could not load this wallet.');
        return;
      }
      const d = await r.json();
      if (!alive) return;
      const had = onChart.find(x => x.wallet === w);           // the row's chart icon and its name can both be in flight: one chart entry
      if (had) { if (story && lastAsked === w) openStory(had); return; }
      const o = { wallet: w, bundleColor: bundleColor(w), trades: d.trades, n: d.n, truncated: d.truncated, complete: d.complete };
      if (onChart.length >= MAX_ON_CHART) {                   // the chart keeps its ten; the card still opens, but only the one asked for last
        if (story && lastAsked === w) openStory(o);
        else if (!story) EarlyUI.toast(MAX_ON_CHART + ' wallets on the chart is the limit — remove one to add another');
        return;
      }
      if (story && lastAsked !== w) return;                    // a card asked for earlier and left: its trades do not land on the chart
      if (story) viaCard = w;
      onChart.push(o); renderOnChart(); if (story && lastAsked === w) openStory(o);
    }
    // every button in a row answers here, so a redrawn row needs no listeners of its own
    tbody.addEventListener('click', e => {
      const tr = e.target.closest('tr'); if (!tr) return;
      const w = tr.dataset.w, s = e.target.closest('.star');
      if (s) { withAcct(() => starWallet(w, s)); return; }
      const bb = e.target.closest('.bundb');
      if (bb) {                                                 // that bundle alone, and a second click brings everyone back
        f.bundle = f.bundle === bb.dataset.bund ? '' : bb.dataset.bund; saveF(); limit = LIMIT; apply();
        EarlyUI.use('funder', { on: !!f.bundle });
        return;
      }
      if (e.target.closest('.t-seen-before.seen')) { cardSrc = 'seen'; toggleWallet(w, true); return; }
      let b = e.target.closest('.mk, .wname');
      if (!b) {                                                 // the rest of the row opens the card too; a selection or a tag stays put
        if (e.target.closest('a, button, input, .tag, .ids') || String(window.getSelection() || '')) return;
        b = tr.querySelector('.wname'); if (!b || b.disabled) return;
      }
      if (b.classList.contains('mk')) EarlyUI.use('pin', { on: !pinned.has(w) });
      b.disabled = true; toggleWallet(w, b.classList.contains('wname')).finally(() => { b.disabled = false; });
    });

    // The agent: quick questions and a summary on demand, then a thread of questions and answers. Asking needs a
    // connected wallet; the server keeps each summary, so one someone already opened costs nothing.
    const apanel = document.getElementById('apanel'), athread = document.getElementById('athread'), aform = document.getElementById('aform');
    const aq = document.getElementById('aq'), aempty = document.getElementById('aempty'), achips = document.getElementById('achips'), aguest = document.getElementById('aguest');
    const ASSIST_ON = !!CFG.assist, aipop = document.getElementById('aipop'), aiwrap = document.getElementById('aiwrap');
    const ALANG = navigator.language || 'en', SUMQ = 'Summary of this pump';
    const QUICK = [...apanel.querySelectorAll('.aqbtn[data-q]')].map(b => b.dataset.q);
    // the agent knows your lists (custdev 01.10): when some of your saved wallets bought here, asking about them is one click
    const MYQ = 'Which of my saved wallets are here?';
    function myChip() {
      if (QUICK.includes(MYQ) || !all.some(o => inList(o.w))) return;
      QUICK.unshift(MYQ);
      const b = document.createElement('button'); b.type = 'button'; b.className = 'aqbtn'; b.dataset.q = MYQ;
      b.innerHTML = aEsc(MYQ) + (V2 ? '' : '<span aria-hidden="true">→</span>');   // v2: no arrows inside buttons
      apanel.querySelector('.aquick').prepend(b);
      aState();
    }
    let aBusy = false, aSummed = false;
    const aEsc = t => esc(String(t == null ? '' : t));
    const aWallet = w => '<div class="awr">' + (V2 && byW.has(w.wallet) ? '<span class="awf" aria-hidden="true">' + face(w.wallet) + '</span>' : '')
      + '<button type="button" class="awallet mono" data-w="' + aEsc(w.wallet) + '" title="Open this wallet\'s card">' + aEsc(w.short) + '</button>'
      + (w.why ? '<span class="awhy">' + aEsc(w.why) + '</span>' : '') + '</div>';
    // the agent writes wallets short ("3idduY…4i4V"); one that matches a single wallet of this analysis becomes a link to its card
    const SHORTS = new Map(); all.forEach(o => { const k = short(o.w); SHORTS.set(k, SHORTS.has(k) ? null : o.w); });
    const aText = t => aEsc(t).replace(/([1-9A-HJ-NP-Za-km-z]{6})(?:…|\.\.\.)([1-9A-HJ-NP-Za-km-z]{4})/g, (m, a, b) => {
      const w = SHORTS.get(a + '…' + b);
      return w ? '<button type="button" class="awallet awin mono" data-w="' + w + '" title="Open this wallet\'s card">' + m + '</button>' : m;
    });
    const aList = items => '<ul>' + items.map(t => '<li>' + aText(t) + '</li>').join('') + '</ul>';
    function aLeft(n) { if (n != null) document.getElementById('aleft').textContent = n + (n === 1 ? ' question' : ' questions') + ' left today.'; }
    async function aPost(path, body) {
      try {
        const r = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        let d = {}; try { d = await r.json(); } catch (e) {}
        return { status: r.status, ok: r.ok, d };
      } catch (e) { return { status: 0, ok: false, d: { error: 'Could not reach the server.' } }; }
    }
    function aState() {                                        // empty: the big buttons; once talking, small ones above the input
      const started = athread.children.length > 0;
      aempty.hidden = started; aguest.hidden = acctOn;
      const asked = new Set([...athread.querySelectorAll('.aqq')].map(p => p.textContent));
      const qs = QUICK.filter(q => !asked.has(q));
      achips.innerHTML = qs.map(q => '<button type="button" class="chip achip" data-q="' + aEsc(q) + '">' + aEsc(q) + '</button>').join('')
        + (aSummed ? '' : '<button type="button" class="chip achip" data-sum="1">Summary</button>');
      achips.hidden = !started || !achips.innerHTML;
    }
    function aBubble(q) {
      const item = document.createElement('div'); item.className = 'aqa';
      item.innerHTML = '<p class="aqq">' + aEsc(q) + '</p><div class="aa"><p class="aload">Thinking<span>.</span><span>.</span><span>.</span></p></div>';
      athread.appendChild(item); aState(); item.scrollIntoView({ block: 'end' });
      return item.querySelector('.aa');
    }
    function aFail(slot, status, d) {
      if (status === 401) { acctOn = false; slot.closest('.aqa').remove(); aState(); return true; }
      slot.innerHTML = '<p class="aerr">' + aEsc(d.error || 'The agent did not answer.') + '</p>'; return true;
    }
    function needWallet(run) {
      if (acctOn) { run(); return; }
      EarlyWallet.open(() => { acctOn = true; loadMe(); aState(); run(); }, 'Connect a wallet to ask the agent.');
    }
    async function aSummary() {
      if (aBusy || aSummed) return;
      aBusy = true;
      const slot = aBubble(SUMQ);
      const { status, ok, d } = await aPost('/job/' + jobId + '/agent/cards', { lang: ALANG });
      aBusy = false;
      if (!ok) { aFail(slot, status, d); return; }
      const c = d.cards || {}, card = (cls, h, body) => '<section class="acard ' + cls + '"><h4>' + h + '</h4>' + body + '</section>';
      slot.innerHTML = (c.story && c.story.length ? card('story', 'What happened', aList(c.story)) : '')
        + (c.risks && c.risks.length ? card('risk', 'What to weigh', aList(c.risks)) : '')
        + card('watch', 'Who to watch', c.watch && c.watch.length ? '<div class="awl">' + c.watch.map(aWallet).join('') + '</div>' : '<p class="muted small">No wallet here fits the method.</p>');
      aSummed = true; aState(); aLeft(d.left);
    }
    async function aAsk(q, chip) {
      q = (q || '').trim();
      if (!q || aBusy) return;
      aBusy = true;
      EarlyUI.track('agent-ask', { chip: !!chip });
      // what the agent needs to follow the talk: the last three questions with the answers as shown, and the wallets
      // put on the chart on this page, so "and this one?" means the one in front of the person
      const history = [...athread.querySelectorAll('.aqa')].slice(-3).map(it => ({
        q: ((it.querySelector('.aqq') || {}).textContent || '').trim(),
        a: [...it.querySelectorAll('.aa li, .aa .awallet, .aa .awhy')].map(x => x.textContent.trim()).join(' · ').slice(0, 600) }))
        .filter(h => h.q && h.a && h.q !== SUMQ);
      // "asked about": the wallets on the chart, five at most
      const focus = [...new Set(onChart.map(o => o.wallet))].slice(0, 5);
      const slot = aBubble(q);
      const { status, ok, d } = await aPost('/job/' + jobId + '/agent/ask', { q, lang: ALANG, chip: !!chip, history, focus });
      aBusy = false;
      if (!ok) { aFail(slot, status, d); return; }
      slot.innerHTML = '<ul class="aans' + (d.on_topic === false ? ' off' : '') + '">' + (d.answer || []).map(t => '<li>' + aText(t) + '</li>').join('') + '</ul>'
        + ((d.wallets || []).length ? '<div class="awl">' + d.wallets.map(aWallet).join('') + '</div>' : '');
      aLeft(d.left);
    }
    document.getElementById('askbtn').addEventListener('click', () => {
      EarlyUI.track('agent-open');
      if (!ASSIST_ON) { aipop.hidden = !aipop.hidden; return; }
      apanel.hidden = !apanel.hidden;
      if (!apanel.hidden) { closeCard(); aState(); }
      document.body.classList.toggle('drawer-open', !apanel.hidden);   // on a phone the page under it stays put
    });
    if (!ASSIST_ON) {
      document.getElementById('askbtn').addEventListener('mouseenter', () => { aipop.hidden = false; });
      aiwrap.addEventListener('mouseleave', () => { aipop.hidden = true; });
      on(document, 'click', e => { if (!aipop.hidden && !e.target.closest('#aiwrap')) aipop.hidden = true; });
    }
    document.getElementById('aclose').addEventListener('click', () => { apanel.hidden = true; document.body.classList.remove('drawer-open'); EarlyUI.use('agent-close'); });
    aform.addEventListener('submit', e => { e.preventDefault(); const q = aq.value.trim(); if (!q) return; needWallet(() => { aq.value = ''; aAsk(q, false); }); });
    apanel.addEventListener('click', e => {
      const w = e.target.closest('.awallet'); if (w) { cardSrc = 'agent'; toggleWallet(w.dataset.w, true); return; }
      const b = e.target.closest('.aqbtn, .achip'); if (!b) return;
      if (b.dataset.sum) needWallet(aSummary); else needWallet(() => aAsk(b.dataset.q, true));
    });

    // The background checks, asked every five seconds while they run: `fresh` and `bundle` tags, funders, first
    // transactions and who a wallet is. Each answer carries only what is new since the one before, and a tab in the
    // background waits until it is looked at again.
    const en = document.getElementById('enrich');
    let polls = 0, fails = 0, namePolls = 0, nF = 0, nA = 0, haveIds = false;   // a page left open stops asking after ten minutes
    const again = () => {
      if (++polls >= 120) return;
      later(() => { if (document.hidden) on(document, 'visibilitychange', tick, { once: true }); else tick(); }, 5000);
    };
    const refresh = () => { verdict(); findings(); if (!drawer.hidden && drawer.dataset.w) { renderIdent(drawer.dataset.w); renderWalletInfo(drawer.dataset.w); if (window.EarlyTZ) EarlyTZ.apply(); } };
    // one dropped answer (a deploy, a flaky network) is asked again; the fourth in a row ends the checks for this view
    const lost = () => { if (!alive) return; if (++fails <= 3) { again(); return; } if (en) en.hidden = true; ageDone = true; refresh(); };
    const tick = async () => {
      let d;
      try {
        const r = await fetch('/job/' + jobId + '.enrich.json?' + new URLSearchParams({ f: nF, a: nA, i: haveIds ? 1 : 0 }));
        if (!r.ok) { lost(); return; }
        d = await r.json();
      } catch (e) { lost(); return; }
      if (!alive) return;
      fails = 0;
      let changed = false, added = 0;
      if (d.identities) { changed = Object.keys(d.identities).length !== Object.keys(idents).length; idents = d.identities; haveIds = !!d.identities_done; }
      Object.assign(ages, d.ages || {}); if (d.n_ages != null) nA = d.n_ages;
      const newF = Object.keys(d.funders || {}).length;
      Object.assign(funders, d.funders || {}); if (d.n_funders != null) nF = d.n_funders;
      const svcs = d.services || [], newS = svcs.length !== services.size;   // a funder found to be an exchange unmakes its bundle
      if (newS) services = new Set(svcs);
      (d.fresh || []).forEach(w => { const o = byW.get(w); if (o && !o.tags.includes('fresh')) { o.tags.unshift('fresh'); added++; } });
      let newL = 0;                                           // InsightX names a funder: an exchange joins EXCH, an app the card
      Object.entries(d.labels || {}).forEach(([a, v]) => { if (EXCH[a] || FLAB[a]) return; newL++;
        if (v[2] === 'exchange') EXCH[a] = v[1] ? [v[0], v[1]] : [v[0], '', 1]; else FLAB[a] = [v[0], v[1], KIND_TXT[v[2]] || 'a known service']; });
      if (newL) changed = true;
      Object.entries(d.dormant || {}).forEach(([w, n]) => { DORM[w] = n; const o = byW.get(w); if (o && !o.tags.includes('dormant')) { o.tags.push('dormant'); added++; } });
      if (d.launch && !LAUNCH) {                              // the launch check (14.10): its tags join the rows once
        LAUNCH = d.launch; changed = true;
        Object.entries(d.launch.tags || {}).forEach(([w, ts]) => { const o = byW.get(w); if (o) ts.forEach(t => { if (!o.tags.includes(t)) { o.tags.push(t); added++; } }); });
      }
      if (newF || newS) {
        rebundle();
        byW.forEach((o, w) => {                               // the tag follows the recount both ways
          const has = o.tags.includes('bundle');
          if (bundle[w] && !has) { o.tags.unshift('bundle'); added++; }
          else if (!bundle[w] && has && funders[w]) { o.tags.splice(o.tags.indexOf('bundle'), 1); added++; }
        });
        let rings = 0;                                        // bundles arrive after the page: ring the wallets already on the chart
        onChart.forEach(o => { const c = bundleColor(o.wallet); if (c !== o.bundleColor) { o.bundleColor = c; rings++; } });
        if (rings) renderOnChart();
      }
      if (added || newF || changed) apply();                  // a Hide chip may catch a new tag; rows already drawn are patched in place
      // names come from their own thread and may still be missing once ages and funders are done. They are asked a
      // dozen more times, not for ten minutes: an older result may never get them, and each answer resends them all
      const names = () => { if (!d.identities_done && ++namePolls <= 12) again(); };
      if (!en || !d.total) { if (en) en.hidden = true; ageDone = true; refresh(); names(); return; }
      const busy = !d.paused && (d.done < d.total || (d.funders_done != null && d.funders_done < d.total));
      if (d.paused) { en.textContent = 'wallet age paused: this month\'s budget for it is used up'; ageDone = true; refresh(); names(); return; }
      ageDone = !busy;
      if (d.done < d.total) { en.textContent = 'wallet age ' + d.done + '/' + d.total + '…'; again(); }
      else {
        const nb = Object.keys(bundle).length;                // only the first d.total by PnL are checked: say so, or "checked" reads as every wallet
        // short in the toolbar, the whole sentence on hover (it sits beside the count now, not in a panel)
        const scope = d.total >= all.length ? 'every wallet' : 'the top ' + d.total + ' by PnL';
        en.textContent = busy ? 'funders ' + (d.funders_done || 0) + '/' + d.total + '…' : 'top ' + Math.min(d.total, all.length) + ' checked';
        en.title = 'Age and first funder checked for ' + scope + ((d.fresh || []).length ? ' · ' + d.fresh.length + ' fresh' : '') + (nb ? ' · ' + nb + ' in bundles' : '');
        if (busy) again(); else names();
      }
      refresh();
    };
    tick();
    loadCrossings();
    if (V2) {                                                   // a link from the card's Share opens with that wallet's card
      const qw = new URLSearchParams(location.search).get('w');
      if (qw && byW.has(qw) && location.pathname === '/job/' + encodeURIComponent(jobId)) { cardSrc = 'link'; later(() => toggleWallet(qw, true), 0); }
    }
    return function unmount() {
      alive = false;
      drawer.hidden = true; delete drawer.dataset.w;          // a late answer's «is this card still open» check now fails
      off.forEach(fn => { try { fn(); } catch (e) {} });
      fpop.remove(); listpop.remove();
      if (V2) { if (tabsres && rheadEl) rheadEl.remove(); if (ctw) { ctw.innerHTML = ''; ctw.hidden = true; } }   // what v2 moved out of the result
      document.body.classList.remove('drawer-open');
      ch.setWalletMarkers([]); ch.setOnMarkers(null); ch.setExit(null);
    };
  }
  window.EarlyResult = { mount };
})();
