"""Вікно раннього входу: межі ставить людина; детектор пампів — лише підказка.

Свічки тут у вигляді [{"time": ms, "open", "high", "low", "close", "volume"}].
Капа = close × supply (supply сталий — перевірено на KET, усі пули однакові).
"""
from ..engine.detect import detect_pumps

HOUR = 3_600_000


def to_detect_series(candles):
    """Формат, який очікує engine.detect: [(t_ms, close, volume)]."""
    return [(c["time"], c.get("close"), c.get("volume")) for c in candles if c.get("close")]


def mcap_series(candles, supply):
    return [(c["time"], c["close"] * supply) for c in candles if c.get("close") and supply]


def mcap_at(series, t):
    """Капа на момент t: остання точка не пізніше t (до першої — перша)."""
    if not series:
        return None
    best = None
    for ts, m in series:
        if ts <= t:
            best = m
        else:
            break
    return best if best is not None else series[0][1]


def suggest(candles, supply, cfg, peak_hours=6):
    """Підказки меж від автодетекту пампів: [{acc_start, pump_start, peak_time, base_mcap,
    peak_mcap, magnitude}]. Порожній список — теж відповідь («автопідказок немає»)."""
    series = to_detect_series(candles)
    if not series or not supply:
        return []
    out = []
    mc = mcap_series(candles, supply)
    for p in detect_pumps(series, supply, cfg):
        lo, hi = p["pump_start"], p["pump_start"] + peak_hours * HOUR
        seg = [(t, m) for t, m in mc if lo <= t <= hi] or [(lo, p["peak_mcap"])]
        peak_t, peak_m = max(seg, key=lambda x: x[1])
        out.append({
            "acc_start": p["acc_start"],
            "pump_start": p["pump_start"],
            "peak_time": peak_t,
            "base_mcap": p["base_mcap"],
            "peak_mcap": max(p["peak_mcap"], peak_m),
            "magnitude": p["magnitude"],
        })
    return out


def validate(from_ms, to_ms, created_ms=None, now_ms=None, max_window_ms=None):
    """Помилки меж людською мовою. Порожній список = усе гаразд."""
    errs = []
    if from_ms is None or to_ms is None:
        return ["Both bounds are required: From and To."]
    if from_ms >= to_ms:
        errs.append("From must be earlier than To.")
    if max_window_ms and to_ms - from_ms > max_window_ms:
        errs.append(f"The entry range is longer than {max_window_ms // HOUR} hours — narrow it.")
    if created_ms and from_ms < created_ms - HOUR:
        errs.append("From is before the token was created — there are no trades there.")
    if now_ms and to_ms > now_ms:
        errs.append("To is in the future.")
    return errs
