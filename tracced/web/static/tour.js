/* A first-visit tour of the token page (owner, 14.10: four steps, Get wallets on the chart as in variant B).
   Each step waits for its own part of the page and shows when it appears, so the tour follows what the person does:
   1 · the chart, to mark the zone; 2 · the bar on the chart with Get wallets; 3 · the result's table; 4 · a wallet's
   card. Once per browser; Skip ends it. The page stays usable underneath: the dim does not catch clicks. */
(function () {
  const root = document.getElementById('token'); if (!root) return;
  const KEY = 'early:tour', DEMO = root.dataset.demo === '1';
  const read = () => { try { return localStorage.getItem(KEY) || '0'; } catch (e) { return 'skip'; } };
  const write = v => { try { localStorage.setItem(KEY, String(v)); } catch (e) {} };
  if (read() === 'skip' || +read() >= 4) return;

  const shown = el => !!el && !el.hidden && el.offsetParent !== null && el.getBoundingClientRect().height > 0;
  const STEPS = [
    { el: () => document.getElementById('chart'), when: () => !DEMO && !shown(document.getElementById('pick')),
      h: 'Mark the zone before the pump', p: 'Click the chart where the buying starts, then where the price takes off. That window is what tracced reads.',
      done: () => shown(document.getElementById('pick')) },
    { el: () => document.getElementById('pick'), when: () => shown(document.getElementById('pick')),
      h: 'Get wallets', p: DEMO ? 'Press it: the recorded analysis of this pump replays.'
        : "The button appears right on the chart. tracced reads every trade in the zone, then each wallet's whole history on this token.",
      done: () => !!document.getElementById('facts') },
    { el: () => document.getElementById('facts'), when: () => shown(document.getElementById('facts')),
      h: 'Every wallet that bought in the zone', p: 'What each one bought, sold and earned. Sort by ROI, filter by size, hide the bots. Click a wallet to open its card.',
      done: () => shown(document.getElementById('drawer')) },
    { el: () => document.getElementById('drawer'), when: () => shown(document.getElementById('drawer')),
      h: 'Read the wallet, then follow it', p: 'Its trades on the chart, its last 30 days on every token. Star it, and its next buys and sells come to your Telegram.',
      done: () => false, last: true },
  ];

  let step = +read() || 0, open = false, raf = 0;
  if (DEMO && step === 0) step = 1;                       // the demo's zones are marked already
  const spot = document.createElement('div'); spot.className = 'tour-spot'; spot.hidden = true;
  const tip = document.createElement('div'); tip.className = 'tour-tip'; tip.hidden = true; tip.setAttribute('role', 'dialog');
  tip.setAttribute('aria-live', 'polite');
  document.body.append(spot, tip);

  function place() {
    raf = 0; if (!open) return;
    const t = STEPS[step].el(); if (!shown(t)) { hide(); return; }
    const r = t.getBoundingClientRect(), pad = 6, vw = innerWidth, vh = innerHeight;
    // a target taller than the screen (the table, the card) is outlined only where it is in view
    const top = Math.max(r.top, 8), bottom = Math.min(r.bottom, vh - 8);
    Object.assign(spot.style, { left: (r.left - pad) + 'px', top: (top - pad) + 'px', width: (r.width + 2 * pad) + 'px', height: Math.max(0, bottom - top + 2 * pad) + 'px' });
    if (vw <= 640) { tip.classList.add('tour-sheet'); tip.style.left = tip.style.top = ''; return; }
    tip.classList.remove('tour-sheet');
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let x = Math.min(Math.max(12, r.left + r.width / 2 - tw / 2), vw - tw - 12);
    let y = bottom + 14;                                  // under the target; above it, or inside its top, when there is no room
    if (y + th > vh - 12) y = r.top - th - 14;
    if (y < 12) y = Math.min(vh - th - 12, top + 16);
    if (STEPS[step].el() === document.getElementById('drawer')) x = Math.max(12, r.left - tw - 16);   // beside the card, not over it
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  const ask = () => { if (!raf) raf = requestAnimationFrame(place); };

  function render() {
    const s = STEPS[step];
    tip.innerHTML = '<div class="tour-n">STEP ' + (step + 1) + ' OF 4</div><h3>' + s.h + '</h3><p>' + s.p + '</p><div class="tour-row"><span class="tour-dots">'
      + STEPS.map((_, i) => '<i class="' + (i === step ? 'on' : '') + '"></i>').join('') + '</span><span>'
      + (s.last ? '' : '<button type="button" class="ghost tour-skip">Skip</button>')
      + '<button type="button" class="primary tour-next">' + (s.last ? 'Got it' : 'Next') + '</button></span></div>';
  }
  function show() { open = true; render(); spot.hidden = tip.hidden = false; place(); }
  function hide() { open = false; spot.hidden = tip.hidden = true; }
  function next() { hide(); step += 1; write(step); }

  tip.addEventListener('click', e => {
    if (e.target.closest('.tour-skip')) { hide(); write('skip'); stop(); return; }
    if (e.target.closest('.tour-next')) { next(); if (step >= 4) stop(); }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && open) next(); });
  addEventListener('scroll', ask, { passive: true }); addEventListener('resize', ask);

  // the page changes on its own (a range marked, a run done, a card opened): look twice a second
  const timer = setInterval(() => {
    if (step >= 4) { stop(); return; }
    const s = STEPS[step];
    if (open) { if (s.done()) { next(); } else ask(); return; }
    if (s.when()) show();
  }, 500);
  function stop() { clearInterval(timer); hide(); }
})();
