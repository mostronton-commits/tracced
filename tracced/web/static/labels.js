/* The owner's labels on user wallets in /admin (30.09: who is a friend, which are my own, which are testers). Each
   .alabels[data-w][data-labels] becomes chips (each × drops one) and a + that opens a field with suggestions; Enter keeps
   the word. Labels live in a file on the server and are seen only in /admin. .alfilter buttons show only the rows
   carrying a label. */
(function () {
  const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const PLUS = '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M6 1.8v8.4M1.8 6h8.4"/></svg>';
  function draw(el) {
    const ls = JSON.parse(el.dataset.labels || '[]');
    el.innerHTML = ls.map(l => '<span class="tag mine"><span>' + esc(l) + '</span><button type="button" class="tagx" data-tag="' + esc(l) + '" title="Remove this label" aria-label="Remove the label ' + esc(l) + '">×</button></span>').join('')
      + '<input type="text" class="tagin" maxlength="24" list="alabel-list" aria-label="New label" hidden>'
      + (ls.length < 6 ? '<button type="button" class="tagadd" title="Label this wallet: me, friend, tester…" aria-label="Add a label">' + PLUS + '</button>' : '');
  }
  async function save(el, ls) {
    try {
      const d = await EarlyWallet.post('/admin/labels', { wallet: el.dataset.w, labels: ls });
      el.dataset.labels = JSON.stringify(d.labels || []);
      const tr = el.closest('tr'); if (tr) tr.dataset.labels = JSON.stringify(d.labels || []);
    } catch (e) { if (window.EarlyUI) EarlyUI.toast(e.message); }
    draw(el);
  }
  function mount(el) {
    draw(el);
    el.addEventListener('click', e => {
      const x = e.target.closest('.tagx');
      if (x) { save(el, JSON.parse(el.dataset.labels || '[]').filter(l => l !== x.dataset.tag)); return; }
      if (e.target.closest('.tagadd')) { const inp = el.querySelector('.tagin'); inp.hidden = false; e.target.closest('.tagadd').hidden = true; inp.focus(); }
    });
    el.addEventListener('keydown', e => {
      const inp = e.target.closest('.tagin'); if (!inp) return;
      if (e.key === 'Escape') { draw(el); return; }
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const v = inp.value.trim(); if (!v) { draw(el); return; }
      save(el, JSON.parse(el.dataset.labels || '[]').concat([v]));
    });
    el.addEventListener('focusout', e => { const inp = e.target.closest('.tagin'); if (inp && !inp.value.trim()) setTimeout(() => { if (!el.contains(document.activeElement)) draw(el); }, 0); });
  }
  document.querySelectorAll('.alabels[data-w]').forEach(mount);
  // the filter above the wallets table: one label at a time, «All» shows everyone
  const bar = document.querySelector('.alfilter');
  if (bar) bar.addEventListener('click', e => {
    const b = e.target.closest('button[data-l]'); if (!b) return;
    const l = b.dataset.l;
    bar.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('tr[data-labels]').forEach(tr => { let ls = []; try { ls = JSON.parse(tr.dataset.labels || '[]'); } catch (x) {} tr.hidden = !!l && !ls.includes(l); });
  });
})();
