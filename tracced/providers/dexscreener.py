"""DexScreener: коли за токен платили за видимість на їхньому сайті.

Публічний ендпоінт без ключа і без реєстрації, тож кредити Solana Tracker він не витрачає взагалі. Віддає
оплачені замовлення: профіль токена, рекламу, «community takeover». Нам цікавий лише час оплати — разом із
міграцією він пояснює, чому памп стався саме тоді.

Важливе застереження, яке йде і в документацію: заплатити за профіль може будь-хто, не конче розробник. Ми
показуємо факт оплати і час, а не автора.
"""
import http.client
import json
import time
import urllib.error
import urllib.request

API = "https://api.dexscreener.com/orders/v1/solana/"
TIMEOUT = 3                  # прикраса графіка: довше тримати спільний потік сторінок не варто
FAIL_TTL_S = 600             # збій теж кешуємо: лежачий сервіс не питаємо на кожен перегляд
LABELS = {"tokenProfile": "profile", "tokenAd": "ad", "trendingBarAd": "trending ad",
          "communityTakeover": "takeover"}


def orders(mint, cache=None):
    """[{ms, kind}] за зростанням часу. Будь-яка помилка — порожній список: це прикраса, а не факт таблиці.

    Збій лягає в кеш під тим самим ключем як {"failed": час}: десять хвилин відповідь порожня без запиту, далі
    питаємо знову, і вдала відповідь його перезаписує."""
    if cache is not None:
        hit = cache.get(mint)
        if isinstance(hit, dict):
            if time.time() - (hit.get("failed") or 0) < FAIL_TTL_S:
                return []
        elif hit is not None:
            return hit
    out = []
    try:
        req = urllib.request.Request(API + mint, headers={"Accept": "application/json",
                                                          "User-Agent": "tracced"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            d = json.loads(r.read().decode())
        rows = d.get("orders") if isinstance(d, dict) else d
        for o in rows or []:
            ms, kind = o.get("paymentTimestamp"), o.get("type")
            if ms and (o.get("status") or "approved") == "approved":
                out.append({"ms": int(ms), "kind": LABELS.get(kind, kind or "paid")})
        out.sort(key=lambda x: x["ms"])
    except (urllib.error.URLError, ValueError, TimeoutError, OSError, http.client.HTTPException):
        # чужий сервіс лежить — графік просто без цих міток
        if cache is not None:
            cache.put(mint, {"failed": time.time()})
        return []
    if cache is not None:
        cache.put(mint, out)
    return out
