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
  window.EarlyUI = { countUp, fmtShort, FMT, toast, menus };
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
/* copy buttons: [data-copy="text"] */
document.addEventListener('click', e => {
  const b = e.target.closest('[data-copy]'); if (!b || !navigator.clipboard) return;
  navigator.clipboard.writeText(b.dataset.copy).then(() => { const o = b.textContent; b.textContent = '✓'; setTimeout(() => { b.textContent = o; }, 1200); });
});
