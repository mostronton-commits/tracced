"""Дашборд власника: хто з підключених гаманців що робить на сайті і скільки кредитів це коштує.

Сировина — журнал подій (accounts.EventLog, output/early/usage/YYYY-MM.jsonl), акаунти і результати аналізів. Тут лише
чиста логіка, без aiohttp і без мережі: її можна тестувати на вигаданих подіях.
"""
import datetime
import json
import math
import os
import re
import zoneinfo
from urllib.parse import parse_qs, urlsplit

HOUR = 3_600_000

# Кліки, які сторінка шле в журнал (EarlyUI.use), і які властивості в них можна. Усе інше відкидається: назва не з
# цього списку, властивість не з її рядка, значення не з VAL.
UI = {
    "card-open": ("src",), "card-close": (), "card-period": ("p",), "pin": ("on",),
    "filter": ("k",), "hide": ("tag", "on"), "filters-reset": (), "filters-toggle": ("on",), "funder": ("on",),
    "sort": ("key", "dir", "via"), "select": ("count",), "select-all": ("on",), "select-clear": (),
    "export": ("format", "sel", "filtered", "where"), "agent-open": (), "agent-close": (),
    "show-more": ("all",), "find-pump": (), "limit-window": ("kind",),
    "range-set": ("end",), "range-add": (), "range-reset": (), "tf": ("tf",), "chart-nav": ("to",),
    "list-tab": (), "copy": ("what",), "ext": ("to",), "cur": ("to",), "tz": ("to",), "leave": ("secs",),
    "egg": ("what",),
}
# короткий рядок: адреса гаманця (32-44 символи) чи набраний людиною текст сюди не пролазять фізично
VAL = re.compile(r"^[A-Za-z0-9_.:-]{1,24}$")
JOB_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
SLUG_RE = re.compile(r"^[a-z0-9-]{1,40}$")
LAG_MAX_MS = 600_000


def _val(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and math.isfinite(v):
        v = max(-1e9, min(1e9, v))
        return int(v) if isinstance(v, int) or v == int(v) else round(v, 2)
    if isinstance(v, str) and VAL.match(v):
        return v
    return None


def clean_batch(body, now_ms, max_events=30):
    """Пачка кліків зі сторінки → [{name, p, ts}], лише те, що пройшло білий список. Годиннику браузера не віримо:
    час кліку — «зараз» мінус те, наскільки він старший за найновіший у пачці (не більше 10 хвилин)."""
    items = body.get("e") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    rows = []
    for it in items[:max_events]:
        if not (isinstance(it, list) and len(it) == 3) or it[0] not in UI or not isinstance(it[1], dict):
            continue
        name, props, t = it
        p = {k: _val(props[k]) for k in UI[name] if k in props}
        rows.append((name, {k: v for k, v in p.items() if v is not None},
                     t if isinstance(t, (int, float)) and not isinstance(t, bool) and math.isfinite(t) else None))
    newest = max((t for _, _, t in rows if t is not None), default=None)
    return [{"name": name, "p": p,
             "ts": int(now_ms - (min(max(newest - t, 0), LAG_MAX_MS) if newest is not None and t is not None else 0))}
            for name, p, t in rows]


def page_of(referer, host):
    """Де клікали — зі шляху Referer цього ж сайту: (сторінка, про що вона). Чужий сайт чи /admin — None."""
    try:
        u = urlsplit(referer or "")
    except ValueError:
        return None
    if not u.netloc or u.netloc != host:
        return None
    path = u.path.rstrip("/") or "/"
    if path == "/admin" or path.startswith("/admin/"):
        return None                                     # власник, що дивиться дашборд, — не користувач продукту
    if path == "/":
        return "home", None
    if path.startswith("/job/"):
        jid = path[5:].split("/")[0]
        return "job", jid if JOB_RE.match(jid) else None
    if path == "/token":
        mint = (parse_qs(u.query).get("mint") or [""])[0]
        return "token", mint if MINT_RE.match(mint) else None
    if path == "/me":
        return "me", None
    if path == "/feedback":
        return "feedback", None
    if path == "/docs" or path.startswith("/docs/"):
        slug = path[6:] or "index"
        return "docs", slug if SLUG_RE.match(slug) else None
    return "other", None


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
    return {"job": job.id, "mint": job.mint, "symbol": job.symbol, "ok": 1 if ok else 0, "t_from": job.t_from, "t_to": job.t_to,
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


# ───────────────────────── підрахунки дашборда ─────────────────────────

PERIODS = {"today": 1, "7d": 7, "30d": 30, "all": None}
SESSION_GAP = 30 * 60_000                # пауза, після якої починається новий візит
DAY_MS = 86_400_000
PK_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
NOT_ACTIVITY = {"run"}                   # прогін закінчується без людини: активність — це її `analyze`
CARD_SPEND = {"card-profile", "card-trades", "card-age"}

# на що пішли кредити: підписи для таблиці витрат
FEATURES = {"run": "Analyses", "names": "Wallet names", "enrich": "Wallet age and funders (background)",
            "overview": "Token overviews", "chart": "Chart candles", "card-profile": "Card: last 30 days",
            "card-trades": "Card: trades on the token", "card-age": "Card: age and funder", "demo": "Demo capture",
            "credits": "Balance checks", "onchain": "This dashboard: on-chain facts", "agent": "AI agent"}
WHO = {"wallets": "Wallet users", "team": "You and test wallets", "guests": "Guests", "system": "The server"}
# кліки людською мовою: таблиця «що клікають» і хронологія гаманця
CLICKS = {"card-open": "Opened a wallet card", "card-close": "Closed a wallet card", "card-period": "Switched 7D/30D in a card",
          "pin": "Pinned a wallet to the chart", "filter": "Changed a filter", "hide": "Hid a tag", "filters-reset": "Reset the filters",
          "filters-toggle": "Opened or closed the filters", "funder": "Filtered by a funder", "sort": "Sorted the table",
          "select": "Ticked wallets", "select-all": "Ticked all", "select-clear": "Cleared the selection", "export": "Exported",
          "agent-open": "Opened the agent", "agent-close": "Closed the agent", "show-more": "Showed more rows",
          "find-pump": "Pressed Find the pump", "limit-window": "Saw the daily limit window", "range-set": "Marked a range on the chart",
          "range-add": "Added a range", "range-reset": "Reset the ranges", "tf": "Changed the timeframe", "chart-nav": "Jumped on the chart",
          "list-tab": "Switched a list", "copy": "Copied an address", "ext": "Followed a link out", "cur": "Switched USD/SOL",
          "tz": "Switched UTC/local", "leave": "Left a page", "egg": "Found an easter egg"}
FUNNEL = (("result", "Opened a result"), ("card", "Opened a wallet card"), ("run", "Ran an analysis"),
          ("keep", "Saved or exported"), ("agent", "Asked the agent"))
LIMITS = {"run": "Live analyses", "browse": "Charts of new tokens", "age-card": "Age checks from cards",
          "agent-ask": "Questions to the agent", "agent-cards": "Agent cards"}
LIMIT_KINDS = {"wallet": "per wallet", "site": "whole site", "network": "per network", "token": "per token",
               "hourly": "per hour from one address", "month": "month budget"}
RANGE_BUCKETS = ((5, "≤ 5 min"), (15, "5–15 min"), (60, "15–60 min"), (360, "1–6 h"), (None, "> 6 h"))
AGE_BUCKETS = ((1, "< 1 h"), (6, "1–6 h"), (24, "6–24 h"), (168, "1–7 d"), (None, "> 7 d"))
AFTER_BUCKETS = ((1, "< 1 h"), (6, "1–6 h"), (24, "6–24 h"), (72, "1–3 d"), (None, "> 3 d"))
MCAP_BUCKETS = ((100_000, "< $100K"), (1_000_000, "$100K–1M"), (10_000_000, "$1M–10M"), (None, "> $10M"))
SOL_BUCKETS = ((0.1, "< 0.1"), (1, "0.1–1"), (10, "1–10"), (100, "10–100"), (None, "> 100"))


def who_of(pk, team):
    """Хто це з погляду дашборда: гаманець-користувач, команда (власник і позначені тестові), гість чи сам сервер."""
    if pk == "guest":
        return "guests"
    if not isinstance(pk, str) or not PK_RE.match(pk):
        return "system"
    return "team" if pk in team else "wallets"


def _day(ms, tz):
    return datetime.datetime.fromtimestamp(ms / 1000, tz).date()


def _day_start(day, tz):
    return int(datetime.datetime.combine(day, datetime.time(), tzinfo=tz).timestamp() * 1000)


def period_start(now_ms, period, tz):
    """Початок періоду: північ першого з N календарних днів (сьогодні — перший із «7 d»); «all» — 0."""
    n = PERIODS.get(period, 7)
    if n is None:
        return 0
    return _day_start(_day(now_ms, tz) - datetime.timedelta(days=n - 1), tz)


def load_since(now_ms, period, tz):
    """З якого моменту читати журнал: період, 30 днів для графіка і MAU, і початок місяця для витрат місяця."""
    if PERIODS.get(period, 7) is None:
        return 0
    month = int(datetime.datetime.fromtimestamp(now_ms / 1000, datetime.timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    return min(period_start(now_ms, period, tz), period_start(now_ms, "30d", tz), month)


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _stats(xs):
    xs = [x for x in xs if x is not None]
    return {"n": len(xs), "avg": sum(xs) / len(xs) if xs else None, "median": _median(xs), "max": max(xs) if xs else None}


def _bucket(v, buckets):
    for hi, label in buckets:
        if hi is None or v < hi:
            return label
    return buckets[-1][1]


def _count(values, buckets):
    out = {label: 0 for _, label in buckets}
    for v in values:
        if v is not None:
            out[_bucket(v, buckets)] += 1
    return [{"label": k, "n": n} for k, n in out.items()]


def job_run(job):
    """Рядок `run` для аналізу, зробленого до журналу: з файлу результату (запити — ті, що записав сам прогін)."""
    f = run_facts(job)
    if f["st"] is None:
        f["st"] = (job.result or {}).get("requests")
    return dict({k: v for k, v in f.items() if v is not None}, ts_ms=job.finished_ms or job.created_ms or 0,
                pubkey=job.owner or "system", event="run", backfill=1)


def with_backfill(events, jobs):
    """Журнал + прогони з файлів результатів, закінчені до першого рядка `run` (раніше журнал прогонів не писав)."""
    first = min((e["ts_ms"] for e in events if e.get("event") == "run"), default=None)
    old = [job_run(j) for j in jobs if not getattr(j, "replay", None) and j.status in ("done", "error")
           and (j.finished_ms or j.created_ms) and (first is None or (j.finished_ms or j.created_ms) < first)]
    return sorted(events + old, key=lambda e: e["ts_ms"]) if old else events


def _sessions(times):
    """Візити одного гаманця: [(початок, кінець, подій)] — новий візит після паузи понад 30 хвилин."""
    out = []
    for t in sorted(times):
        if out and t - out[-1][1] <= SESSION_GAP:
            out[-1] = (out[-1][0], t, out[-1][2] + 1)
        else:
            out.append((t, t, 1))
    return out


def _run_costs(events):
    """Кредити кожного прогону: сам прогін, імена, збагачення і картки гаманців цього аналізу, доки його не
    перезапустили. {id рядка run: {"st_run", "st_names", "st_cards", "rpc_enrich", "rpc_cards"}}."""
    runs_by_job, out = {}, {}
    for e in events:
        if e.get("event") == "run" and e.get("job"):
            runs_by_job.setdefault(e["job"], []).append(e)
            out[id(e)] = {"st_run": e.get("st"), "st_names": 0, "st_cards": 0, "rpc_enrich": 0, "rpc_cards": 0}
    for e in events:
        if e.get("event") != "spend" or not e.get("job") or e["job"] not in runs_by_job:
            continue
        owner = None
        for r in runs_by_job[e["job"]]:                  # останній прогін цього аналізу до витрати
            if r["ts_ms"] <= e["ts_ms"]:
                owner = r
        if owner is None:
            continue
        c, what = out[id(owner)], e.get("what")
        if what == "names":
            c["st_names"] += e.get("st") or 0
        elif what == "enrich":
            c["rpc_enrich"] += e.get("rpc") or 0
        elif what in CARD_SPEND:
            c["st_cards"] += e.get("st") or 0
            c["rpc_cards"] += e.get("rpc") or 0
    return out


def _ai_usd(e):
    return float(e.get("ai_usd") or 0)


def summarize(events, *, accounts, jobs=(), onchain=None, now_ms, period="7d", tz=datetime.timezone.utc,
              team=frozenset(), include_team=False, budgets=None):
    """Усе, що показує дашборд власника, одним словником. `events` — журнал з load_since(), за часом; `accounts` —
    AccountStore.all(); `jobs` — аналізи в пам'яті (для прогонів, зроблених до журналу); `onchain` — onchain.json;
    `team` — гаманці власника і позначені тестовими. Витрати — по всіх, поведінка — лише гаманців-користувачів
    (з командою, коли `include_team`)."""
    onchain = onchain or {}
    team = frozenset(team)
    events = with_backfill(list(events), list(jobs))
    p0 = period_start(now_ms, period, tz)
    today, d30 = period_start(now_ms, "today", tz), period_start(now_ms, "30d", tz)
    wants = {"wallets", "team"} if include_team else {"wallets"}

    def person(pk):
        return who_of(pk, team) in wants

    acts = [e for e in events if person(e.get("pubkey")) and not e.get("bg") and e.get("event") not in NOT_ACTIVITY]
    in_p = [e for e in acts if e["ts_ms"] >= p0]
    active = {e["pubkey"] for e in in_p}
    by_pk = {}
    for e in in_p:
        by_pk.setdefault(e["pubkey"], []).append(e)

    # ── пульс і графік за 30 днів ──
    days = [_day(now_ms, tz) - datetime.timedelta(days=i) for i in range(29, -1, -1)]
    daily = {d: {"active": set(), "runs": 0, "failed": 0, "st": 0, "rpc": 0, "ai_usd": 0.0} for d in days}
    for e in events:
        if e["ts_ms"] < d30:
            continue
        slot = daily.get(_day(e["ts_ms"], tz))
        if slot is None:
            continue
        if person(e.get("pubkey")) and not e.get("bg") and e.get("event") not in NOT_ACTIVITY:
            slot["active"].add(e["pubkey"])
        if e.get("event") == "run" and person(e.get("pubkey")):
            slot["runs"] += 1
            slot["failed"] += 0 if e.get("ok") else 1
        slot["st"] += int(e.get("st") or 0) if e.get("event") in ("run", "spend") else 0
        slot["rpc"] += int(e.get("rpc") or 0) if e.get("event") == "spend" else 0
        slot["ai_usd"] += _ai_usd(e) if e.get("event") == "agent" else 0
    series = [{"day": d.isoformat(), "label": f"{d:%b} {d.day}", "active": len(v["active"]), "runs": v["runs"], "failed": v["failed"],
               "st": v["st"], "rpc": v["rpc"], "ai_usd": round(v["ai_usd"], 4)} for d, v in daily.items()]
    mau = len({e["pubkey"] for e in acts if e["ts_ms"] >= d30})
    wau = len({e["pubkey"] for e in acts if e["ts_ms"] >= period_start(now_ms, "7d", tz)})
    dau = len({e["pubkey"] for e in acts if e["ts_ms"] >= today})
    runs_p = [e for e in events if e.get("event") == "run" and e["ts_ms"] >= p0 and person(e.get("pubkey"))]
    runs_t = [e for e in runs_p if e["ts_ms"] >= today]
    spent = [e for e in events if e["ts_ms"] >= p0]
    spent_t = [e for e in spent if e["ts_ms"] >= today]

    def total(evs, key):
        if key == "ai_usd":
            return round(sum(_ai_usd(e) for e in evs if e.get("event") == "agent"), 4)
        kinds = ("run", "spend") if key == "st" else ("spend",)
        return sum(int(e.get(key) or 0) for e in evs if e.get("event") in kinds)
    accts = [a for a in accounts if person(a.get("pubkey"))]
    new = [a for a in accts if (a.get("created_ms") or 0) >= p0]
    pulse = {"dau": dau, "wau": wau, "mau": mau,
             "stickiness": (sum(s["active"] for s in series) / 30 / mau) if mau else None,
             "accounts": len(accts), "accounts_all": len(accounts), "new": len(new),
             "new_today": sum(1 for a in accts if (a.get("created_ms") or 0) >= today),
             "runs": len(runs_p), "runs_failed": sum(1 for e in runs_p if not e.get("ok")),
             "runs_today": len(runs_t), "runs_today_failed": sum(1 for e in runs_t if not e.get("ok")),
             "saved": sum(int(e.get("n") or 0) for e in in_p if e["event"] == "save_wallets"),
             "st": total(spent, "st"), "rpc": total(spent, "rpc"), "ai_usd": total(spent, "ai_usd"),
             "st_today": total(spent_t, "st"), "rpc_today": total(spent_t, "rpc"), "ai_usd_today": total(spent_t, "ai_usd")}

    # ── воронка, повернення, візити ──
    reached = {k: set() for k, _ in FUNNEL}
    for e in in_p:
        ev, pk = e["event"], e["pubkey"]
        if (ev == "view" and e.get("page") == "job" and e.get("state") == "done") or (ev == "ui" and e.get("page") == "job"):
            reached["result"].add(pk)
        if (ev == "ui" and e.get("name") == "card-open") or (ev == "spend" and e.get("what") in CARD_SPEND):
            reached["card"].add(pk)
        if ev == "analyze":
            reached["run"].add(pk)
        if ev in ("save_wallets", "save_analysis", "export") or (ev == "ui" and e.get("name") == "export"):
            reached["keep"].add(pk)
        if ev == "agent" and e.get("kind") == "ask" and e.get("ok"):
            reached["agent"].add(pk)
    funnel = [{"key": k, "label": label, "n": len(reached[k])} for k, label in FUNNEL]
    first_seen = min((e["ts_ms"] for e in events), default=now_ms)
    last_act = {}
    for e in acts:
        last_act[e["pubkey"]] = e["ts_ms"]                # події за часом: остання перемагає
    came_back = []
    for n in (1, 7, 30):
        # лише ті, чий перший вхід журнал бачив і кому вже є N днів: чи був хтось із них тут на N-й день або пізніше
        cohort = [a for a in accts if first_seen <= (a.get("created_ms") or 0) <= now_ms - n * DAY_MS]
        back = sum(1 for a in cohort if last_act.get(a["pubkey"], 0) >= a["created_ms"] + n * DAY_MS)
        came_back.append({"days": n, "n": back, "of": len(cohort)})
    first_run = {}
    for e in acts:
        if e["event"] == "analyze":
            first_run.setdefault(e["pubkey"], e["ts_ms"])
    first_card = {}
    for e in acts:
        if (e["event"] == "ui" and e.get("name") == "card-open") or (e["event"] == "spend" and e.get("what") in CARD_SPEND):
            first_card.setdefault(e["pubkey"], e["ts_ms"])
    activated = [a for a in new if min(first_run.get(a["pubkey"], 1e18), first_card.get(a["pubkey"], 1e18)) <= (a.get("created_ms") or 0) + 7 * DAY_MS]
    ttfa = [(first_run[a["pubkey"]] - a["created_ms"]) / HOUR for a in accts
            if a["pubkey"] in first_run and (a.get("created_ms") or 0) >= first_seen and first_run[a["pubkey"]] >= a["created_ms"]]
    sess = {pk: _sessions([e["ts_ms"] for e in evs]) for pk, evs in by_pk.items()}
    all_sess = [s for v in sess.values() for s in v]
    sessions = {"n": len(all_sess), "per_wallet": len(all_sess) / len(active) if active else None,
                "median_min": _median([(b - a) / 60_000 for a, b, _ in all_sess]), "median_events": _median([k for _, _, k in all_sess])}
    returning = sum(1 for pk, evs in by_pk.items() if len({_day(e["ts_ms"], tz) for e in evs}) >= 2)

    # ── аналізи і кредити кожного ──
    costs_of = _run_costs(events)
    runs = []
    for e in sorted(runs_p, key=lambda e: -e["ts_ms"]):
        c = costs_of.get(id(e), {})
        st_total = None if c.get("st_run") is None else c["st_run"] + c["st_names"] + c["st_cards"]
        runs.append({"ts_ms": e["ts_ms"], "pubkey": e["pubkey"], "who": who_of(e["pubkey"], team), "job": e.get("job"),
                     "t_from": e.get("t_from"), "t_to": e.get("t_to"), "range_min": e.get("range_min"),
                     "mint": e.get("mint"), "symbol": e.get("symbol"), "ok": bool(e.get("ok")), "err": e.get("err"),
                     "rows": e.get("rows"), "secs": e.get("secs"), "backfill": bool(e.get("backfill")), **c,
                     "st_total": st_total, "rpc_total": c.get("rpc_enrich", 0) + c.get("rpc_cards", 0)})
    run_stats = {"st": _stats([r["st_total"] for r in runs]), "rpc": _stats([r["rpc_total"] for r in runs if not r["backfill"]]),
                 "secs": _stats([r["secs"] for r in runs]), "rows": _stats([r["rows"] for r in runs if r["ok"]])}
    fails = {}
    for r in runs:
        if not r["ok"]:
            k = (r["err"] or "unknown")[:90]
            fails[k] = fails.get(k, 0) + 1

    # ── витрати: усі, хто платив ──
    feat, by_who, month = {}, {k: {"st": 0, "rpc": 0, "ai_usd": 0.0} for k in WHO}, {"st": 0, "rpc": 0, "ai_usd": 0.0}
    m0 = int(datetime.datetime.fromtimestamp(now_ms / 1000, datetime.timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    for e in events:
        ev = e.get("event")
        if ev not in ("run", "spend", "agent"):
            continue
        key = "agent" if ev == "agent" else ("run" if ev == "run" else e.get("what") or "other")
        st, rpc, usd = (int(e.get("st") or 0) if ev in ("run", "spend") else 0), (int(e.get("rpc") or 0) if ev == "spend" else 0), \
            (_ai_usd(e) if ev == "agent" else 0.0)
        if e["ts_ms"] >= m0:
            month["st"] += st
            month["rpc"] += rpc
            month["ai_usd"] += usd
        if e["ts_ms"] < p0:
            continue
        f = feat.setdefault(key, {"what": key, "label": FEATURES.get(key, key), "st": 0, "rpc": 0, "ai_usd": 0.0, "times": 0})
        f["st"] += st
        f["rpc"] += rpc
        f["ai_usd"] += usd
        f["times"] += 1
        w = by_who[who_of(e.get("pubkey"), team)]
        w["st"] += st
        w["rpc"] += rpc
        w["ai_usd"] += usd
    for x in list(feat.values()) + list(by_who.values()) + [month]:
        x["ai_usd"] = round(x["ai_usd"], 4)
    b = budgets or {}
    rpc_month = (b.get("rpc") or {}).get("spent")
    costs = {"by_feature": sorted(feat.values(), key=lambda f: (-f["st"], -f["rpc"], -f["ai_usd"])),
             "by_who": [dict(v, who=k, label=WHO[k]) for k, v in by_who.items()],
             "month": dict(month, month=datetime.datetime.fromtimestamp(now_ms / 1000, datetime.timezone.utc).strftime("%Y-%m"),
                           rpc_unlogged=max(0, rpc_month - month["rpc"]) if rpc_month is not None else None)}

    # ── агент ──
    ag = [e for e in in_p if e["event"] == "agent" and e.get("kind") in ("cards", "ask")]
    asks = [e for e in ag if e["kind"] == "ask"]
    fresh = [e for e in ag if e["kind"] == "cards" and e.get("ok") and not e.get("cached")]
    chips = {}
    for e in asks:
        if isinstance(e.get("chip"), str):
            chips[e["chip"]] = chips.get(e["chip"], 0) + 1
    ai = {"wallets": len({e["pubkey"] for e in ag}), "of": len(active),
          "opens": sum(1 for e in in_p if e["event"] == "ui" and e.get("name") == "agent-open"),
          "cards_fresh": len(fresh), "cards_ready": sum(1 for e in ag if e["kind"] == "cards" and e.get("cached")),
          "asks": len(asks), "asks_chip": sum(1 for e in asks if e.get("chip") is not None),
          "off": sum(1 for e in asks if e.get("off")), "dropped": sum(int(e.get("dropped") or 0) for e in ag),
          "errors": sum(1 for e in ag if not e.get("ok")),
          "ms_median": _median([e.get("ms") for e in ag if e.get("ok") and not e.get("cached")]),
          "ai_in": sum(int(e.get("ai_in") or 0) for e in ag), "ai_out": sum(int(e.get("ai_out") or 0) for e in ag),
          "usd": round(sum(_ai_usd(e) for e in ag), 4),
          "usd_per_ask": (sum(_ai_usd(e) for e in asks) / len(asks)) if asks else None,
          "usd_per_cards": (sum(_ai_usd(e) for e in fresh) / len(fresh)) if fresh else None,
          "chips": sorted(({"q": q, "n": n} for q, n in chips.items()), key=lambda c: -c["n"])}

    # ── гаманці ──
    paid = {}
    for e in events:
        if e["ts_ms"] < p0 or e.get("event") not in ("run", "spend", "agent"):
            continue
        x = paid.setdefault(e.get("pubkey"), {"st": 0, "rpc": 0, "ai_usd": 0.0})
        x["st"] += int(e.get("st") or 0) if e["event"] in ("run", "spend") else 0
        x["rpc"] += int(e.get("rpc") or 0) if e["event"] == "spend" else 0
        x["ai_usd"] += _ai_usd(e) if e["event"] == "agent" else 0.0
    users = []
    for a in accts:
        pk, evs = a["pubkey"], by_pk.get(a["pubkey"], [])
        devs = [e.get("dev") for e in evs if e["event"] == "view" and e.get("dev")]
        x = paid.get(pk, {})
        users.append({"pubkey": pk, "who": who_of(pk, team), "app": a.get("wallet_app"), "first_ms": a.get("created_ms"),
                      "last_ms": last_act.get(pk) or a.get("last_seen_ms"),   # останній крок; поза журналом — останній запис акаунта
                      "dev": max(set(devs), key=devs.count) if devs else None,
                      "days": len({_day(e["ts_ms"], tz) for e in evs}), "sessions": len(sess.get(pk, [])),
                      "runs": sum(1 for e in evs if e["event"] == "analyze"),
                      "cards": sum(1 for e in evs if e["event"] == "ui" and e.get("name") == "card-open")
                      or sum(1 for e in evs if e["event"] == "spend" and e.get("what") in CARD_SPEND),
                      "asks": sum(1 for e in evs if e["event"] == "agent" and e.get("kind") == "ask"),
                      "saves": sum(1 for e in evs if e["event"] in ("save_wallets", "save_analysis")),
                      "exports": sum(1 for e in evs if e["event"] == "export" or (e["event"] == "ui" and e.get("name") == "export")),
                      "st": x.get("st", 0), "rpc": x.get("rpc", 0), "ai_usd": round(x.get("ai_usd", 0.0), 4),
                      "onchain": onchain.get(pk) or {}})
    users.sort(key=lambda u: -(u["last_ms"] or 0))

    # ── кліки, токени, ліміти, on-chain ──
    feats = {}
    for e in in_p:
        if e["event"] != "ui" or e.get("name") == "leave":     # вихід зі сторінки — не натискання, він лише закриває візит
            continue
        k = (e.get("name"), e.get("page"))
        f = feats.setdefault(k, {"name": k[0], "label": CLICKS.get(k[0], k[0]), "page": k[1], "times": 0, "wallets": set()})
        f["times"] += 1
        f["wallets"].add(e["pubkey"])
    features = sorted(({**f, "wallets": len(f["wallets"])} for f in feats.values()), key=lambda f: (-f["wallets"], -f["times"]))
    viewers = {}
    for e in in_p:
        if e["event"] == "view" and e.get("page") == "token" and e.get("ref"):
            viewers.setdefault(e["ref"], set()).add(e["pubkey"])
    top = {}
    for e in runs_p:
        t = top.setdefault(e.get("mint"), {"mint": e.get("mint"), "symbol": e.get("symbol"), "runs": 0, "by": set()})
        t["runs"] += 1
        t["by"].add(e["pubkey"])
    for m, vs in viewers.items():
        top.setdefault(m, {"mint": m, "symbol": None, "runs": 0, "by": set()})
    tokens = {"top": sorted(({"mint": t["mint"], "symbol": t["symbol"], "runs": t["runs"], "runners": len(t["by"]),
                              "viewers": len(viewers.get(t["mint"], ()))} for t in top.values()),
                            key=lambda t: (-t["runs"], -t["viewers"]))[:15],
              "age": _count([e.get("age_h") for e in runs_p], AGE_BUCKETS),
              "after": _count([e.get("after_h") for e in runs_p], AFTER_BUCKETS),
              "mcap": _count([e.get("mcap") for e in runs_p], MCAP_BUCKETS),
              "range": _count([e.get("range_min") for e in runs_p], RANGE_BUCKETS)}
    pads = {}
    for e in runs_p:
        if e.get("pad"):
            pads[e["pad"]] = pads.get(e["pad"], 0) + 1
    tokens["pads"] = sorted(({"pad": k, "n": n} for k, n in pads.items()), key=lambda x: -x["n"])
    lim = {}
    for e in in_p:
        if e["event"] == "limit":
            x = lim.setdefault((e.get("what"), e.get("kind")), {"what": e.get("what"), "kind": e.get("kind"), "times": 0, "wallets": set(),
                                                                 "label": LIMITS.get(e.get("what"), e.get("what")),
                                                                 "whose": LIMIT_KINDS.get(e.get("kind"), e.get("kind"))})
            x["times"] += 1
            x["wallets"].add(e["pubkey"])
    limits = sorted(({**x, "wallets": len(x["wallets"])} for x in lim.values()), key=lambda x: -x["times"])
    errs = {}
    for e in in_p:
        if e["event"] == "error":
            x = errs.setdefault((e.get("where"), e.get("status"), e.get("msg")), {"where": e.get("where"), "status": e.get("status"),
                                                                              "msg": e.get("msg"), "times": 0, "wallets": set()})
            x["times"] += 1
            x["wallets"].add(e["pubkey"])
    errors = sorted(({**x, "wallets": len(x["wallets"])} for x in errs.values()), key=lambda x: -x["times"])
    phone = {e["pubkey"] for e in in_p if e["event"] == "view" and e.get("dev") == "m"}
    computer = {e["pubkey"] for e in in_p if e["event"] == "view" and e.get("dev") == "d"}
    oc = [onchain[a["pubkey"]] for a in accts if onchain.get(a["pubkey"])]
    idn = [o.get("idn") or {} for o in oc]
    p30 = [o.get("p30") or {} for o in oc]
    onchain_sum = {"n": len(oc), "known": sum(1 for i in idn if i), "kol": sum(1 for i in idn if i.get("type") == "kol" or "kol" in (i.get("tags") or [])),
                   "x": sum(1 for i in idn if i.get("twitter")),
                   "age_median_d": _median([(now_ms - o["age_ms"]) / DAY_MS for o in oc if o.get("age_ms")]),
                   "sol": _count([o.get("sol") for o in oc], SOL_BUCKETS),
                   "trades_median": _median([p.get("swaps") for p in p30 if p]),
                   "in_profit": sum(1 for p in p30 if (p.get("pnl_usd") or 0) > 0), "with_p30": sum(1 for p in p30 if p),
                   "winrate_median": _median([p.get("win_rate") for p in p30 if (p.get("closed") or 0) >= 3])}
    return {"period": period if period in PERIODS else "7d", "since_ms": p0, "now_ms": now_ms, "include_team": include_team,
            "tracked_since": min((e["ts_ms"] for e in events if not e.get("backfill")), default=None),
            "pulse": pulse, "daily": series, "funnel": funnel, "funnel_base": len(active), "returning": returning,
            "sessions": sessions, "came_back": came_back, "activation": {"n": len(activated), "of": len(new)},
            "ttfa_median_h": _median(ttfa), "runs": runs[:100], "runs_n": len(runs), "run_stats": run_stats, "costs": costs,
            "ai": ai, "users": users, "features": features, "tokens": tokens, "limits": limits, "onchain": onchain_sum,
            "errors": errors, "fails": sorted(({"err": k, "n": n} for k, n in fails.items()), key=lambda x: -x["n"]),
            "devices": {"phone": len(phone), "computer": len(computer)},
            "questions": sum(1 for e in in_p if e["event"] == "agent" and e.get("kind") == "ask")}


# ───────────────────────── події людською мовою ─────────────────────────

PAGES = {"home": "the home page", "token": "a token", "job": "a result", "me": "their lists", "docs": "the docs",
         "feedback": "the Write to us form", "other": "a page"}
SPEND_OF = {"st": "Solana Tracker requests", "rpc": "Helius credits"}


def _plural(n, word):
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def label(e):
    """Подія одним рядком для власника: {"text", "href", "link"} — текст і, якщо є, посилання після нього."""
    ev, g = e.get("event"), e.get
    job = g("job")
    link = {"href": f"/job/{job}", "link": g("symbol") or (job or "")[:14]} if job else {}
    if ev == "signin":
        return {"text": "signed in" + (f" · {g('wallet')}" if g("wallet") else "")}
    if ev == "signout":
        return {"text": "signed out"}
    if ev == "save_wallets":
        return {"text": f"saved {_plural(int(g('n') or 0), 'wallet')} from", **link}
    if ev == "save_analysis":
        return {"text": "saved the analysis", **link}
    if ev == "remove_wallet":
        return {"text": f"removed {_plural(int(g('n') or 1), 'wallet')} from a list"}
    if ev == "remove_analysis":
        return {"text": "removed an analysis"}
    if ev == "analyze":
        return {"text": "ran an analysis:", **link}
    if ev == "delete_analysis":
        return {"text": f"deleted the analysis {g('symbol') or job or ''}".rstrip()}
    if ev in ("list_create", "list_rename", "list_remove"):
        return {"text": {"list_create": "made", "list_rename": "renamed", "list_remove": "deleted"}[ev] + " a list"}
    if ev == "tags":
        return {"text": f"tagged a wallet ({_plural(int(g('count') or 0), 'own tag')})"}
    if ev == "export":
        return {"text": f"exported {'a list' if g('what') == 'list' else 'the lists'} as CSV"}
    if ev == "set_demo":
        return {"text": "made the demo:", **link}
    if ev == "agent_method":
        return {"text": f"saved the agent's method v{g('v')}"}
    if ev == "assistant":                                  # старий журнал
        return {"text": "asked the agent", **link}
    if ev == "waitlist":
        return {"text": "joined the waitlist"}
    if ev == "feedback":
        return {"text": f"wrote to us: {g('kind') or 'message'}"}
    if ev == "agent":
        usd = f" · ${float(g('ai_usd')):.4f}" if g("ai_usd") else ""
        if not g("ok", 1):
            return {"text": f"the agent failed ({g('err') or 'error'}){usd}", **link}
        if g("kind") == "cards":
            return {"text": ("opened the agent (cards ready)" if g("cached") else "opened the agent: new cards" + usd) + " on", **link}
        if g("kind") == "preview":
            return {"text": "tried the agent's method on the demo" + usd}
        chip = g("chip")
        what = f"a suggested question «{chip}»" if isinstance(chip, str) else ("a suggested question" if chip else "their own question")
        return {"text": f"asked the agent {what}" + (" (off topic)" if g("off") else "") + usd + " on", **link}
    if ev == "view":
        page = g("page")
        if page == "job":
            return {"text": "opened a result" + (" (demo)" if g("demo") else "") + (" while it ran" if g("state") == "run" else ""),
                    **({"href": f"/job/{g('ref')}", "link": (g("ref") or "")[:14]} if g("ref") else {})}
        if page == "token":
            return {"text": "opened a token" + (" (demo)" if g("demo") else ""),
                    **({"href": f"/token?mint={g('ref')}", "link": (g("ref") or "")[:6] + "…"} if g("ref") else {})}
        if page == "docs":
            return {"text": f"read the docs: {g('ref') or 'index'}"}
        return {"text": f"opened {PAGES.get(page, 'a page')}"}
    if ev == "ui":
        name, extra = g("name"), []
        for k in ("key", "dir", "k", "tag", "format", "tf", "to", "src", "what", "p", "end", "kind"):
            if isinstance(g(k), str):
                extra.append(g(k))
        if g("on") is False:
            extra.append("off")
        return {"text": CLICKS.get(name, name or "clicked") + (f" · {' '.join(extra)}" if extra else "")}
    if ev == "run":
        if not g("ok"):
            return {"text": "the analysis failed" + (f": {g('err')}" if g("err") else ""), **link}
        bits = [_plural(int(g("rows") or 0), "wallet")]
        if g("secs") is not None:
            bits.append(f"{g('secs'):.0f} s")
        if g("st") is not None:
            bits.append(_plural(int(g("st")), "request"))
        return {"text": "the analysis finished (" + ", ".join(bits) + "):", **link}
    if ev == "spend":
        cost = ", ".join(f"{int(g(k)):,} {v}" for k, v in SPEND_OF.items() if g(k))
        return {"text": f"{FEATURES.get(g('what'), g('what'))}: {cost}", **link}
    if ev == "limit":
        return {"text": f"hit the daily limit: {g('what')} ({g('kind')})"}
    if ev == "error":
        return {"text": f"saw an error on {g('where') or 'a page'} ({g('status')}): {g('msg') or ''}".rstrip(": ")}
    return {"text": str(ev)}


def wallet_detail(events, pk, *, account=None, jobs=(), onchain=None, agent_log=(), now_ms, tz=datetime.timezone.utc,
                  team=frozenset()):
    """Один гаманець для власника: хто він, що робив день за днем, його аналізи з кредитами і питання агенту."""
    events = with_backfill(list(events), [j for j in jobs if getattr(j, "owner", None) == pk])
    mine = [e for e in events if e.get("pubkey") == pk]
    costs_of = _run_costs(events)
    acts = [e for e in mine if not e.get("bg") and e.get("event") not in NOT_ACTIVITY]
    runs = []
    for e in reversed([e for e in mine if e.get("event") == "run"]):
        c = costs_of.get(id(e), {})
        runs.append({"ts_ms": e["ts_ms"], "job": e.get("job"), "mint": e.get("mint"), "symbol": e.get("symbol"), "ok": bool(e.get("ok")),
                     "err": e.get("err"), "rows": e.get("rows"), "secs": e.get("secs"), "backfill": bool(e.get("backfill")), **c,
                     "st_total": None if c.get("st_run") is None else c["st_run"] + c["st_names"] + c["st_cards"],
                     "rpc_total": c.get("rpc_enrich", 0) + c.get("rpc_cards", 0)})
    totals = {"st": sum(int(e.get("st") or 0) for e in mine if e.get("event") in ("run", "spend")),
              "rpc": sum(int(e.get("rpc") or 0) for e in mine if e.get("event") == "spend"),
              "ai_usd": round(sum(_ai_usd(e) for e in mine if e.get("event") == "agent"), 4),
              "runs": sum(1 for e in mine if e.get("event") == "analyze"),
              "cards": sum(1 for e in mine if e.get("event") == "ui" and e.get("name") == "card-open"),
              "asks": sum(1 for e in mine if e.get("event") == "agent" and e.get("kind") == "ask"),
              "views": sum(1 for e in mine if e.get("event") == "view"),
              "sessions": len(_sessions([e["ts_ms"] for e in acts])), "days": len({_day(e["ts_ms"], tz) for e in acts})}
    since = now_ms - 30 * DAY_MS
    days = {}
    for e in reversed([e for e in mine if e["ts_ms"] >= since and not e.get("bg")]):   # фонові витрати — у таблиці аналізів
        d = _day(e["ts_ms"], tz)
        items = days.setdefault(d, [])
        lb = label(e)
        if items and items[-1]["text"] == lb["text"] and items[-1].get("href") == lb.get("href"):
            items[-1]["n"] += 1                                # те саме підряд: «sorted the table ×5»
            continue
        items.append(dict(lb, ts_ms=e["ts_ms"], n=1, event=e.get("event")))
    timeline = [{"day": f"{d:%a} {d:%b} {d.day}", "steps": items} for d, items in days.items()]   # не "items": у шаблоні це метод словника
    agent = [e for e in agent_log if e.get("pk") == pk]
    return {"pubkey": pk, "who": who_of(pk, team), "account": account or {}, "onchain": (onchain or {}).get(pk) or {},
            "totals": totals, "runs": runs, "timeline": timeline, "agent": agent,
            "first_ms": (account or {}).get("created_ms"), "last_ms": max((e["ts_ms"] for e in acts), default=None)}


# ───────────────────────── файли дашборда ─────────────────────────

def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_exclude(path):
    """Гаманці, які власник позначив тестовими: у поведінку не йдуть (як і його власні)."""
    d = load_json(path, {}) or {}
    return {w for w in d.get("wallets") or [] if isinstance(w, str) and PK_RE.match(w)}


def save_exclude(path, wallets):
    save_json(path, {"wallets": sorted(wallets)})


# ───────────────────────── on-chain факти користувачів ─────────────────────────

ONCHAIN_GAP_MS = 20 * HOUR               # «раз на добу» з запасом: прохід кожні 6 годин не чіпає свіжий запис


def due_wallets(events, onchain, now_ms, gap_ms=ONCHAIN_GAP_MS, cap=100):
    """Кому оновити on-chain факти: гаманці з кроками в `events` (читають за останні дні), чий запис старший за gap_ms;
    найсвіжіші першими, не більше cap. Гості й сервер — не гаманці."""
    last = {}
    for e in events:
        pk = e.get("pubkey")
        if isinstance(pk, str) and PK_RE.match(pk) and not e.get("bg") and e.get("event") not in NOT_ACTIVITY:
            last[pk] = max(last.get(pk, 0), e.get("ts_ms") or 0)
    fresh = {w for w, rec in (onchain or {}).items() if (rec or {}).get("at", 0) > now_ms - gap_ms}
    return [w for w, _ in sorted(last.items(), key=lambda x: -x[1]) if w not in fresh][:cap]


def compact_profile(card):
    """З картки гаманця (profile.card, останні 30 днів) — те, що бачить дашборд."""
    if not isinstance(card, dict):
        return None
    r = lambda v, d=2: None if v is None else round(float(v), d)   # noqa: E731
    return {"pnl_usd": r(card.get("pnl_usd")), "win_rate": r(card.get("win_rate"), 3), "closed": card.get("closed"),
            "swaps": card.get("swaps"), "tokens": card.get("tokens"), "volume_usd": r(card.get("volume_usd")),
            "partial": bool(card.get("partial")), "at": card.get("computed_ms")}
