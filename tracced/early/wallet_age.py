"""Вік гаманця з блокчейну: час його найстарішої транзакції (для тега-факту `fresh`).

Джерело — Solana RPC `getSignaturesForAddress(limit=1000)`: підписи йдуть від нових до старих, тож
останній у списку — найстаріший. Гортаємо сторінки, доки відповідь не порожня або доки не впремось у
MAX_PAGES; у другому випадку вік невідомий (`exact=False`, тегу `fresh` не буде). Зупинятись на короткій
сторінці НЕ можна: нода ST віддає [7, 1000, 1000, …], і тоді старий гаманець виглядав би свіжим.

Нода за замовчуванням — офіційна api.mainnet-beta.solana.com: вона віддає повну історію підписів
(проба 17.09.2026: гаманець з лютого → oldest = лютий, 0.3 с). publicnode НЕ підходить: тримає лише
~2 доби історії, тому кожен гаманець виглядав «свіжим» (100 % fresh на PAID — хибно).
Публічні ноди ріжуть серії запитів, тому між запитами пауза `pace_s`, а на 429/5xx — повтор з
наростаючою паузою. Один запит на гаманець, кеш 7 днів. Адресу ноди можна замінити через
SOLANA_RPC_URL (платна нода → без пауз), але вона мусить зберігати повну історію підписів.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request

DEFAULT_URL = "https://api.mainnet-beta.solana.com"
LIMIT = 1000
MAX_PAGES = 6            # 6 000 підписів: далі гаманець точно не «свіжий», а ходити глибше дорого
RETRY_SLEEP = (2, 4, 8)


class WalletAge:
    def __init__(self, url=None, cache=None, pace_s=0.5, post=None, sleep=time.sleep, tx_url=None):
        self.url = url or os.getenv("SOLANA_RPC_URL") or DEFAULT_URL
        # getTransaction і getSignaturesForAddress не конче живуть на одній ноді. Нода Solana Tracker віддає
        # повну історію підписів і не ріже серії, але на getTransaction відповідає Internal error (перевірено
        # 24.09.2026, усі варіанти параметрів). Тому одну транзакцію питаємо там, де вона працює.
        self.tx_url = tx_url or os.getenv("SOLANA_RPC_TX_URL") or (DEFAULT_URL if self.url != DEFAULT_URL else self.url)
        self.cache = cache
        self.pace_s = pace_s
        self.requests = 0
        self.cache_hits = 0
        self._post = post or self._http
        self._sleep = sleep
        self._last = 0.0
        self._lock = threading.Lock()

    # ── транспорт ──
    def _http(self, payload, url=None):
        req = urllib.request.Request(url or self.url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "early-wallets/1.0"},   # без UA деякі ноди дають 403
                                     method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    def _call(self, method, params, url=None):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        last_err = None
        for attempt in range(len(RETRY_SLEEP) + 1):
            with self._lock:
                wait = self.pace_s - (time.monotonic() - self._last)
                if wait > 0:
                    self._sleep(wait)
                try:
                    self.requests += 1
                    d = self._post(payload, url) if url else self._post(payload)
                    self._last = time.monotonic()
                except urllib.error.HTTPError as e:
                    self._last = time.monotonic()
                    last_err = e
                    if e.code not in (429, 500, 502, 503, 504) or attempt == len(RETRY_SLEEP):
                        raise
                except urllib.error.URLError as e:
                    self._last = time.monotonic()
                    last_err = e
                    if attempt == len(RETRY_SLEEP):
                        raise
                else:
                    if d.get("error"):
                        raise RuntimeError(f"RPC error: {d['error']}")
                    return d.get("result")
            self._sleep(RETRY_SLEEP[attempt])
        raise last_err  # pragma: no cover — цикл завжди або повертає, або кидає

    # ── факт ──
    def oldest_tx(self, wallet, refresh=False):
        """{"oldest_ms": ms|None, "exact": bool, "n": кількість підписів, "oldest_sig"} (кешовано)."""
        if self.cache is not None and not refresh:
            cached = self.cache.get(wallet)
            if cached is not None:
                self.cache_hits += 1
                return cached
        # Коротка сторінка НЕ означає кінець історії: нода Solana Tracker віддає першою сторінкою 7 підписів,
        # а далі ще двадцять дев'ять по тисячі. Тому гортаємо, доки відповідь не порожня, і лише вичерпавши
        # сторінки, зізнаємось, що точної дати не знаємо (exact=False, тег fresh не ставиться).
        before, last, n, pages = None, None, 0, 0
        while pages < MAX_PAGES:
            params = [wallet, {"limit": LIMIT}]
            if before:
                params[1]["before"] = before
            sigs = self._call("getSignaturesForAddress", params) or []
            if not sigs:
                break
            n += len(sigs)
            last, before = sigs[-1], sigs[-1].get("signature")
            pages += 1
        bt = last.get("blockTime") if last else None
        out = {"oldest_ms": int(bt) * 1000 if bt else None, "exact": pages < MAX_PAGES, "n": n,
               "oldest_sig": last.get("signature") if last else None}
        if self.cache is not None:
            self.cache.put(wallet, out)
        return out

    def funder(self, wallet, oldest_sig):
        """Хто дав гаманцю перший SOL: підписант найстарішої транзакції, чий баланс зменшився, коли баланс
        гаманця зріс. None, якщо перша транзакція не була вхідним переказом (кешовано)."""
        key = f"funder:{wallet}"
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                self.cache_hits += 1
                return cached.get("funder")
        tx = self._call("getTransaction", [oldest_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                         url=self.tx_url)
        out = {"funder": funder_from_tx(tx, wallet)}
        if self.cache is not None:
            self.cache.put(key, out)
        return out["funder"]

    def flush(self):
        if self.cache is not None:
            self.cache.flush()


def funder_from_tx(tx, wallet):
    """Чиста розбірка транзакції (jsonParsed): спонсор = підписант з найбільшим відпливом лампортів,
    якщо баланс `wallet` у цій транзакції зріс. Інакше None."""
    if not tx:
        return None
    meta, msg = tx.get("meta") or {}, (tx.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    if len(keys) != len(pre) or len(pre) != len(post):
        return None
    idx = next((i for i, k in enumerate(keys) if (k.get("pubkey") if isinstance(k, dict) else k) == wallet), None)
    if idx is None or post[idx] - pre[idx] <= 0:
        return None
    best, best_delta = None, 0
    for i, k in enumerate(keys):
        pk = k.get("pubkey") if isinstance(k, dict) else k
        signer = k.get("signer") if isinstance(k, dict) else (i == 0)
        delta = pre[i] - post[i]
        if signer and pk != wallet and delta > best_delta:
            best, best_delta = pk, delta
    return best
