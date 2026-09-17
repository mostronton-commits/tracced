"""Авто-детект пампов и их фаз накопления по графику (mcap во времени).

Идея: памп = пик, поднявшийся в ≥pump_multiple раз от «базы» (локального минимума
за lookback). Старт пампа (конец фазы накопления) = момент ОТРЫВА от базы
(цена ушла выше база*breakout_ratio) — не точка «уже ×2», а начало движения.
Фаза накопления = [время базового минимума … старт пампа].
Значимость: оставляем только пампы с пиком ≥ min_peak_mcap (отсев мелочи).
"""


def detect_pumps(series, supply, cfg):
    d = cfg["detect"]
    mult = d["pump_multiple"]
    W = d["lookback"]
    breakout = d["breakout_ratio"]
    min_peak = d["min_peak_mcap"]
    merge_gap_ms = d.get("merge_gap_min", 60) * 60 * 1000

    S = [(t, close * supply) for t, close, _ in series if close and supply]
    n = len(S)
    pumps = []
    i = W
    while i < n:
        window = S[max(0, i - W):i]
        base_t, base = min(window, key=lambda x: x[1])
        if base > 0 and S[i][1] >= base * mult:
            bo_t = S[i][0]                       # старт пампа = отрыв от базы
            for t, m in S:
                if t > base_t and m >= base * breakout:
                    bo_t = t
                    break
            fwd = S[i:i + W] or [S[i]]
            peak = max(m for _, m in fwd)
            pumps.append({
                "acc_start": base_t,
                "pump_start": bo_t,
                "base_mcap": base,
                "peak_mcap": peak,
                "magnitude": round(peak / base, 1) if base else None,
            })
            i += W                                # проскочить этот памп
            continue
        i += 1

    pumps = [p for p in pumps if p["peak_mcap"] >= min_peak]     # значимость
    merged = []                                                  # слить близкие
    for p in sorted(pumps, key=lambda x: x["pump_start"]):
        if merged and p["pump_start"] - merged[-1]["pump_start"] <= merge_gap_ms:
            if p["peak_mcap"] > merged[-1]["peak_mcap"]:
                merged[-1] = p
        else:
            merged.append(p)
    return merged
