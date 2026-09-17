"""Мелкие помощники: HTTP с сертификатами, нормализация времени, медиана."""
import ssl
import json
import datetime
import urllib.request
import urllib.error

# macOS/образы иногда не находят корневые сертификаты — берём из certifi, если есть.
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()


def to_ms(t):
    """Разные эндпоинты ST дают время в секундах или миллисекундах — приводим к мс."""
    if t is None:
        return None
    t = float(t)
    return int(t * 1000) if t < 1e12 else int(t)


def http_get_json(url, headers, timeout=30):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read().decode())


def http_post_json(url, payload, headers=None, timeout=30):
    """POST JSON → JSON. Нужен для JSON-RPC узлов (eth_*, getTransaction и т.п.)."""
    body = json.dumps(payload).encode()
    hdrs = {"content-type": "application/json"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read().decode())


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    m = n // 2
    return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2


def iso_ms(ms):
    """Время в мс → человекочитаемая строка UTC (для файлов/вывода)."""
    if not ms:
        return ""
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def parse_time_to_ms(s):
    """Ввод пользователя (--from/--to): unix (сек/мс) или 'YYYY-MM-DD HH:MM'."""
    if s is None:
        return None
    s = str(s).strip()
    if s.isdigit():
        return to_ms(int(s))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"Не понял время: {s!r} (используй unix или 'YYYY-MM-DD HH:MM')")


def get_key():
    """Solana Tracker API key: environment first, then .env in the working directory."""
    import os
    key = os.environ.get("SOLANATRACKER_API_KEY")
    if key:
        return key.strip()
    if os.path.exists(".env"):
        for line in open(".env"):
            if line.strip().startswith("SOLANATRACKER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None
