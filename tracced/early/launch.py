"""Організовані запуски: факти з доказом, без балів (власник, 14.10; research/2026-10-13-organised-launches-for-tracced.md).

Два факти, обидва з безкоштовних джерел і обидва перевіряються посиланням:

1. **Пакети Jito перших хвилин.** Пакет — до п'яти транзакцій, які валідатор виконує поспіль: подати його може лише
   той, хто тримає всі підписані транзакції. Тож якщо гаманець A продав, а гаманець B купив **в одному пакеті**, це
   одні руки: B забрав токени A («продаж своїм», головний трюк запуску AI6). Гаманці в пакеті самого творця на
   старті — це його ж покупки. На AI6 tracced без цього показував 14 з 20 найприбутковіших як «найкращих трейдерів».
2. **Комісія творця.** Через програму розподілу комісій pump.fun (UpdateFeeShares) її переписують на інший гаманець:
   творець виглядає «чистим», а гроші йдуть повз нього. Кому і скільки SOL уже пройшло.

Мережеві частини отримують функції-клієнти ззовні (тести підставляють свої); тут лише розбір і правила."""
import json
import struct
import threading
import time
import urllib.error
import urllib.request

REV = 1                                   # версія перевірки: результат зі старшою перераховується при збагаченні
JITO_API = "https://bundles.jito.wtf/api/v1"
FEE_PROGRAM = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
UPDATE_SHARES = bytes.fromhex("bd0d8863bba4ed23")   # дискримінатор UpdateFeeShares: далі vec<(Pubkey, u16 bps)>
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s):
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def b58encode(b):
    n, out = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def decode_shares(data_b58):
    """Дані інструкції UpdateFeeShares → [(гаманець, частка в bps)]; None, якщо це не вона."""
    try:
        d = b58decode(data_b58 or "")
    except ValueError:
        return None
    if len(d) < 12 or d[:8] != UPDATE_SHARES:
        return None
    n = struct.unpack_from("<I", d, 8)[0]
    out, off = [], 12
    for _ in range(min(n, 32)):
        if off + 34 > len(d):
            break
        out.append((b58encode(d[off:off + 32]), struct.unpack_from("<H", d, off + 32)[0]))
        off += 34
    return out


# ── мережа: прості клієнти з паузою; кеш пакетів — назавжди (пакет не змінюється) ──

def _get_json(url, body=None, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "User-Agent": "tracced"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


class Paced:
    """Не частіше одного виклику за `pace` секунд; 429 — пауза і ще дві спроби."""
    def __init__(self, pace):
        self.pace, self.last, self.lock = pace, 0.0, threading.Lock()
        self.failed = 0

    def call(self, fn):
        for attempt in range(3):
            with self.lock:
                wait = self.pace - (time.monotonic() - self.last)
                if wait > 0:
                    time.sleep(wait)
                self.last = time.monotonic()
            try:
                return fn()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < 2:
                    time.sleep(2 + 3 * attempt)
                    continue
                if e.code in (400, 404):
                    return None
                raise
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt < 1:
                    continue                      # повільна відповідь: ще раз, далі — «невідомо», а не падіння прогону
                self.failed += 1
                return None
        return None


class Jito:
    """Публічне API пакетів Jito: підпис → пакет, пакет → його транзакції і хто платив чайові."""
    def __init__(self, cache=None, pace=0.3, get=None):
        self.cache = cache if cache is not None else {}
        self.p = Paced(pace)
        self.get = get or _get_json
        self.calls = 0

    def bundle_of(self, sig):
        key = "tx:" + sig
        if key not in self.cache:
            self.calls += 1
            d = self.p.call(lambda: self.get(f"{JITO_API}/bundles/transaction/{sig}"))
            self.cache[key] = (d[0].get("bundle_id") if isinstance(d, list) and d else None)
        return self.cache[key]

    def bundle(self, bid):
        key = "b:" + bid
        if key not in self.cache:
            self.calls += 1
            d = self.p.call(lambda: self.get(f"{JITO_API}/bundles/bundle/{bid}"))
            d = d[0] if isinstance(d, list) and d else (d or {})
            self.cache[key] = {"txs": d.get("txSignatures") or [], "tippers": d.get("tippers") or [], "slot": d.get("slot")}
        return self.cache[key]


class Rpc:
    """Публічна нода Solana (0 кредитів), з паузою: вона тримає ~40 викликів за 10 с на метод."""
    def __init__(self, url="https://api.mainnet-beta.solana.com", pace=0.6, post=None):
        self.url, self.p, self.post = url, Paced(pace), post or _get_json
        self.calls = 0

    def __call__(self, method, params):
        self.calls += 1
        d = self.p.call(lambda: self.post(self.url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}))
        return (d or {}).get("result")


# ── 1. пакети Jito перших хвилин ──

def receivers(rpc, sig, mint, supply):
    """Хто отримав токен у транзакції: власники, у яких баланс цього токена зріс. Пул і криву (на старті вони тримають
    більшість випуску) відсіюємо за балансом понад 10% випуску до чи після. [(власник, кількість)]."""
    tx = rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]) if rpc else None
    meta = (tx or {}).get("meta") or {}
    if not tx or meta.get("err"):
        return []
    def bal(xs):
        out = {}
        for x in xs or []:
            if x.get("mint") == mint and x.get("owner"):
                out[x["owner"]] = out.get(x["owner"], 0.0) + float((x.get("uiTokenAmount") or {}).get("uiAmount") or 0)
        return out
    pre, post = bal(meta.get("preTokenBalances")), bal(meta.get("postTokenBalances"))
    big = 0.1 * supply if supply else float("inf")
    return [(o, post[o] - pre.get(o, 0.0)) for o in post
            if post[o] - pre.get(o, 0.0) > 0 and pre.get(o, 0.0) <= big and post[o] <= big]   # крива отримує випуск при створенні


def buybacks(trades, created_ms, window_ms, jito, creator=None, max_lookups=120, rpc=None, mint=None, supply=None):
    """Угоди (wallet, type, time, qty, tx) → що знайшли пакети Jito.

    Продажі перших `window_ms` після запуску перевіряються по одному: якщо продаж у пакеті, а в тому ж пакеті
    купив інший гаманець зі списку — це пара «продав своєму». Покупки в пакеті з покупкою творця на старті — пакет
    запуску. Повертає {"pairs": [...], "launch": {...} або None, "lookups": n, "sells": n, "capped": bool}."""
    by_tx = {t["tx"]: t for t in trades if t.get("tx")}
    end = created_ms + window_ms
    # найбільші продажі першими: пакет «продаж своїм» переносить відсотки випуску, а не крихти, і стеля лишається
    # на них (на AI6 — 3–4% кожен у перші 17 секунд)
    sells = sorted((t for t in by_tx.values() if t["type"] == "sell" and created_ms <= (t["time"] or 0) <= end),
                   key=lambda t: -(t.get("qty") or 0))
    pairs, seen_b, looked = [], set(), 0
    for sell in sells[:max_lookups]:
        looked += 1
        bid = jito.bundle_of(sell["tx"])
        if not bid or bid in seen_b:
            continue
        seen_b.add(bid)
        b = jito.bundle(bid)
        got = {by_tx[s]["wallet"]: by_tx[s].get("qty") or 0 for s in b["txs"]
               if s in by_tx and by_tx[s]["type"] == "buy" and by_tx[s]["wallet"] != sell["wallet"]}
        for s in b["txs"]:                         # покупці поза нашим списком (дрібні, чи угода під чужим підписом)
            if s not in by_tx and s != sell["tx"] and rpc and mint:
                for o, q in receivers(rpc, s, mint, supply):
                    if o != sell["wallet"]:
                        got[o] = max(got.get(o, 0), q)
        if got:
            pairs.append({"bundle": bid, "seller": sell["wallet"], "sold": sell.get("qty") or 0, "time": sell["time"],
                          "buyers": [[w, q] for w, q in got.items()], "tippers": b["tippers"][:3]})
    launch = None
    if creator:
        first = sorted((t for t in by_tx.values() if t["wallet"] == creator and t["type"] == "buy"
                        and (t["time"] or 0) <= created_ms + 10_000), key=lambda t: t["time"])
        if first:
            looked += 1
            bid = jito.bundle_of(first[0]["tx"])
            if bid:
                b = jito.bundle(bid)
                ws = {by_tx[s]["wallet"] for s in b["txs"] if s in by_tx and by_tx[s]["type"] == "buy"}
                for s in b["txs"]:                 # спільний підпис: двоє отримують токени в одній транзакції
                    if rpc and mint:
                        ws |= {o for o, _ in receivers(rpc, s, mint, supply)}
                ws = sorted(ws - {creator})
                launch = {"bundle": bid, "wallets": ws, "tippers": b["tippers"][:3]}
    return {"pairs": pairs, "launch": launch, "lookups": looked, "sells": len(sells), "capped": len(sells) > max_lookups}


# ── 2. комісія творця ──

def fee_shares(rpc, creator, mint, created_ms, max_tx=30):
    """Кому творець переписав комісію: остання UpdateFeeShares по цьому токену за першу добу.

    {"to": [[гаманець, bps]], "tx": підпис, "config": рахунок налаштування} або None."""
    sigs = rpc("getSignaturesForAddress", [creator, {"limit": 1000}]) or []
    lo, hi = created_ms / 1000 - 60, created_ms / 1000 + 86_400
    near = sorted((x for x in sigs if x.get("blockTime") and lo <= x["blockTime"] <= hi and not x.get("err")),
                  key=lambda x: x.get("slot") or 0)
    found = None
    for x in near[:max_tx]:
        tx = rpc("getTransaction", [x["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        if not tx:
            continue
        for ins in (tx.get("transaction") or {}).get("message", {}).get("instructions", []):
            if ins.get("programId") != FEE_PROGRAM or mint not in (ins.get("accounts") or []):
                continue
            shares = decode_shares(ins.get("data"))
            if shares:
                acc = ins.get("accounts") or []
                i = acc.index(mint)
                found = {"to": [[w, bps] for w, bps in shares], "tx": x["signature"],
                         "config": acc[i + 1] if i + 1 < len(acc) else None}
    return found


def fee_paid(rpc, config, wallet, max_tx=200):
    """Скільки SOL виплати комісії (DistributeCreatorFees) принесли гаманцю: історія рахунку налаштування — лише
    операції з комісією, тож вона коротка. {"sol": x, "txs": n, "capped": bool}."""
    sigs, before = [], None
    for _ in range(3):
        p = {"limit": 1000}
        if before:
            p["before"] = before
        page = rpc("getSignaturesForAddress", [config, p]) or []
        sigs += [x for x in page if not x.get("err")]
        if len(page) < 1000:
            break
        before = page[-1]["signature"]
    sol, n = 0.0, 0
    for x in sigs[:max_tx]:
        tx = rpc("getTransaction", [x["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        if not tx:
            continue
        logs = (tx.get("meta") or {}).get("logMessages") or []
        if not any("DistributeCreatorFees" in m for m in logs):
            continue
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in tx["transaction"]["message"].get("accountKeys", [])]
        if wallet not in keys:
            continue
        i = keys.index(wallet)
        pre, post = tx["meta"].get("preBalances") or [], tx["meta"].get("postBalances") or []
        if i < len(pre) and i < len(post) and post[i] > pre[i]:
            sol += (post[i] - pre[i]) / 1e9
            n += 1
    return {"sol": round(sol, 3), "txs": n, "capped": len(sigs) > max_tx}


# ── теги і підсумок для сторінки ──

def wallet_tags(found):
    """{гаманець: [теги]} із знайденого: own-bundle — обидва боки пари в одному пакеті; launch-bundle — у пакеті творця."""
    out = {}
    for p in (found or {}).get("pairs") or []:
        for w in [p["seller"]] + [b[0] for b in p["buyers"]]:
            out.setdefault(w, set()).add("own-bundle")
    for w in (((found or {}).get("launch") or {}).get("wallets") or []):
        out.setdefault(w, set()).add("launch-bundle")
    return {w: sorted(t) for w, t in out.items()}


def summary(found, supply):
    """Що показати на токені: частка випуску, викуплена своїми в пакетах, скільки пакетів, комісія творця."""
    found = found or {}
    pairs = found.get("pairs") or []
    took = sum(q for p in pairs for _, q in p["buyers"])
    out = {"pairs": len(pairs), "bought_back_pct": round(100 * took / supply, 2) if supply else None,
           "launch_wallets": len(((found.get("launch") or {}).get("wallets") or []))}
    fee = found.get("fee")
    if fee and fee.get("to"):
        out["fee_to"] = fee["to"]
        out["fee_sol"] = (fee.get("paid") or {}).get("sol")
    return out


# ── гаманці організованих запусків між аналізами: готові списки їх не показують ──
OPERATORS_PATH = "output/early/launch_wallets.json"


def load_operators(path=None):
    path = path or OPERATORS_PATH
    try:
        with open(path, encoding="utf-8") as f:
            return set((json.load(f) or {}).get("wallets") or {})
    except (OSError, ValueError):
        return set()


def remember(wallet_tags_, mint, path=None):
    """Дописує гаманці з тегами запуску: {wallet: [mint, …]}. Запис атомарний, файл маленький."""
    if not wallet_tags_:
        return
    import os
    path = path or OPERATORS_PATH
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f) or {}
    except (OSError, ValueError):
        d = {}
    ws = d.setdefault("wallets", {})
    for w in wallet_tags_:
        if mint not in ws.setdefault(w, []):
            ws[w].append(mint)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, path)
