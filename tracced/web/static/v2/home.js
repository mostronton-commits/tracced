/* design v2 · home, the small motion the owner asked for (06.11): a card leans towards the pointer and catches its light,
   what lies below the fold rises in once, the month's total counts up. All of it off with reduced motion. */
(function () {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const cards = Array.from(document.querySelectorAll('.hm-card'));
  /* the lean: at most 1.2° each way, only where there is a real pointer */
  if (matchMedia('(hover: hover) and (pointer: fine)').matches) {
    const MAX = 1.2;
    cards.forEach(c => {
      let raf = 0, last = null;
      const paint = () => {
        raf = 0; if (!last) return;
        const r = c.getBoundingClientRect(), x = (last.clientX - r.left) / r.width, y = (last.clientY - r.top) / r.height;
        c.style.setProperty('--mx', (x * 100).toFixed(1) + '%'); c.style.setProperty('--my', (y * 100).toFixed(1) + '%');
        c.style.setProperty('--ry', ((x - .5) * 2 * MAX).toFixed(2) + 'deg'); c.style.setProperty('--rx', ((.5 - y) * 2 * MAX).toFixed(2) + 'deg');
      };
      c.addEventListener('pointerenter', () => c.classList.add('hm-lean'));
      c.addEventListener('pointermove', e => { last = e; if (!raf) raf = requestAnimationFrame(paint); });
      c.addEventListener('pointerleave', () => { last = null; c.classList.remove('hm-lean'); c.style.removeProperty('--rx'); c.style.removeProperty('--ry'); });
    });
  }
  /* the month's total: counts up the first time it is seen, and lands on the text the server wrote */
  const money = v => { const a = Math.abs(v); return (v < 0 ? '−$' : '+$') + (a >= 1e6 ? (a / 1e6).toFixed(2) + 'M' : a >= 1e3 ? (a / 1e3).toFixed(0) + 'K' : a.toFixed(0)); };
  const countUp = el => {
    const end = el.textContent, target = +el.dataset.roll; if (!target) return;
    const t0 = performance.now(), DUR = 900;
    (function step(now) {
      const p = Math.min(1, (now - t0) / DUR), e = 1 - Math.pow(1 - p, 3);
      if (p < 1) { el.textContent = money(target * e); requestAnimationFrame(step); } else el.textContent = end;
    })(t0);
  };
  /* what lies below the fold rises in once, one after another; what is already in view stays as it is */
  const seen = c => c.querySelectorAll('[data-roll]').forEach(countUp);
  if (!window.IntersectionObserver) { cards.forEach(seen); return; }
  const io = new IntersectionObserver(es => es.forEach(x => {
    if (!x.isIntersecting) return;
    io.unobserve(x.target); x.target.classList.add('in'); seen(x.target);
  }), { threshold: 0.12 });
  cards.forEach((c, i) => {
    if (c.getBoundingClientRect().top > innerHeight) { c.classList.add('hm-rev'); c.style.setProperty('--d', (i % 2) * 90 + 'ms'); }
    io.observe(c);
  });
})();
