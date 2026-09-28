"""API для партнерів: перевірка токена правилами, а не оцінкою, і ключі, які власник веде в /admin.

Solana Tracker забороняє передавати третім сторонам свої сирі цифри без письмового дозволу, тож назовні йдуть лише
похідні: рівень кожного правила (low / medium / high), які правила на high і чи пройшла монета пороги, які власник
поставив цьому ключу. Пороги — на ключі, а не в запиті: інакше перебором порогів можна було б відновити сирі частки.

Тут лише чиста логіка і файл ключів, без aiohttp і без мережі.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

KEY_PREFIX = "tr_"
RULES = ("dev", "bundle", "top10", "snipers", "insiders", "bundled_launch", "mint", "freeze", "liquidity")
# межі рівнів у відсотках запасу монети: до першої — low, до другої включно — medium, вище — high
CUTS = {"dev": (5, 20), "bundle": (5, 20), "top10": (20, 40), "snipers": (5, 15), "insiders": (5, 15),
        "bundled_launch": (20, 50)}
LIQ_HIGH, LIQ_MEDIUM = 5_000, 20_000             # $ ліквідності пулу біржі: менше першої — high, менше другої — medium
LP_BURN_MIN = 90                                  # % спалених LP-токенів пулу, з якого ліквідність уже не забрати
# у пулах зі сконцентрованою ліквідністю нема LP-токенів — лише позиції маркетмейкерів, тож «спалено» до них не
# застосовується (Solana Tracker завжди пише 0); їх оцінюємо лише за розміром ліквідності
CONCENTRATED = ("dlmm", "clmm", "whirlpool", "orca")
# на кривій лаунчпада ліквідність — сама крива: вивести її не можна, тож і ризику «забрали пул» нема
CURVES = {"pumpfun", "meteora-curve", "raydium-launchpad", "raydium-launchlab", "launchlab", "boop", "moonit", "believe",
          "bonk", "letsbonk"}
THRESHOLD_RULES = ("dev", "bundle", "top10")     # пороги «пускати / ні», які власник ставить ключу
DEFAULT_THRESHOLDS = {"dev": 20, "bundle": 20, "top10": 20}
DEFAULT_DAILY_CAP = 1000


def _pct(v):
    """Частка у відсотках 0–100; None — невідомо. Понад 100 буває збоєм джерела (подвійний облік пачок) — обрізаємо."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return None
    return max(0.0, min(100.0, float(v)))


def facts(d):
    """Сирі факти з відповіді Solana Tracker `/tokens/{mint}` — лише для обчислень тут, назовні не йдуть."""
    d = d if isinstance(d, dict) else {}
    r = d.get("risk") or {}
    pools = [p for p in (d.get("pools") or []) if isinstance(p, dict)]
    main = max(pools, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0), default={})
    b = r.get("bundlers") or {}
    security = [p.get("security") or {} for p in pools]
    created = ((d.get("token") or {}).get("creation") or {}).get("created_time")
    return {
        "dev": _pct((r.get("dev") or {}).get("percentage")),
        "bundle": _pct(b.get("totalPercentage")),
        "top10": _pct(r.get("top10")),
        "snipers": _pct((r.get("snipers") or {}).get("totalPercentage")),
        "insiders": _pct((r.get("insiders") or {}).get("totalPercentage")),
        "bundled_launch": _pct(b.get("totalInitialPercentage")),
        "mint": any(s.get("mintAuthority") for s in security),
        "freeze": any(s.get("freezeAuthority") for s in security),
        "liquidity_usd": (main.get("liquidity") or {}).get("usd"),
        "lp_burn": main.get("lpBurn"),
        "market": main.get("market"),
        "created_s": created if isinstance(created, (int, float)) else None,
        "rugged": bool(r.get("rugged")),
        "known": bool(r),
    }


def level(rule, f):
    """low / medium / high / unknown одного правила; межі — у CUTS, LIQ_* і в документації /docs/api."""
    if rule in CUTS:
        v = f.get(rule)
        if v is None:
            return "unknown"
        low, high = CUTS[rule]
        return "low" if v < low else "medium" if v <= high else "high"
    if rule in ("mint", "freeze"):
        return "high" if f.get(rule) else "low" if f.get("known") else "unknown"
    if rule == "liquidity":
        market, burn, usd = f.get("market"), f.get("lp_burn"), f.get("liquidity_usd")
        if market in CURVES:
            return "low"
        pooled = not any(c in str(market or "") for c in CONCENTRATED)
        if pooled and isinstance(burn, (int, float)) and burn < LP_BURN_MIN:
            return "high"                                    # пул не спалено: творець може забрати ліквідність
        if not isinstance(usd, (int, float)):
            return "unknown"
        return "high" if usd < LIQ_HIGH else "medium" if usd < LIQ_MEDIUM else "low"
    raise ValueError(rule)


def evaluate(d, thresholds, now_s=None):
    """Відповідь партнеру з відповіді Solana Tracker: рівні правил і чи пройшла монета пороги ключа.

    Невідома частка під порогом — не пропуск: фільтр скаму закривається, коли не знає (у `failed` — `no_data`)."""
    f = facts(d)
    levels = {r: level(r, f) for r in RULES}
    high = [r for r in RULES if levels[r] == "high"]
    failed = []
    for rule in THRESHOLD_RULES:
        limit = (thresholds or {}).get(rule)
        if limit is None:
            continue
        v = f.get(rule)
        if v is None:
            if "no_data" not in failed:
                failed.append("no_data")
        elif v > float(limit):
            failed.append(rule)
    if f["rugged"]:
        failed.append("rugged")
    now_s = time.time() if now_s is None else now_s
    age = round((now_s - f["created_s"]) / 60) if f["created_s"] else None
    return {"passes": not failed, "failed": failed, "high": high, "flags": f"{len(high)} of {len(RULES)}",
            "levels": levels, "age_minutes": age}


# ───────────────────────── ключі ─────────────────────────

def _hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


def _new_key():
    return KEY_PREFIX + secrets.token_urlsafe(24)


class KeyStore:
    """Ключі партнерів у файлі. Зберігаємо лише sha256 ключа і перші символи, щоб його впізнати; сам ключ власник бачить
    один раз — коли створює чи перевипускає. Вимкнений ключ відмовляє одразу, перевипущений — старий більше не діє."""

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            return {}
        return d if isinstance(d, dict) else {}

    def _save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.replace(tmp, self.path)

    def all(self):
        """Усі ключі без відбитків, новіші першими."""
        with self._lock:
            d = self._load()
        out = [dict({k: v for k, v in rec.items() if k != "hash"}, id=kid) for kid, rec in d.items()]
        return sorted(out, key=lambda r: -int(r.get("created_ms") or 0))

    def create(self, name, now_ms=None):
        """(id, ключ): ключ показати власнику один раз."""
        key, kid = _new_key(), secrets.token_hex(4)
        with self._lock:
            d = self._load()
            d[kid] = {"name": str(name or "partner").strip()[:40] or "partner", "hash": _hash(key), "prefix": key[:8],
                      "created_ms": int(now_ms or time.time() * 1000), "rotated_ms": None, "enabled": True,
                      "daily_cap": DEFAULT_DAILY_CAP, "thresholds": dict(DEFAULT_THRESHOLDS)}
            self._save(d)
        return kid, key

    def rotate(self, kid, now_ms=None):
        """Новий ключ замість старого (старий одразу перестає діяти); None — такого нема."""
        key = _new_key()
        with self._lock:
            d = self._load()
            if kid not in d:
                return None
            d[kid].update(hash=_hash(key), prefix=key[:8], rotated_ms=int(now_ms or time.time() * 1000))
            self._save(d)
        return key

    def update(self, kid, **fields):
        """Змінити назву, вимикач, денну межу чи пороги. False — такого ключа нема."""
        allowed = {"name", "enabled", "daily_cap", "thresholds"}
        with self._lock:
            d = self._load()
            if kid not in d:
                return False
            d[kid].update({k: v for k, v in fields.items() if k in allowed})
            self._save(d)
        return True

    def delete(self, kid):
        with self._lock:
            d = self._load()
            if d.pop(kid, None) is None:
                return False
            self._save(d)
        return True

    def find(self, key):
        """Запис ключа за самим ключем (з id), або None. Порівняння відбитків — сталого часу."""
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX) or len(key) > 100 or not key.isascii():
            return None
        want = _hash(key)
        with self._lock:
            d = self._load()
        for kid, rec in d.items():
            if hmac.compare_digest(str(rec.get("hash") or ""), want):
                return dict({k: v for k, v in rec.items() if k != "hash"}, id=kid)
        return None
