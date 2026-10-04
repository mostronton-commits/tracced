/* Sign in with a Solana wallet: connect → sign a server-issued message → the server sets a cookie.
   No libraries, no transaction. Phantom, Backpack and Solflare (owner, 02.10): through Wallet Standard when the wallet
   registers itself, or its injected provider; any other wallet is not offered. On a phone without the wallet in the
   browser, its row opens this page inside that wallet's app, where the wallet is. */
(function () {
  const sheet = () => document.getElementById('wsheet'), list = () => document.getElementById('wlist'), st = () => document.getElementById('wstate');
  let onDone = null, busy = false, opener = null;

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
  /* these three only: whatever else registers itself (MetaMask, Rabby, …) is not offered. browse: the wallet's own link
     that opens a page in its in-app browser (Phantom, Backpack and Solflare docs, "browse" deeplink) */
  const here = () => encodeURIComponent(location.href) + '?ref=' + encodeURIComponent(location.origin);
  const KNOWN = [
    { name: 'Phantom', url: 'https://phantom.com/download', browse: () => 'https://phantom.app/ul/browse/' + here(), display: 'utf8',
      legacy: () => (window.phantom && window.phantom.solana) || (window.solana && window.solana.isPhantom ? window.solana : null) },
    { name: 'Backpack', url: 'https://backpack.app/downloads', browse: () => 'https://backpack.app/ul/v1/browse/' + here(), display: null,
      legacy: () => (window.backpack && window.backpack.isBackpack ? window.backpack : null) },
    { name: 'Solflare', url: 'https://solflare.com/download', browse: () => 'https://solflare.com/ul/v1/browse/' + here(), display: 'utf8',
      legacy: () => (window.solflare && window.solflare.isSolflare ? window.solflare : null) },
  ];
  const onPhone = () => /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) || (matchMedia('(pointer: coarse)').matches && innerWidth < 900);
  function adapters() {
    const std = standardWallets();
    const byName = n => std.find(w => String(w.name || '').toLowerCase().startsWith(n.toLowerCase()));
    return KNOWN.map(k => {
      const w = byName(k.name);
      if (w) return { name: k.name, url: k.url, browse: k.browse, icon: w.icon, acc: null,
        async connect() { const r = await w.features['standard:connect'].connect(); this.acc = (r.accounts || [])[0]; if (!this.acc) throw new Error('No account'); return this.acc.address; },
        async sign(bytes) { const [r] = await w.features['solana:signMessage'].signMessage({ account: this.acc, message: bytes }); return r.signature; } };
      const p = k.legacy && k.legacy();
      if (p) return { name: k.name, url: k.url, browse: k.browse, icon: p.icon,
        async connect() { const r = await p.connect(); const pk = p.publicKey || (r && r.publicKey); if (!pk) throw new Error('No public key'); return pk.toString(); },
        // Phantom and Solflare take the display encoding second; Backpack takes a public key there, so it gets nothing
        async sign(bytes) { const r = await (k.display ? p.signMessage(bytes, k.display) : p.signMessage(bytes)); return r && r.signature ? r.signature : r; } };
      return { name: k.name, url: k.url, browse: k.browse, missing: true };
    });
  }

  function showPill(v) {
    const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    document.querySelectorAll('.acct-slot, .hero-acct').forEach(el => {   // the same menu a server-rendered page shows
      el.innerHTML = '<nav class="toplinks" aria-label="What you keep"><a href="/me">Watchlist</a></nav>'
        + '<div class="menu acct"><button type="button" class="acct-pill" data-menu title="' + esc(v.pubkey) + '"><i class="dot"></i><span class="mono">' + esc(v.short) + '</span></button>'
        + '<div class="menu-panel r" hidden><a href="/me#list">Watchlist</a><a href="/me#analyses">My analyses</a><button type="button" data-wallet-signout>Sign out</button></div></div>';
    });
    if (window.EarlyUI && EarlyUI.menus) EarlyUI.menus();
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
      const v = await post('/auth/verify', { pubkey: pk, signature: b64(sig), message: msg, wallet: a.name });
      document.documentElement.dataset.acct = '1';     // the page stays: its clicks now go to the owner's log too
      if (window.EarlyUI) EarlyUI.track('connect-done', { app: a.name });   // which wallet app, never the address
      const f = onDone; close();                       // close() drops the callback: take it first
      if (!f) {                                          // no callback: a page may leave a form to send once signed in (the 401 card), else reload
        const after = document.querySelector('form[data-wallet-after]');
        if (after) after.submit(); else location.reload();
        return;
      }
      showPill(v);                                       // the page stays: swap the top-bar button for the wallet pill
      f(v);
    } catch (e) {
      // a failed sign-in is invisible to the server (it breaks in the wallet), so it goes to the analytics: which kind, never the address
      const why = rejected(e) ? 'rejected' : /format/i.test((e && e.message) || '') ? 'format' : 'error';
      if (window.EarlyUI) EarlyUI.track('connect-fail', { app: a.name, why });
      state(rejected(e) ? 'Signature rejected. Nothing was sent.' : ((e && e.message) || 'Something went wrong.'));
    } finally { busy = false; }
  }

  function open(cb, note) {
    const s = sheet(); if (!s) return;
    if (window.EarlyUI) EarlyUI.track('connect-open');
    onDone = cb || null; state(); opener = document.activeElement;
    const wn = document.getElementById('wnote'); if (wn) { wn.textContent = note || ''; wn.hidden = !note; }   // why we ask, in context
    const l = list(); l.innerHTML = '';
    const as = adapters();
    // the wallets this browser has come first; the rest below them, to open this page in their app or to install
    as.filter(a => !a.missing).concat(as.filter(a => a.missing)).forEach(a => {
      if (a.missing) {                                   // not in this browser: on a phone open the page in the app, else install
        const phone = onPhone(), x = document.createElement('a'); x.className = 'button winstall'; x.rel = 'noopener';
        x.href = phone ? a.browse() : a.url; if (!phone) x.target = '_blank';
        x.innerHTML = '<span>' + a.name + '</span><small>' + (phone ? 'Open in the app ↗' : 'Install ↗') + '</small>'; l.appendChild(x); return;
      }
      const b = document.createElement('button'); b.type = 'button';
      if (a.icon && /^data:image\//.test(a.icon)) { const i = document.createElement('img'); i.src = a.icon; i.alt = ''; b.appendChild(i); }
      b.appendChild(document.createTextNode(a.name));
      b.addEventListener('click', () => signIn(a));
      l.appendChild(b);
    });
    if (!as.some(a => !a.missing)) state(onPhone() ? 'On a phone, tracced connects inside your wallet app: pick it below.'
      : 'No Phantom, Backpack or Solflare in this browser. Install one, then reload this page.');
    s.hidden = false;
    const first = l.querySelector('button, a'); if (first) first.focus();
  }
  function close() { const s = sheet(); if (s) s.hidden = true; onDone = null; if (opener && opener.focus && document.contains(opener)) { try { opener.focus(); } catch (e) {} } opener = null; }
  async function signOut() { if (window.EarlyUI) EarlyUI.flush(); try { await post('/auth/logout'); } catch (e) {} location.reload(); }

  document.addEventListener('click', e => {
    const t = e.target.closest('[data-wallet-signin]');
    if (t) { e.preventDefault(); open(null, t.dataset.walletNote); return; }   // data-wallet-note: why this page asks
    if (e.target.closest('[data-wallet-signout]')) { e.preventDefault(); signOut(); return; }
    if (e.target.closest('[data-wallet-close]') || (e.target.classList && e.target.classList.contains('sheet'))) close();
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  window.EarlyWallet = { open, close, signIn, signOut, adapters, post };
})();
