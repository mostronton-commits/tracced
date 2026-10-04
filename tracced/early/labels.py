"""Мітки адрес від InsightX (api.insightx.network): хто стоїть за спонсором гаманця — біржа, застосунок, казино.

Спонсор — гаманець, що дав першому SOL (wallet_age.funder). Наш список бірж (exchanges.py) знає лише гарячі гаманці з
власних звітів бірж; InsightX знає більше (спайк 02.10 на PAID: названо 22 спонсори, з них 17 нових для нас — Coinbase,
MoonPay, Kraken, Revolut…). Власник 04.10: «подивимось, як це працює і що воно дає додатково».

Один запит — до 100 адрес. Безкоштовний план: 5 запитів на хвилину і 1000 на місяць, тому кеш (мітка живе 30 днів,
«мітки нема» — 7), місячний лічильник з резервом і пауза між запитами. Ключ — лише з оточення (INSIGHTX_API_KEY).
Розбір відповіді й назви — чисті функції; мережа — лише в `_http`.
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request

URL = "https://api.insightx.network/labels/v1/sol/"
BATCH = 100
KEEP_S = 30 * 86_400          # мітка біржі не змінюється тижнями
NONE_S = 7 * 86_400           # «мітки нема» перепитуємо частіше: їхня база росте
# як сказати людині, що це за спонсор (перше слово мітки InsightX); решта — «a known service»
KINDS = {"exchange": "an exchange", "dex": "a trading app", "gambling": "a gambling site", "bridge": "a bridge",
         "defi": "a DeFi app", "payments": "a payments app", "mev": "an MEV bot"}
# назви, які InsightX пише не так, як їх пишуть самі компанії
CASE = {"moonpay": "MoonPay", "kucoin": "KuCoin", "okx": "OKX", "mexc": "MEXC", "htx": "HTX", "bybit": "Bybit",
        "bitget": "Bitget", "changenow": "ChangeNOW", "sideshift": "SideShift"}


class Unavailable(Exception):
    """Ключ не прийнято або квоту вичерпано: цей прохід далі не питає."""


def short_name(label):
    """«Binance: Hot Wallet» → «Binance», «Coinbase Hot Wallet 3» → «Coinbase», «Unibot SOL Fee Address (New)» →
    «Unibot». Повна мітка лишається в підказці."""
    s = str(label or "").strip()
    name = s.split(":")[0]
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"\b(hot|cold|deposit|withdrawal)?\s*wallet\b.*$", "", name, flags=re.I)
    name = re.sub(r"\bSOL\s+fee\s+address\b.*$|\bfee\s+address\b.*$", "", name, flags=re.I)
    name = re.sub(r"\s+\d+$", "", name.strip()).strip(" -·")
    if not name:
        name = s[:24]
    return CASE.get(name.lower(), name)[:24]


def entry_of(item):
    """Один запис відповіді → {"name", "label", "kind"}; без мітки — None."""
    if not isinstance(item, dict) or not item.get("label"):
        return None
    tags = [str(t).lower() for t in item.get("tags") or [] if t]
    return {"name": short_name(item["label"]), "label": str(item["label"])[:80], "kind": tags[0] if tags else None}


# такий спонсор роздає SOL незнайомим людям, як біржа: гаманці від нього — не бандл (людина-KOL сюди не входить)
SERVICE_KINDS = {"exchange", "dex", "gambling", "bridge", "defi", "payments"}


# what a funder is, without InsightX's name for it: their terms allow derived insights, not their data «in raw or
# substantially similar form» (Terms of Service, API Usage, read 04.10)
SHORT = {"exchange": "an exchange", "dex": "an app", "gambling": "a casino", "bridge": "a bridge", "defi": "a DeFi app",
         "payments": "a payments app", "mev": "an MEV bot"}


def kind_text(kind):
    return KINDS.get(kind or "", "a known service")


class InsightX:
    def __init__(self, key, cache=None, budget=None, pace_s=13.0, post=None, sleep=time.sleep, now=time.time):
        self.key = key
        self.cache = cache                  # JsonCache: «ix:{адреса}» → {"e": запис|None, "at": секунди}
        self.budget = budget                # wallet_age.MonthBudget: запити за календарний місяць
        self.pace_s = pace_s
        self.requests = 0
        self._get_json = post or self._http
        self._sleep, self._now = sleep, now
        self._lock, self._last = threading.Lock(), 0.0

    def _http(self, url):
        req = urllib.request.Request(url, headers={"X-API-Key": self.key, "Accept": "application/json",
                                                   "User-Agent": "tracced/0.7 (+https://tracced.xyz)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())

    def paused(self):
        return bool(self.budget and self.budget.exhausted())

    def cached(self, addr):
        """Що відомо без запиту: (True, запис|None) — питали і пам'ятаємо; (False, None) — ще не питали або застаріло."""
        hit = self.cache.get(f"ix:{addr}") if self.cache is not None else None
        if not isinstance(hit, dict):
            return False, None
        age = self._now() - float(hit.get("at") or 0)
        if age > (KEEP_S if hit.get("e") else NONE_S):
            return False, None
        return True, hit.get("e")

    def _call(self, batch):
        with self._lock:                                  # 5 на хвилину: між запитами не менше pace_s
            wait = self.pace_s - (time.monotonic() - self._last)
            if self._last and wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            if self.budget is not None:
                self.budget.spend(1)                      # невдалий запит теж рахується в їхній квоті
        try:
            d = self._get_json(URL + ",".join(batch))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 429):
                raise Unavailable(f"InsightX answered {e.code}") from e
            raise
        return d if isinstance(d, list) else (d or {}).get("data") or []

    def lookup(self, addresses, max_calls=3):
        """{адреса: запис} для тих, у кого є мітка, — з кешу і не більше max_calls нових запитів. Чого не встигли
        спитати, лишається на наступний раз; збій чи відмова не валять того, хто питає."""
        out, todo = {}, []
        for a in dict.fromkeys(a for a in addresses if a):
            known, e = self.cached(a)
            if known:
                if e:
                    out[a] = e
            else:
                todo.append(a)
        calls = 0
        for i in range(0, len(todo), BATCH):
            if calls >= max_calls or self.paused():
                break
            batch = todo[i:i + BATCH]
            try:
                items = self._call(batch)
            except Unavailable:
                break
            except Exception:  # noqa: BLE001 — мережа чи їхній збій: решту спитаємо наступного разу
                break
            calls += 1
            got = {it.get("address"): entry_of(it) for it in items if isinstance(it, dict)}
            now = self._now()
            for a in batch:
                e = got.get(a)
                if self.cache is not None:
                    self.cache.put(f"ix:{a}", {"e": e, "at": now})
                if e:
                    out[a] = e
        return out

    def flush(self):
        if self.cache is not None:
            self.cache.flush()
        if self.budget is not None:
            self.budget.flush()
