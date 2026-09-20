/* Sign in with a Solana wallet: connect → sign a server-issued message → the server sets a cookie.
   No libraries, no transaction. Injected wallets (Phantom, Solflare, Backpack, window.solana) and
   any Wallet Standard wallet that offers solana:signMessage. */
(function () {
  const sheet = () => document.getElementById('wsheet'), list = () => document.getElementById('wlist'), st = () => document.getElementById('wstate');
  let onDone = null, busy = false;

  function b64(bytes) { let s = ''; for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]); return btoa(s); }
  async function post(url, body) {
    const r = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    let d = {}; try { d = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error(d.error || ('error ' + r.status));
    return d;
  }

  /* wallet-standard: the page announces itself and wallets register in the same tick */
  function standardWallets() {
    const out = [];
    try { window.dispatchEvent(new CustomEvent('wallet-standard:app-ready', { detail: { register: (...ws) => { ws.forEach(w => out.push(w)); return () => {}; } } })); } catch (e) {}
    return out.filter(w => w && w.features && w.features['standard:connect'] && w.features['solana:signMessage']);
  }
  function adapters() {
    const out = [], names = new Set();
    const add = a => { if (a && !names.has(a.name)) { names.add(a.name); out.push(a); } };
    standardWallets().forEach(w => add({ name: w.name, icon: w.icon, acc: null,
      async connect() { const r = await w.features['standard:connect'].connect(); this.acc = (r.accounts || [])[0]; if (!this.acc) throw new Error('No account'); return this.acc.address; },
      async sign(bytes) { const [r] = await w.features['solana:signMessage'].signMessage({ account: this.acc, message: bytes }); return r.signature; } }));
    const legacy = (name, p) => p && add({ name, icon: p.icon,
      async connect() { const r = await p.connect(); const pk = p.publicKey || (r && r.publicKey); if (!pk) throw new Error('No public key'); return pk.toString(); },
      async sign(bytes) { const r = await p.signMessage(bytes, 'utf8'); return r && r.signature ? r.signature : r; } });
    legacy('Phantom', window.phantom && window.phantom.solana);
    legacy('Solflare', window.solflare);
    legacy('Backpack', window.backpack);
    if (window.solana) legacy(window.solana.isPhantom ? 'Phantom' : 'Solana wallet', window.solana);
    return out;
  }

  function showPill(v) {
    const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    document.querySelectorAll('.acct-slot, .hero-acct').forEach(el => {
      el.innerHTML = '<a class="acct-pill" href="/me" title="' + esc(v.pubkey) + '"><i class="dot"></i><span class="mono">' + esc(v.short) + '</span></a>';
    });
  }
  const rejected = e => e && (e.code === 4001 || /reject|denied|cancel|declin/i.test(e.message || ''));
  function state(t) { const s = st(); if (s) s.textContent = t || ''; }

  async function signIn(a) {
    if (busy) return; busy = true;
    state('Waiting for your wallet…');
    try {
      const pk = await a.connect();
      const n = await post('/auth/nonce');
      const msg = n.domain + ' wants you to sign in with your Solana account:\n' + pk + '\n\n' + n.statement + '\n\nNonce: ' + n.nonce + '\nIssued At: ' + n.issued_at;
      const sig = await a.sign(new TextEncoder().encode(msg));
      const v = await post('/auth/verify', { pubkey: pk, signature: b64(sig), message: msg });
      const f = onDone; close();                       // close() drops the callback: take it first
      if (!f) { location.reload(); return; }
      showPill(v);                                       // the page stays: swap the top-bar button for the wallet pill
      f(v);
    } catch (e) {
      state(rejected(e) ? 'Signature rejected. Nothing was sent.' : ((e && e.message) || 'Something went wrong.'));
    } finally { busy = false; }
  }

  function open(cb) {
    const s = sheet(); if (!s) return;
    onDone = cb || null; state('');
    const l = list(); l.innerHTML = '';
    const as = adapters();
    if (!as.length) {
      l.innerHTML = '<p class="muted small">No wallet found. Install <a href="https://phantom.com" target="_blank" rel="noopener">Phantom</a> or <a href="https://solflare.com" target="_blank" rel="noopener">Solflare</a> and come back.</p>';
    }
    as.forEach(a => {
      const b = document.createElement('button'); b.type = 'button';
      if (a.icon && /^data:image\//.test(a.icon)) { const i = document.createElement('img'); i.src = a.icon; i.alt = ''; b.appendChild(i); }
      b.appendChild(document.createTextNode(a.name));
      b.addEventListener('click', () => signIn(a));
      l.appendChild(b);
    });
    s.hidden = false;
    const first = l.querySelector('button'); if (first) first.focus();
  }
  function close() { const s = sheet(); if (s) s.hidden = true; onDone = null; }
  async function signOut() { try { await post('/auth/logout'); } catch (e) {} location.reload(); }

  document.addEventListener('click', e => {
    if (e.target.closest('[data-wallet-signin]')) { e.preventDefault(); open(); return; }
    if (e.target.closest('[data-wallet-signout]')) { e.preventDefault(); signOut(); return; }
    if (e.target.closest('[data-wallet-close]') || (e.target.classList && e.target.classList.contains('sheet'))) close();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  window.EarlyWallet = { open, close, signIn, signOut, adapters, post };
})();
