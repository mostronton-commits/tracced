/* Seven quick clicks on the tracced wordmark: green and red candles burst out of it and fall, like a chart on a
   wild day. One of them is Wick. This file loads only when someone finds it (ui.js); no requests, nothing stored. */
window.EarlyEgg = (function () {
  const GREEN = '#34D399', MINT = '#A7F3D0', RED = '#F87171', NAVY = '#090D16', WHITE = '#F8FAFC';
  let busy = false;

  function rain(from) {
    if (busy || !from) return;
    busy = true;
    if (window.EarlyUI) { EarlyUI.use('egg', { what: 'candles' }); EarlyUI.toast('You found Wick.', 3500); }
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) { busy = false; return; }   // the toast is enough

    const W = innerWidth, H = innerHeight, dpr = Math.min(2, devicePixelRatio || 1);
    const cv = document.createElement('canvas');
    cv.className = 'eggfx'; cv.setAttribute('aria-hidden', 'true');
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    document.body.appendChild(cv);
    const g = cv.getContext('2d');
    g.scale(dpr, dpr);

    let r = from.getBoundingClientRect();                           // the word itself, not the whole line it sits on
    try { const rg = document.createRange(); rg.selectNodeContents(from); const t = rg.getBoundingClientRect(); if (t.width) r = t; } catch (e) {}
    const ox = r.left + r.width / 2, oy = r.top + r.height / 2;
    const lift = Math.sqrt(2 * 0.3 * Math.max(60, Math.min(oy - 16, 280)));   // the fountain peaks inside the window
    const n = W < 600 ? 46 : 76, ps = [];
    for (let i = 0; i < n; i++) {
      const wick = i === n - 1;                                     // Wick leaves last and falls down the middle
      ps.push({
        x: ox + (wick ? 0 : (Math.random() - 0.5) * r.width * 0.8), y: oy,
        vx: wick ? (Math.random() - 0.5) * 2 : (Math.random() - 0.5) * (W < 600 ? 8 : 12),
        vy: -(wick ? 0.85 : 0.55 + Math.random() * 0.45) * lift,
        a: wick ? 0 : (Math.random() - 0.5) * 0.5, va: (Math.random() - 0.5) * (wick ? 0.02 : 0.08),
        w: wick ? 22 : 6 + Math.random() * 5, h: wick ? 36 : 12 + Math.random() * 26,
        up: wick || Math.random() < 0.58, wick, at: i * 12,
      });
    }

    let t0 = null, last = 0;
    function frame(ts) {
      if (t0 === null) { t0 = ts; last = ts; }
      const dt = Math.min(2.5, (ts - last) / 16.67); last = ts;
      g.clearRect(0, 0, W, H);
      let alive = 0;
      for (const p of ps) {
        if (ts - t0 < p.at) { alive++; continue; }
        p.vy += 0.3 * dt; p.x += p.vx * dt; p.y += p.vy * dt; p.a += p.va * dt;
        if (p.y - p.h > H + 20) continue;
        alive++; draw(p);
      }
      if (alive && ts - t0 < 8000) requestAnimationFrame(frame);
      else { cv.remove(); busy = false; }
    }

    function draw(p) {
      g.save(); g.translate(p.x, p.y); g.rotate(p.a);
      const tail = p.h * 0.28;
      g.lineCap = 'round'; g.lineWidth = p.wick ? 2.5 : 1.5; g.strokeStyle = p.up ? MINT : RED;
      g.beginPath(); g.moveTo(0, -p.h / 2 - tail); g.lineTo(0, p.h / 2 + tail); g.stroke();
      g.fillStyle = p.up ? GREEN : RED;
      box(-p.w / 2, -p.h / 2, p.w, p.h, p.wick ? 4 : 1.5); g.fill();
      if (p.wick) face(p);
      g.restore();
    }

    function face(p) {                                             // the same face as on the rugged page
      const ex = p.w * 0.2, ey = -p.h * 0.18;
      g.fillStyle = WHITE;
      g.beginPath(); g.arc(-ex, ey, 2.8, 0, 7); g.arc(ex, ey, 2.8, 0, 7); g.fill();
      g.fillStyle = NAVY;
      g.beginPath(); g.arc(-ex - 0.8, ey + 0.5, 1.4, 0, 7); g.arc(ex - 0.8, ey + 0.5, 1.4, 0, 7); g.fill();
      g.strokeStyle = '#064E3B'; g.lineWidth = 1.5;
      g.beginPath(); g.arc(0, p.h * 0.08, 3.2, 0.15 * Math.PI, 0.85 * Math.PI); g.stroke();
    }

    function box(x, y, w, h, rad) {
      g.beginPath();
      if (g.roundRect) { g.roundRect(x, y, w, h, rad); return; }
      g.rect(x, y, w, h);
    }

    requestAnimationFrame(frame);
  }

  return { rain };
})();
