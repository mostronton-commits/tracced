/* Small UI helpers: count-up numbers and dropdown menus. No dependencies. */
(function () {
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function fmtShort(v) {
    if (v == null || isNaN(v)) return '—';
    const sign = v < 0 ? '-' : ''; v = Math.abs(v);
    for (const [lim, suf] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) {
      if (v >= lim * 0.9995) { const x = Math.max(v / lim, 1); let s = x < 10 ? x.toFixed(1) : x.toFixed(0); if (s.includes('.')) s = s.replace(/\.?0+$/, ''); return sign + s + suf; }
    }
    return sign + v.toFixed(0);
  }
  const FMT = {
    int: v => Math.round(v).toLocaleString('en-US'),
    usd: v => (v < 0 ? '-$' : '$') + fmtShort(Math.abs(v)),
    short: v => fmtShort(v),
    mult: v => (v ? (v >= 10 ? v.toFixed(0) : v.toFixed(1)) + '×' : '—'),
  };

  /* Count from 0 to data-count; bigger numbers take longer (log scale), smaller ones stop earlier. */
  function countUp(el) {
    /* A money tile counts up in whatever unit the footer switch is set to, so the animation
       does not land on the dollar figure while the page is showing SOL. */
    const inSol = el.classList.contains('amt') && window.EarlyCur && EarlyCur.get() === 'sol' && el.dataset.sol !== undefined;
    const target = +(inSol ? el.dataset.sol : el.dataset.count), fmt = inSol ? EarlyCur.sol : (FMT[el.dataset.fmt || 'int'] || FMT.int);
    if (isNaN(target)) return;
    if (reduced || target === 0) { el.textContent = fmt(target); return; }
    const dur = Math.min(1400, Math.max(300, 300 + 250 * Math.log10(Math.abs(target) + 1)));
    const t0 = performance.now();
    (function step(now) {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = fmt(target * e);
      if (p < 1) requestAnimationFrame(step); else el.textContent = fmt(target);
    })(t0);
  }

  /* The token's own events for the chart's badges: what each one means and when, in its tooltip. */
  const DEX = '<img src="/static/brands/dexscreener.png" alt="">';
  function marks(d) {
    const out = [];
    const when = ms => (window.EarlyTZ ? ' · ' + EarlyTZ.fmt(ms, false) : '');
    if (d && d.migration && d.migration.ms) out.push({ ms: d.migration.ms, kind: 'mig', badge: 'M',
      label: 'Migrated to ' + (d.migration.market || 'a DEX'),
      title: 'Migration: trading moved from ' + (d.migration.from || 'the launchpad') + ' to ' + (d.migration.market || 'a DEX') + when(d.migration.ms) });
    ((d && d.paid) || []).forEach(p => out.push({ ms: p.ms, kind: 'paid', html: DEX, label: 'DexScreener ' + (p.kind || 'profile') + ' paid',
      title: 'DexScreener ' + (p.kind || 'profile') + ' paid' + when(p.ms) + ' (anyone can pay, not only the team)' }));
    return out;
  }
  /* <div class="menu"><button data-menu>…</button><div class="menu-panel" hidden>…</div></div> */
  function menus() {
    document.querySelectorAll('[data-menu]').forEach(btn => {
      const panel = btn.parentElement.querySelector('.menu-panel'); if (!panel || btn.dataset.bound) return;
      btn.dataset.bound = '1';                                   // safe to call again for menus added later (in-page sign-in)
      btn.addEventListener('click', e => { e.stopPropagation(); const open = !panel.hidden; document.querySelectorAll('.menu-panel').forEach(p => p.hidden = true); panel.hidden = open; });
      panel.addEventListener('click', () => { panel.hidden = true; });
    });
    document.addEventListener('click', () => document.querySelectorAll('.menu-panel').forEach(p => p.hidden = true));
  }

  document.addEventListener('DOMContentLoaded', () => { document.querySelectorAll('[data-count]').forEach(countUp); menus(); });
  /* one toast at the bottom; html is ours (server messages and our own links), never user text */
  function toast(html, ms) {
    let t = document.querySelector('.toast'); if (!t) { t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
    t.innerHTML = html; t.hidden = false; clearTimeout(t._h); t._h = setTimeout(() => { t.hidden = true; }, ms || 4000);
  }
  /* The owner's own log, only for a connected wallet (docs: Your account → What we record): a named click and a short
     setting, never an address or anything typed. Queued and sent in one request every 15 s, at 20 clicks and when the
     page hides; the server keeps a line only for a wallet that is signed in. */
  const Q = [], seen = {}, T0 = Date.now();
  let timer = null;
  const signedIn = () => document.documentElement.dataset.acct === '1';
  function flush() {
    clearTimeout(timer); timer = null;
    while (Q.length) {
      const body = JSON.stringify({ e: Q.splice(0, 30) });
      try { if (navigator.sendBeacon && navigator.sendBeacon('/me/usage', body)) continue; } catch (e) {}   // a string goes as text/plain
      try { fetch('/me/usage', { method: 'POST', body, credentials: 'same-origin', keepalive: true }).catch(() => {}); } catch (e) {}
    }
  }
  /* merge (ms): a burst of the same step keeps only its last setting, e.g. ticking rows one by one */
  function use(name, props, merge) {
    if (!signedIn()) return;
    const now = Date.now(), key = name + JSON.stringify(props || {}), tail = Q[Q.length - 1];
    if (seen[key] && now - seen[key] < 1500) return;                         // a double click is one click
    seen[key] = now;
    if (merge && tail && tail[0] === name && now - tail[2] < merge) { tail[1] = props || {}; tail[2] = now; return; }
    Q.push([name, props || {}, now]);
    if (Q.length >= 20) flush(); else if (!timer) timer = setTimeout(flush, 15000);
  }
  addEventListener('pagehide', () => { use('leave', { secs: Math.round((Date.now() - T0) / 1000) }); flush(); });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(); });

  /* A product step for Umami, the privacy-friendly analytics on the live site: what people do, never who they are
     (no wallet addresses, at most one small property). Nothing happens where Umami is not loaded or is blocked.
     A few steps also go to the owner's own log above (only for a connected wallet). */
  const FWD = { 'show-more': 1, 'limit-window': 1, 'find-pump': 1, 'agent-open': 1 };
  function track(name, data) {
    if (FWD[name]) use(name, data);
    toUmami(name, data);
  }
  function toUmami(name, data) {
    // an inline script runs while the page is still parsed, before the deferred Umami script: wait for it
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', () => toUmami(name, data), { once: true }); return; }
    try { if (window.umami && typeof umami.track === 'function') umami.track(name, data); } catch (e) {}
  }
  window.EarlyUI = { countUp, fmtShort, FMT, toast, menus, marks, track, use, flush };
})();

/* home: the address field "types" a made-up base58 address until the user touches it */
document.addEventListener('DOMContentLoaded', () => {
  const el = document.querySelector('[data-type-address]'); if (!el) return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const ALPHA = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  const fake = () => { let s = ''; for (let i = 0; i < 40; i++) s += ALPHA[Math.floor(Math.random() * ALPHA.length)]; return s + 'pump'; };
  let addr = fake(), i = 0, dir = 1;
  const tick = () => {
    if (document.activeElement === el || el.value) { el.placeholder = 'Paste a token address'; setTimeout(tick, 1500); return; }
    i += dir; el.placeholder = addr.slice(0, i) + (i < addr.length ? '▍' : '');
    let d = 26;
    if (dir === 1 && i >= addr.length) { dir = -1; d = 2200; }
    else if (dir === -1 && i <= 0) { dir = 1; addr = fake(); d = 600; }
    else if (dir === -1) d = 10;
    setTimeout(tick, d);
  };
  setTimeout(tick, 600);
});
/* copy buttons: [data-copy="text"]; the button may hold an icon, so its markup comes back, not only its text */
document.addEventListener('click', e => {
  const b = e.target.closest('[data-copy]'); if (!b || !b.dataset.copy || !navigator.clipboard) return;
  e.stopPropagation();
  EarlyUI.use('copy', { what: b.closest('#drawer') ? 'card' : b.closest('tr') ? 'row' : 'page' });   // where, never what
  navigator.clipboard.writeText(b.dataset.copy).then(() => {
    if (!b.dataset.was) b.dataset.was = b.innerHTML;
    b.textContent = '✓'; clearTimeout(b._h); b._h = setTimeout(() => { b.innerHTML = b.dataset.was; delete b.dataset.was; }, 1200);
  });
});

/* a link out of tracced (Solscan, X, DexScreener): for the owner's log, which site, never the address in it */
document.addEventListener('click', e => {
  const a = e.target.closest('a[target=_blank]'); if (!a) return;
  let h = ''; try { h = new URL(a.href).hostname.replace(/^www\./, ''); } catch (x) {}
  EarlyUI.use('ext', { to: /solscan/.test(h) ? 'solscan' : (h === 'x.com' || h === 'twitter.com') ? 'x' : /dexscreener/.test(h) ? 'dexscreener' : /github/.test(h) ? 'github' : 'other' });
});

/* Markers that say what kind of wallet a row is, the way terminals do: a small picture per category, the rule or
   the source in the tooltip, the words in the card and in the filter legend. Our tags are rules computed from the
   chain; KOL, the X account and the trading platform are Solana Tracker's identification of the wallet. */
window.EarlyTags = (function () {
  const S = d => '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + d + '</svg>';
  const ICON = {
    dev: S('<path d="M4.6 9.6C2.9 9.3 1.8 8 2.1 6.5c.3-1.4 1.7-2.3 3.1-2A3.3 3.3 0 0 1 8 2.6a3.3 3.3 0 0 1 2.8 1.9c1.4-.3 2.8.6 3.1 2 .3 1.5-.8 2.8-2.5 3.1V13.4H4.6z"/><path d="M4.6 11.2h6.8"/>'),
    sniper: S('<circle cx="8" cy="8" r="5"/><path d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3"/><circle cx="8" cy="8" r=".6" fill="currentColor"/>'),
    fresh: S('<path d="M8 14V8.2"/><path d="M8 9.2C8 6.4 6.2 4.8 3 4.8c0 3 1.9 4.4 5 4.4z"/><path d="M8 8.2c0-2.6 1.7-4.2 4.8-4.2 0 2.9-1.8 4.2-4.8 4.2z"/>'),
    bundle: S('<path d="M2.5 5 8 2.4 13.5 5v6.1L8 13.6 2.5 11.1z"/><path d="M2.5 5 8 7.6 13.5 5M8 7.6v6"/>'),
    'bot-like': S('<rect x="3" y="5.5" width="10" height="7.5" rx="2"/><path d="M8 5.5V3.4"/><circle cx="8" cy="2.6" r=".8"/><circle cx="6" cy="9.2" r=".7" fill="currentColor"/><circle cx="10" cy="9.2" r=".7" fill="currentColor"/>'),
    'pre-range': S('<path d="M2.9 8.6A5.2 5.2 0 1 0 4.4 4.3"/><path d="M2.6 2.4v2.9h2.9"/><path d="M8 5.4V8l1.9 1.2"/>'),
    're-bought': S('<path d="M3 7.4a4.6 4.6 0 0 1 8.2-2.6M13 8.6a4.6 4.6 0 0 1-8.2 2.6"/><path d="M11.6 1.9v2.9H8.7M4.4 14.1v-2.9h2.9"/>'),
    'transfer-in': S('<path d="M8 2v6.6M5.4 6 8 8.6 10.6 6"/><path d="M2.4 10.2h3.1l.9 1.6h3.2l.9-1.6h3.1V13.6H2.4z"/>'),
    'no-exits': S('<circle cx="8" cy="8" r="5.6" stroke-dasharray="2 1.7"/><path d="M6.5 6.6a1.6 1.6 0 1 1 2.3 1.4c-.5.3-.8.6-.8 1.3"/><circle cx="8" cy="11.2" r=".55" fill="currentColor"/>'),
    'seen-before': '<svg class="lnk" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2" aria-hidden="true"><g transform="rotate(-45 12 12)"><rect x="1.2" y="7.4" width="12.4" height="9.2" rx="4.6"/><rect x="10.4" y="7.4" width="12.4" height="9.2" rx="4.6"/></g></svg>',
    kol: '<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 1.6l1.95 3.95 4.35.63-3.15 3.07.74 4.33L8 11.53l-3.89 2.05.74-4.33L1.7 6.18l4.35-.63z"/></svg>',
    x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>',
    exchange: S('<path d="M2 6.4 8 3l6 3.4M3.6 7.2v4.8M6.5 7.2v4.8M9.5 7.2v4.8M12.4 7.2v4.8M2 13.2h12"/>'),
    hacker: S('<path d="M8 2.4a4.6 4.6 0 0 0-4.6 4.6c0 1.7.9 2.9 2.1 3.5v2.3h5v-2.3c1.2-.6 2.1-1.8 2.1-3.5A4.6 4.6 0 0 0 8 2.4z"/><circle cx="6.2" cy="7.2" r=".9" fill="currentColor"/><circle cx="9.8" cy="7.2" r=".9" fill="currentColor"/><path d="M7 12.8v-1.3M9 12.8v-1.3"/>'),
  };
  // trading platforms Solana Tracker names, and the file of each one's own icon in /static/brands
  const BRANDS = { axiom: ['axiom', 'Axiom'], 'axiom-flash': ['axiom', 'Axiom'], gmgn: ['gmgn', 'GMGN'], fomo: ['fomo', 'Fomo'],
    'pumpfun-app': ['pumpfun', 'the pump.fun app'], pumpfun: ['pumpfun', 'the pump.fun app'], terminal: ['terminal', 'Terminal (Padre)'],
    padre: ['terminal', 'Terminal (Padre)'], photon: ['photon', 'Photon'], bloom: ['bloom', 'Bloom'], bullx: ['bullx', 'BullX'] };
  const ROLES = { exchange: 'An exchange wallet', hacker: 'A known exploit or scam wallet', bot: 'A known bot',
    potential_bot: 'Likely a bot or arbitrage wallet', arbitrage: 'An arbitrage wallet' };
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const handle = idn => String((idn && idn.twitter) || '').replace(/^@/, '').replace(/[^A-Za-z0-9_]/g, '');
  const isKol = idn => !!idn && (idn.type === 'kol' || (idn.tags || []).includes('kol'));
  const platforms = idn => [...new Set([idn.type].concat(idn.tags || [], idn.platforms || []).filter(p => BRANDS[p]).map(p => BRANDS[p][0]))];

  /* a tag of ours drawn as its picture; `text` also writes the word (card, legend) */
  function chip(tag, title, opts) {
    opts = opts || {};
    const base = tag.replace(/ ×\d+$/, ''), n = (tag.match(/×(\d+)$/) || [])[1];
    const icon = ICON[base];
    if (!icon) return '<span class="tag t-' + esc(base) + '" title="' + esc(title || base) + '">' + esc(base) + '</span>';
    return '<span class="tag ico t-' + esc(base) + (opts.text ? ' txt' : '') + '" data-tag="' + esc(base) + '" title="' + esc(title || base)
      + '" aria-label="' + esc(base) + '">' + icon + (opts.text ? '<b>' + esc(base) + '</b>' : '') + (n ? '<small>×' + n + '</small>' : '') + '</span>';
  }
  /* turn a server-rendered <span class="tag" data-tag> into its picture, keeping the definition in the tooltip */
  function iconify(el) {
    const t = el.dataset.tag; if (!t || !ICON[t] || el.classList.contains('ico')) return;
    const n = el.dataset.n;
    el.classList.add('ico'); el.setAttribute('aria-label', t);
    el.innerHTML = ICON[t] + (n ? '<small>×' + esc(n) + '</small>' : '');
  }
  /* The name to show. A known trader goes by the name traders use; anyone else by the handle the apps show: Fomo,
     Axiom and Solscan call such a wallet by its X handle, while the display name differs from one app to the next. */
  const displayName = idn => !idn ? '' : (isKol(idn) ? (idn.name || handle(idn)) : (handle(idn) || idn.name || ''));
  /* who the wallet is, as pictures: KOL star, X account, the platforms it trades through, known roles */
  function idMarks(idn, opts) {
    if (!idn) return '';
    opts = opts || {};
    const out = [], h = handle(idn), who = displayName(idn) ? '«' + esc(displayName(idn)) + '»' : '';
    if (isKol(idn)) out.push('<span class="idm kol" title="A known trader (KOL)' + (idn.name ? ': ' + esc(idn.name) : '') + '">' + ICON.kol + '</span>');
    if (h) out.push('<a class="idm xacc" href="https://x.com/' + h + '" target="_blank" rel="noopener" title="@' + h + ' on X">' + ICON.x + '</a>');
    platforms(idn).forEach(f => {
      const name = Object.values(BRANDS).find(b => b[0] === f)[1];
      out.push('<span class="idm brand" title="Trades through ' + esc(name) + (who && !isKol(idn) ? ' as ' + who : '') + '"><img src="/static/brands/' + f + '.png" alt="' + esc(name) + '"></span>');
    });
    [...new Set([idn.type].concat(idn.tags || []))].filter(r => ROLES[r]).forEach(r => {
      const icon = r === 'exchange' ? ICON.exchange : r === 'hacker' ? ICON.hacker : ICON['bot-like'];
      out.push('<span class="idm role r-' + r + '" title="' + ROLES[r] + '">' + icon + '</span>');
    });
    return out.join('');
  }
  return { ICON, BRANDS, chip, iconify, idMarks, isKol, handle, platforms, displayName, esc };
})();
