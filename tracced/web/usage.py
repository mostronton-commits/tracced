"""Дашборд власника: хто з підключених гаманців що робить на сайті і скільки кредитів це коштує.

Сировина — журнал подій (accounts.EventLog, output/early/usage/YYYY-MM.jsonl), акаунти і результати аналізів. Тут лише
чиста логіка, без aiohttp і без мережі: її можна тестувати на вигаданих подіях.
"""
import datetime
import zoneinfo

HOUR = 3_600_000


def zone(name):
    """Часовий пояс доби дашборда; невідомий (чи образ без бази поясів) — UTC."""
    try:
        return zoneinfo.ZoneInfo(str(name or "UTC"))
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return datetime.timezone.utc


def _host(v):
    """Лаунчпад коротко: pump.fun, а не https://pump.fun/board."""
    v = str(v or "").strip().lower().split("://", 1)[-1].split("/", 1)[0]
    return (v[4:] if v.startswith("www.") else v)[:24] or None


def run_facts(job):
    """Що рядок журналу знає про закінчений прогін — з полів самого аналізу, без жодного запиту. Те саме рахується і
    для аналізів, зроблених до журналу (дашборд підтягує їх з файлів результатів)."""
    r = job.result or {}
    info = r.get("info") or {}
    t0, t1, created = job.t_from or 0, job.t_to or 0, info.get("created_time") or 0
    ok = job.status == "done" and bool(job.result)
    mcap = info.get("mcap")
    return {"job": job.id, "mint": job.mint, "symbol": job.symbol, "ok": 1 if ok else 0,
            "err": None if ok else (job.error or "")[:120] or None,
            "st": job.spent,                                  # None — невідомо (обірваний рестартом)
            "secs": round((job.finished_ms - job.started_ms) / 1000, 1) if job.finished_ms and job.started_ms else None,
            "wait_s": round((job.started_ms - job.created_ms) / 1000, 1) if job.started_ms and job.created_ms else None,
            "rows": len(r.get("rows") or []) if ok else None,
            "mode": r.get("mode"),
            "range_min": round((t1 - t0) / 60_000) if t1 > t0 else None,
            "age_h": round((t0 - created) / HOUR, 1) if created and t0 >= created else None,          # вік токена на початку пампу
            "after_h": round((job.created_ms - t1) / HOUR, 1) if job.created_ms and t1 and job.created_ms >= t1 else None,   # від пампу до аналізу
            "mcap": round(mcap) if isinstance(mcap, (int, float)) and mcap > 0 else None,
            "pad": _host(info.get("launchpad")),
            "best": round(float((r.get("summary") or {}).get("best_multiple") or 0), 2) or None}
