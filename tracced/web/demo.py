"""Демо-токен: знімок готового аналізу, який сторінка токена, графік і термінал програють без жодного запиту.

Знімок output/early/demo/<mint>.json самодостатній: факти токена, свічки всіх таймфреймів, діапазони, журнал і
результат кожного. Хто зараз демо, вирішує адмін кнопкою на сторінці результату; вибір лежить поруч у current.json і
сильніший за early.demo_job з config.yaml, тож заміна демо не потребує ні правки конфігу, ні входу на сервер.
"""
import json
import os
import time

TFS = ("1m", "5m", "15m", "1h")
HOUR = 3_600_000
# Solana Tracker віддає не більше 2000 свічок і мовчки губить найстаріші, а на грубих таймфреймах ще й обриває
# історію за кілька днів. Тож кожен таймфрейм гортаємо назад вікнами, на які він справді відповідає.
STEP_H = {"1m": 24, "5m": 48, "15m": 24 * 10, "1h": 24 * 45}
OVERRIDE = "current.json"


def read_override(demo_dir):
    try:
        with open(os.path.join(demo_dir, OVERRIDE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_override(demo_dir, job_id):
    os.makedirs(demo_dir, exist_ok=True)
    tmp = os.path.join(demo_dir, OVERRIDE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"demo_job": job_id, "example_job": job_id, "set_ms": int(time.time() * 1000)}, f)
    os.replace(tmp, os.path.join(demo_dir, OVERRIDE))


def capture(st, jobs, demo_dir, chart_fn=None, labels=None, span_hours=0, now_ms=None, log=print):
    """Готові аналізи одного токена (словники Job.to_dict()) → знімок демо. Повертає (шлях, id першого діапазону).

    chart_fn(st, mint, tf, a_ms, b_ms, info) — як тягнути свічки (з пулом кривої, як на живій сторінці)."""
    chart_fn = chart_fn or (lambda st_, m, tf, a, b, info: st_.chart(m, tf, a, b))
    ranges, info, created, mint = [], None, None, None
    for i, job in enumerate(jobs):
        if job.get("status") != "done" or not job.get("result"):
            raise ValueError(f"{job.get('id')} is {job.get('status')}: only finished analyses can be the demo")
        res = job["result"]
        if mint and res["info"]["mint"] != mint:
            raise ValueError("all analyses of a demo must be of the same token")
        info, mint = res["info"], res["info"]["mint"]
        created = info.get("created_time") or res["window"]["from"]
        label = (labels or {}).get(job["id"]) or f"Range {i + 1}"
        ranges.append({"label": label, "from": res["window"]["from"], "to": res["window"]["to"], "job": job["id"],
                       "log": list(job.get("log") or []), "result": res})
    ranges.sort(key=lambda r: r["from"])
    end = ranges[0]["from"] + int(span_hours * HOUR) if span_hours else int(now_ms or time.time() * 1000)
    candles, calls_total = {}, 0
    for tf in TFS:
        step, out, hi, calls = int(STEP_H[tf] * HOUR), [], end, 0
        while hi > created and calls < 30:
            lo = max(created, hi - step)
            out.extend(chart_fn(st, mint, tf, lo, hi, info))
            calls += 1
            hi = lo
        seen, merged = set(), []
        for c in sorted(out, key=lambda c: c["time"]):
            if c["time"] not in seen:
                seen.add(c["time"])
                merged.append(c)
        candles[tf] = merged
        calls_total += calls
        log(f"  {tf}: {len(merged)} candles ({calls} calls)")
    snap = {"mint": mint, "info": info, "created": created, "captured_ms": int(time.time() * 1000),
            "candles": candles, "hints": [], "ranges": ranges}
    os.makedirs(demo_dir, exist_ok=True)
    path = os.path.join(demo_dir, f"{mint}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False)
    os.replace(tmp, path)
    log(f"{path}  {os.path.getsize(path) / 1e6:.1f} MB · {len(ranges)} range(s) · {calls_total} chart requests")
    return path, ranges[0]["job"]
