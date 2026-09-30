"""Сповіщення в Telegram: купівлі й продажі гаманців зі списків людини — без переказів, вхідних SOL і дрібниць.

Тут лише чиста логіка: розбір транзакції, одноразові коди прив'язки Telegram, хто на який гаманець підписаний і текст
повідомлення. Мережа (потік транзакцій, бот) — у app.py.

Принцип розбору той самий, що й у KOLS-радарі: транзакцію підписав сам гаманець, отже це його дія, а не переказ йому.
Але тут обидві сторони угоди мають суму в доларах: купівля — токен прийшов, а SOL чи стейбл пішли; продаж — навпаки.
Усе інше (переказ токена комусь, airdrop, вхідний SOL, обмін токена на токен) — не купівля і не продаж.
"""
import html
import secrets
import threading
import time

WSOL = "So11111111111111111111111111111111111111112"
STABLES = {"EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",      # USDC
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}      # USDT
QUOTE_MIN_USD = 1.0          # менше долара платні — це комісії й рента рахунку, а не угода (airdrop, переказ)
CODE_TTL_S = 600             # код прив'язки живе 10 хвилин
PREF_DEFAULTS = {"buys": True, "sells": True, "min_usd": 100.0}
DUST = 1e-3                  # менше тисячної одиниці другого токена поруч з основним — крихта, не друга нога угоди
SIZES = (1000, 10000)        # межі кольору крапки, $: менше першої, до другої, від другої
DOTS = ("🟢", "🟡", "🔴")


def _balances(arr, wallet):
    out = {}
    for b in arr or []:
        if isinstance(b, dict) and b.get("owner") == wallet:
            amt = (b.get("uiTokenAmount") or {}).get("uiAmount")
            out[b.get("mint")] = out.get(b.get("mint"), 0.0) + float(amt or 0)
    return out


def classify(tx, wallet, sol_usd):
    """[{side, mint, amount, usd, sig, ts}] — купівля чи продаж одного токена, яку підписав сам гаманець.

    tx — відповідь getTransaction (encoding jsonParsed). sol_usd — ціна SOL. Комісія мережі в угоду не входить: її
    платить той, хто підписав першим, і вона повертається до SOL перед підрахунком."""
    if not isinstance(tx, dict):
        return []
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:
        return []
    keys_full = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    signers = {k.get("pubkey") for k in keys_full if isinstance(k, dict) and k.get("signer")}
    if wallet not in signers:                  # переказ йому, airdrop, чужа угода, що його згадує, — не його дія
        return []
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in keys_full]
    sol = 0.0
    if wallet in keys:
        i = keys.index(wallet)
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        if i < len(pre) and i < len(post):
            sol = (post[i] - pre[i]) / 1e9
            if i == 0:                         # платник комісії: комісія — не частина угоди
                sol += (meta.get("fee") or 0) / 1e9
    pre_t, post_t = _balances(meta.get("preTokenBalances"), wallet), _balances(meta.get("postTokenBalances"), wallet)
    quote = sol * sol_usd                      # скільки грошей прийшло (+) чи пішло (−), у доларах
    moved = {}
    for mint in set(pre_t) | set(post_t):
        d = post_t.get(mint, 0.0) - pre_t.get(mint, 0.0)
        if mint == WSOL:
            quote += d * sol_usd
        elif mint in STABLES:
            quote += d
        elif abs(d) > 1e-12:
            moved[mint] = d
    if len(moved) > 1:                         # FOMO докладає до купівлі крихту іншого токена (0.0001): крихта — не угода
        moved = {m: d for m, d in moved.items() if abs(d) >= DUST}
    if len(moved) != 1:                        # нічого не рухалось, або токен на токен: не купівля й не продаж
        return []
    (mint, amount), = moved.items()
    sig = ((tx.get("transaction") or {}).get("signatures") or [""])[0]
    ts = int(tx.get("blockTime") or time.time())
    before, after = pre_t.get(mint, 0.0), post_t.get(mint, 0.0)
    # нова позиція — до купівлі був нуль чи пил (до 1 %); «продав усе» — після продажу лишився нуль чи пил, як «sold out» на сайті
    if amount > 0 and quote <= -QUOTE_MIN_USD:
        return [{"side": "buy", "mint": mint, "amount": amount, "usd": -quote, "sig": sig, "ts": ts, "new": before <= 0.01 * after}]
    if amount < 0 and quote >= QUOTE_MIN_USD:
        return [{"side": "sell", "mint": mint, "amount": -amount, "usd": quote, "sig": sig, "ts": ts, "all": after <= 0.01 * before,
                 "pct": min(100, round(-100 * amount / before)) if before > 0 else None}]
    return []                                  # токен пішов без грошей (переказ) чи прийшов без плати (airdrop)


def prefs_of(raw, default_min=None):
    """Налаштування людини: купівлі, продажі, мінімальна сума. Будь-що зайве чи криве — до меж."""
    p = dict(PREF_DEFAULTS, **({"min_usd": float(default_min)} if default_min is not None else {}))
    if isinstance(raw, dict):
        for k in ("buys", "sells"):
            if isinstance(raw.get(k), bool):
                p[k] = raw[k]
        try:
            if raw.get("min_usd") is not None:
                p["min_usd"] = max(0.0, min(1e6, float(raw["min_usd"])))
        except (TypeError, ValueError):
            pass
    return p


def wants(ev, prefs):
    return bool(prefs["buys" if ev["side"] == "buy" else "sells"]) and ev["usd"] >= prefs["min_usd"]


def watch_map(accounts, admins=(), open_to_all=False, max_wallets=50, default_min=None):
    """{гаманець: [{pk, chat, lists, prefs}]} — хто і в яких списках стежить за гаманцем.

    Рахується акаунт, у якого прив'язано Telegram і ввімкнено дзвіночок хоча б на одному списку. Поки сповіщення в
    закритому тесті (open_to_all=False), лише гаманці власника. На акаунт — не більше max_wallets гаманців."""
    out = {}
    admins = set(admins)
    for a in accounts:
        tg = a.get("telegram") or {}
        if not tg.get("chat") or (not open_to_all and a.get("pubkey") not in admins):
            continue
        lists = a.get("lists") or {}
        on = {lid for lid, l in lists.items() if isinstance(l, dict) and l.get("alerts")}
        if not on:
            continue
        prefs, n = prefs_of(a.get("alerts"), default_min), 0
        for w, meta in sorted((a.get("wallets") or {}).items(), key=lambda kv: -(kv[1].get("added_ms") or 0)):
            ls = [lists[x]["name"] for x in (meta.get("lists") or []) if x in on]
            if not ls:
                continue
            if n >= max_wallets:
                break
            # звідки гаманець (памп, з якого його зберегли) і власні мітки людини — щоб з повідомлення було видно, чий він
            out.setdefault(w, []).append({"pk": a["pubkey"], "chat": tg["chat"], "lists": ls, "prefs": prefs,
                                          "src": meta.get("symbol") or "", "tags": list(meta.get("my_tags") or [])[:3]})
            n += 1
    return out


class LinkCodes:
    """Одноразові коди «цей Telegram — цей гаманець»: видає сайт тому, хто увійшов гаманцем, забирає бот. 10 хвилин."""

    def __init__(self, ttl_s=CODE_TTL_S, cap=2000):
        self.ttl, self.cap, self.live, self.lock = ttl_s, cap, {}, threading.Lock()

    def issue(self, pubkey, now=None):
        now = time.time() if now is None else now
        with self.lock:
            for c in [c for c, (_, exp) in self.live.items() if exp <= now]:
                del self.live[c]
            if len(self.live) >= self.cap:
                for c in sorted(self.live, key=lambda c: self.live[c][1])[: len(self.live) - self.cap + 1]:
                    del self.live[c]
            code = secrets.token_hex(12)       # 96 біт: перебрати неможливо; лише [0-9a-f], як просить параметр start
            self.live[code] = (pubkey, now + self.ttl)
        return code

    def consume(self, code, now=None):
        now = time.time() if now is None else now
        with self.lock:
            v = self.live.pop(str(code or ""), None)
        return v[0] if v and v[1] > now else None


def money(v):
    v = float(v or 0)
    a = abs(v)
    s = f"{a / 1e9:.1f}B" if a >= 1e9 else f"{a / 1e6:.1f}M" if a >= 1e6 else f"{a / 1e3:.1f}K" if a >= 1e3 else f"{a:.0f}"
    return ("-$" if v < 0 else "$") + s.replace(".0B", "B").replace(".0M", "M").replace(".0K", "K")


def short(w):
    return f"{w[:6]}…{w[-4:]}" if isinstance(w, str) and len(w) > 12 else str(w)


def sold_share(trades, ev):
    """(продано з початку позиції %, продано цією угодою %) — від купленого, разом із цим продажем. None — купівель не видно.

    trades — угоди гаманця на токені (Solana Tracker, ledger.normalize). Власник, 30.09: «продано 40%», потім «продано 60%
    від початкової, тобто ще 20%». Позиція починається з першої купівлі після повного виходу: докупка після «sold all» —
    нова позиція. Поточну угоду рахуємо самі: Solana Tracker може ще її не бачити; пізніших угод не беремо."""
    upto = int(ev.get("ts") or 0) * 1000 + 999
    bought = sold = 0.0
    for t in sorted((t for t in trades or [] if t.get("tx") != ev.get("sig")), key=lambda t: t.get("time") or 0):
        q = float(t.get("qty") or 0)
        if q <= 0 or (t.get("time") or 0) > upto:
            continue
        if t.get("type") == "buy":
            if bought and bought - sold <= 0.01 * bought:    # попередню позицію закрито: рахуємо нову
                bought = sold = 0.0
            bought += q
        elif t.get("type") == "sell":
            sold += q
    if bought <= 0:
        return None
    step = float(ev.get("amount") or 0)
    return min(100, round(100 * (sold + step) / bought)), min(100, round(100 * step / bought))


def sold_text(ev):
    """«sold all»; «sold 60% (+20%)», коли вже продавав з цієї позиції; «sold 40%» за першим продажем; частка цієї угоди,
    коли історії позиції немає; нічого, коли не знаємо навіть її."""
    if ev.get("all"):
        return "sold all"
    total, step = ev.get("total"), ev.get("step")
    if total is not None:
        if total >= 99:
            return "sold all"
        return f"sold {total}%" + (f" (+{step}%)" if step is not None and step < total else "")
    return f"sold {ev['pct']}%" if ev.get("pct") else ""


def size_dot(usd, sizes=None):
    """Колір крапки — розмір угоди, як у каналах угод: три діапазони, межі — alerts_size_usd."""
    lo, hi = (list(sizes or SIZES) + list(SIZES))[:2]
    return DOTS[0] if usd < lo else DOTS[1] if usd < hi else DOTS[2]


def message(ev, wallet, sub, token, site="https://tracced.xyz", ca=True, sizes=None):
    """Текст повідомлення (HTML-розмітка Telegram) у вигляді каналів угод (власник, 30.09):
    1) крапка — розмір угоди (🟢 🟡 🔴), тікер — посилання на графік у tracced; купівля — 🆕 для нової позиції або
       «bought more», продаж — скільки позиції продано з початку («sold 60% (+20%)») або «sold all»; капа; tx;
    2) адреса токена — лише в першому повідомленні про цей токен у чаті (`ca`);
    3) чий гаманець: мітки людини, а без них коротка адреса (посилання на гаманець у Solscan); сума.
    Чуже (назва токена, мітки, памп) обрізане до екранування: розрізана посередині &amp; зламала б розмітку, і Telegram не
    прийняв би повідомлення."""
    def e(v, n):
        return html.escape(str(v)[:n])
    buy = ev["side"] == "buy"
    sym = (token or {}).get("symbol")
    name = f"<a href=\"{site}/token?mint={ev['mint']}\"><b>{'$' + e(sym, 24) if sym else short(ev['mint'])}</b></a>"
    head = [f"{size_dot(ev['usd'], sizes)} {name}" + (" 🆕" if buy and ev.get("new") else "")]
    if buy and ev.get("new") is False:
        head.append("bought more")
    if not buy and sold_text(ev):
        head.append(sold_text(ev))
    if (token or {}).get("mcap"):
        head.append(f"MC {money(token['mcap'])}")
    head.append(f"<a href=\"https://solscan.io/tx/{ev['sig']}\">tx</a>")
    tags = [e(t, 24) for t in (sub.get("tags") or [])[:3]]
    who = f"<a href=\"https://solscan.io/account/{wallet}\">{', '.join(tags) if tags else short(wallet)}</a>"
    # рядки через порожній рядок: у стрічці Telegram так легше читати (власник, 30.09)
    return "\n\n".join([" · ".join(head)] + ([f"<code>{ev['mint']}</code>"] if ca else []) + [f"{who} · <b>{money(ev['usd'])}</b>"])


def token_facts(report):
    """Назва і капа токена з відповіді Solana Tracker /tokens/{mint}: найбільший пул дає капу."""
    d = report if isinstance(report, dict) else {}
    pools = [p for p in d.get("pools") or [] if isinstance(p, dict)]
    main = max(pools, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0), default={})
    cap = (main.get("marketCap") or {}).get("usd") if isinstance(main.get("marketCap"), dict) else main.get("marketCap")
    return {"symbol": (d.get("token") or {}).get("symbol"), "mcap": cap if isinstance(cap, (int, float)) else None}
