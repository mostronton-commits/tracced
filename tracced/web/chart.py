"""Formatting helpers for the pages and the candles endpoint. Pure functions.

The chart itself is drawn in the browser (TradingView Lightweight Charts, vendored under
static/vendor); the server only serves market-cap candles and short labels: 500K / 1.2M / 12M,
'Sep 22, 12:00' for dates.
"""
import datetime

HOUR = 3_600_000
TFS = ("1m", "5m", "15m", "1h")
TF_SEC = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
# how much time one browser request for candles covers, per timeframe (seconds);
# ranges are snapped to this grid so repeated visits hit the 72-hour cache
CHUNK_SEC = {"1m": 12 * 3600, "5m": 3 * 86400, "15m": 10 * 86400, "1h": 60 * 86400}


def fmt_mcap(v):
    """980 → '980', 1500 → '1.5K', 500000 → '500K', 1234567 → '1.2M', 12300000 → '12M', 999.98M → '1B'."""
    try:
        v = float(v)
    except Exception:  # noqa: BLE001 — None, '', jinja Undefined
        return "—"
    if v != v:
        return "—"
    sign, v = ("-" if v < 0 else ""), abs(v)
    for lim, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= lim * 0.9995:
            x = max(v / lim, 1.0)
            s = f"{x:.1f}" if x < 10 else f"{x:.0f}"
            if "." in s:
                s = s.rstrip("0").rstrip(".")
            return f"{sign}{s}{suf}"
    return f"{sign}{v:.0f}"


def fmt_dt(ms, year=False, utc=False):
    """'Sep 22, 12:00' for lists; 'Sep 22, 2026 12:00 UTC' for the token card."""
    if not ms:
        return "—"
    d = datetime.datetime.utcfromtimestamp(ms / 1000)
    s = d.strftime("%b %-d, %Y %H:%M") if year else d.strftime("%b %-d, %H:%M")
    return s + (" UTC" if utc else "")


def to_input(ms):
    """ms → value for <input type=datetime-local> (UTC)."""
    if not ms:
        return ""
    return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%dT%H:%M")


def from_input(s):
    """datetime-local value (UTC) → ms; None if empty or unparsable."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return int(datetime.datetime.strptime(s, fmt).replace(
                tzinfo=datetime.timezone.utc).timestamp() * 1000)
        except ValueError:
            continue
    return None


def auto_tf(span_ms):
    """Timeframe for a span: ≤24h → 1m, ≤7d → 5m, ≤30d → 15m, else 1h."""
    h = span_ms / HOUR
    return "1m" if h <= 24 else "5m" if h <= 24 * 7 else "15m" if h <= 24 * 30 else "1h"


def snap_range(a_sec, b_sec, tf):
    """Snap [a, b] (seconds) outward to the chunk grid of the timeframe."""
    chunk = CHUNK_SEC.get(tf, CHUNK_SEC["1h"])
    return (a_sec // chunk) * chunk, ((b_sec + chunk - 1) // chunk) * chunk


def candles_mcap(candles, supply):
    """Server candles (ms, price) → browser candles (seconds, market cap), sorted, deduplicated."""
    out, seen = [], set()
    for c in candles:
        if not c.get("close") or not supply:
            continue
        t = int(c["time"] // 1000)
        if t in seen:
            continue
        seen.add(t)
        o = c.get("open") or c["close"]
        out.append({"time": t, "open": o * supply, "high": (c.get("high") or max(o, c["close"])) * supply,
                    "low": (c.get("low") or min(o, c["close"])) * supply, "close": c["close"] * supply,
                    "volume": float(c.get("volume") or 0)})
    out.sort(key=lambda c: c["time"])
    return out
