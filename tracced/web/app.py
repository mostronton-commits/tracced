"""Pages: / (paste a token) → /token (chart + pump windows) → /job/<id> (progress, table) → CSV.

Blocking Solana Tracker calls run in threads (asyncio.to_thread). The client is shared: at most
st_concurrency + 1 calls are in flight across the analysis and the pages, and every caller counts its own
calls through a meter carried in the context. No tracebacks in the browser: one plain sentence for the user,
details in the container log.
"""
import asyncio
import contextlib
import contextvars
import csv
import hashlib
import ipaddress
import os
import secrets
import io
import json
import logging
import math
import re
import threading
import time
from pathlib import Path

from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from ..cache import JsonCache
from ..config import DEFAULTS as CFG_DEFAULTS
from ..early import agent as agent_mod, assistant as assistant_mod, ledger, pipeline, profile, report, scope, tags, wallet_age as wallet_age_mod, window
from ..early.store import TradeStore
from ..providers import dexscreener
from . import accounts as acct_mod
from . import docs as docs_mod
from . import chart
from . import demo as demo_mod
from . import replay
from . import usage as usage_mod
from .agent_store import AgentStore
from .jobs import JobQueue, make_id, unnamed

log = logging.getLogger("early.web")
HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE.parent.parent / "docs"      # сторінки документації лежать у репозиторії поруч із кодом
HOUR = 3_600_000
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
MAX_CANDLES = 1500          # скільки свічок має сенс просити за раз: більше — і джерело мовчки обріже відповідь
ACCT_COOKIE = "early_acct"          # вхід гаманцем — єдиний вхід на сайті
DEVICE_COOKIE = "early_dev"         # випадкове число браузера для добової стелі аналізів; нічого іншого в ньому нема
DEVICE_DAYS = 365
ACCT_DAYS = 30

env = Environment(loader=FileSystemLoader(str(HERE / "templates")),
                  autoescape=select_autoescape(["html"]))


def _usd(v):
    s = chart.fmt_mcap(v)
    if s == "—":
        return s
    return "-$" + s[1:] if s.startswith("-") else "$" + s


def _num(v, digits=0):
    try:
        return f"{float(v):,.{digits}f}"
    except Exception:  # noqa: BLE001 — None, '', jinja Undefined
        return "—"


def _asset_version():
    """Short hash of the static assets' mtimes: appended as ?v= so browsers drop stale CSS/JS."""
    h = hashlib.sha1()
    for p in sorted((HERE / "static").rglob("*")):
        if p.is_file():
            h.update(f"{p.name}:{int(p.stat().st_mtime)}".encode())
    return h.hexdigest()[:8]


def _rows_rev():
    """Хеш коду, що рахує рядки результату (scope, ledger, tags, report). Прогін пише його в результат: поки код той
    самий, збережені рядки «усієї історії» дорівнюють перерахунку і беруться як є; змінився код — перераховуються."""
    h = hashlib.sha1()
    for m in (scope, ledger, tags, report):
        h.update(Path(m.__file__).read_bytes())
    return h.hexdigest()[:12]


ROWS_REV = _rows_rev()
env.globals["v"] = _asset_version()
from .. import __version__                                   # noqa: E402 — product version for the footer
env.globals["version"] = ".".join(__version__.split(".")[:2])
env.filters["dt"] = chart.fmt_dt
env.filters["dtu"] = lambda ms: chart.fmt_dt(ms, year=True, utc=True)   # експорт: у файлі колонка мусить назвати зону
env.filters["dty"] = lambda ms: chart.fmt_dt(ms, year=True)            # на сторінці зону називає перемикач у підвалі
env.filters["dtl"] = chart.to_input
env.filters["mcap"] = chart.fmt_mcap
env.filters["usd"] = _usd
env.filters["num"] = _num
env.filters["per_day"] = lambda n: "one live analysis a day" if int(n or 0) == 1 else f"{int(n or 0)} live analyses a day"
env.filters["log10"] = lambda v: math.log10(v) if (v and float(v) > 0) else 0.0


def _hold_text(m):
    """Хвилини утримання людською мовою: 48 min, 5.2 h, 3 d."""
    try:
        m = float(m)
    except (TypeError, ValueError):
        return "—"
    return f"{m:.0f} min" if m < 60 else (f"{m / 60:.1f} h" if m < 600 else (f"{m / 60:.0f} h" if m < 1440 else f"{m / 1440:.0f} d"))


env.filters["holdt"] = _hold_text


class WebError(Exception):
    """A message we show to the user as plain text (400 unless told otherwise)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def make_namer(identify, st=None, spend=None):
    """Після аналізу, одразу: хто стоїть за гаманцями таблиці, пакетами по 100 (секунди). Власний потік, бо черга
    збагачення зайнята віком гаманців попередніх аналізів хвилинами, а імена мають з'явитись, поки людина дивиться.

    Джерело відмовило (скінчились кредити, збій) — результат не позначається названим: наступний запуск сервера
    спитає знову, і вже знайдені імена з кешу нічого не коштують. Запити цього кроку йдуть у журнал на рахунок того,
    хто запустив аналіз (`spend`)."""
    def name(job, save):
        r = job.result
        if r.get("identities_done") and not unnamed(r):
            return
        with (st.meter() if st is not None else contextlib.nullcontext()):
            req0 = st.requests_here() if st is not None else 0
            try:
                found = identify([row["wallet"] for row in r.get("rows") or []])
            except Exception as ex:  # noqa: BLE001
                job.log.append(f"wallet names unavailable: {str(ex)[:60]}")
                return
            finally:
                if spend and st is not None:
                    spend(getattr(job, "owner", None) or "system", "names", st=st.requests_here() - req0, job=job.id, bg=1)
        r["identities"] = dict(r.get("identities") or {}, **(found or {}))
        r["identities_done"] = True
        save(job)
    return name


def full_top(r, s):
    """Скільки перших за PnL гаманців отримують повну перевірку віку і спонсора. Результат може мати свою (демо — усі)."""
    return int(r.get("age_full_top") or s.get("age_full_top", 200) or 0)


def enrich_target(r, s):
    """Скільки рядків (за PnL) перевіряє фон. Рядки з підписом першої покупки — до age_lookups_max: дешева перевірка
    читає історію гаманця до цієї покупки і коштує 1-2 кредити. Результати, зняті до цього підпису, — лише перші
    full_top: решта їхніх гаманців дочитується з картки, коли її відкривають."""
    rows = r.get("rows") or []
    cap = max(int(s.get("age_lookups_max", 0) or 0), int(r.get("age_full_top") or 0))   # демо: повна перевірка всім
    if not any(row.get("entry_tx") for row in rows):
        cap = min(cap, full_top(r, s))
    return min(len(rows), cap)


def make_enricher(ages, s, spend=None):
    """Після аналізу, у фоні: вік кожного гаманця з RPC → тег `fresh` і перший спонсор → `bundle`; прогрес у
    result["enrich"]. Кредити ноди йдуть у журнал (`spend`) на кожному збереженні: деплой dev перезапускає сервер
    посеред збагачення, і витрачене до рестарту інакше загубилось би."""
    body = _enrich_body(ages, s)

    def enrich(job, save):
        with wallet_age_mod.rpc_meter() as m:
            said = [0]

            def charge():
                n, said[0] = m["credits"] - said[0], m["credits"]
                if n and spend:
                    spend(getattr(job, "owner", None) or "system", "enrich", rpc=n, job=job.id, bg=1)

            def save_(j):
                charge()
                return save(j)
            try:
                return body(job, save_)
            finally:
                charge()
    return enrich


def _enrich_body(ages, s):
    """Сам прохід збагачення; що він коштував, рахує make_enricher.

    Перші full_top за PnL — повна перевірка: точний вік і зайнятого гаманця (10 кредитів), спонсор і в гаманця
    застосунку (пошук серед перших 100 транзакцій, 10 кредитів). Решта — дешева: сторінка історії до першої покупки
    і перша транзакція. Теги від цього не змінюються: `fresh` дешева перевірка вирішує точно (коли не може — дочитує
    вік, див. tags.could_be_fresh), а в бандлах живуть нові гаманці, у яких уся історія на одній сторінці. Чого
    дешева перевірка не дочитала — вік зайнятого гаманця, спонсора застосунку — дочитує картка, коли її відкривають."""
    def enrich(job, save):
        r = job.result
        rows = r.get("rows") or []
        n, top = enrich_target(r, s), full_top(r, s)
        e = r.setdefault("enrich", {"done": 0, "total": n, "fresh": 0, "failed": 0})
        e["total"] = n
        if e.get("failed"):
            e.update(done=0, failed=0, fresh=0)            # був збій ноди — перевіряємо заново (кеш лишається)
        e.pop("paused", None)
        e.pop("funders_failed", None)                      # невдалі спонсори не в funder_checked: цей прохід їх повторить

        is_paused = getattr(ages, "paused", None) or (lambda: False)
        cached = getattr(ages, "cached", None) or (lambda w: None)

        def pause(w, full):
            """Місячний бюджет платної ноди вичерпано: гаманець, якого нема в кеші, чекає нового місяця."""
            c = cached(w) if is_paused() else None
            if not is_paused() or (c is not None and (c.get("exact") or c.get("deep") or not full)):
                return False
            e["paused"] = "rpc-budget"
            job.log.append("wallet age paused: this month's RPC budget is used up; it resumes next month")
            save(job)
            ages.flush()
            return True
        for i, row in enumerate(rows[:n], 1):
            if i <= e.get("done", 0):
                continue                                   # продовження після перезапуску
            full = i <= top
            if pause(row["wallet"], full):
                return
            try:
                age = ages.oldest_tx(row["wallet"], full=full, before=row.get("entry_tx"))
                if _after_buy(age, row):                   # перша транзакція пізніша за покупку: запис хибний, перечитуємо
                    job.log.append(f"wallet {row['wallet'][:8]}…: its cached first transaction came after its buy — read again")
                    age = ages.oldest_tx(row["wallet"], refresh=True, full=full, before=row.get("entry_tx"))
                if not full and not age.get("exact") and tags.could_be_fresh(row.get("first_buy_ms"), age):
                    age = ages.oldest_tx(row["wallet"], full=True)   # тисяча транзакцій за добу до покупки: дочитуємо
            except Exception as ex:  # noqa: BLE001 — одна нода/гаманець не має зупиняти решту
                e["failed"] = e.get("failed", 0) + 1
                if e["failed"] <= 3:
                    job.log.append(f"age lookup failed for {row['wallet'][:8]}…: {str(ex)[:60]}")
                age = None
            if age and age.get("oldest_ms"):                # картка показує перший підпис гаманця
                r.setdefault("ages", {})[row["wallet"]] = {"ms": age["oldest_ms"], "exact": bool(age.get("exact")), "n": age.get("n")}
            if age and tags.is_fresh(row.get("first_buy_ms"), age) and "fresh" not in (row.get("tag_list") or []):
                row["tag_list"] = tags.with_tag(row.get("tag_list"), "fresh")
                row["tags"] = "|".join(row["tag_list"])
                fw = r.setdefault("fresh_wallets", [])
                if row["wallet"] not in fw:
                    fw.append(row["wallet"])
                e["fresh"] += 1
            e["done"] = i
            if i % 25 == 0:
                if save(job) is False:
                    return                                 # аналіз видалили: кредити RPC на нього більше не йдуть
                ages.flush()
        def services():
            """Біржі й застосунки серед спонсорів бандлів: одна сторінка підписів на спонсора, решта з кешу."""
            try:
                _check_services(r, ages)
            except Exception as ex:  # noqa: BLE001 — бандл лишається бандлом, наступний прохід перевірить ще раз
                job.log.append(f"exchange check failed: {str(ex)[:60]}")

        # другий прохід: хто дав перший SOL (вік уже в кеші → 1 запит getTransaction на гаманець)
        funders, checked = r.setdefault("funders", {}), set(r.get("funder_checked") or [])
        for i, row in enumerate(rows[:n], 1):
            w = row["wallet"]
            if w in funders or w in checked:
                continue
            if is_paused() and getattr(ages, "cache", None) is not None and ages.cache.get(f"funder:{w}") is None:
                e["paused"] = "rpc-budget"
                r["funder_checked"] = sorted(checked)
                services()
                _bundles(r, rows)
                save(job)
                ages.flush()
                return
            fund, ok = None, True
            try:
                age = ages.oldest_tx(w, full=False)                # те, що лишив перший прохід, без нових викликів
                if age.get("exact") and age.get("n") and not age.get("oldest_sig"):
                    age = ages.oldest_tx(w, refresh=True)          # кеш віку з часів без підпису → 1 запит
                fund = (ages.funder(w, age["oldest_sig"], scan=i <= top)
                        if age.get("exact") and age.get("oldest_sig") else None)
            except Exception as ex:  # noqa: BLE001 — 429 від ноди: гаманець не перевірено, наступний прохід спробує ще
                ok = False
                e["funders_failed"] = e.get("funders_failed", 0) + 1
                if e["funders_failed"] <= 3:
                    job.log.append(f"funder lookup failed for {w[:8]}…: {str(ex)[:60]}")
            if fund:
                funders[w] = fund
            if ok:
                checked.add(w)
            e["funders_done"] = i
            if i % 25 == 0:
                r["funder_checked"] = sorted(checked)
                services()
                _bundles(r, rows)
                if save(job) is False:
                    return
                ages.flush()
        r["funder_checked"] = sorted(checked)
        e["funders_done"] = n
        services()
        _bundles(r, rows)
        r["bundle_rev"] = tags.BUNDLE_REV                   # бандли пораховані чинним правилом
        save(job)
        ages.flush()
    return enrich


def _after_buy(age, row):
    """Точний вік, за яким гаманець народився після власної покупки, — неможливий: кеш бачив лише кінець історії."""
    return bool(age and age.get("exact") and age.get("oldest_ms") and row.get("first_buy_ms")
                and age["oldest_ms"] > row["first_buy_ms"] + 60_000)


def _burst(wallets, born):
    """Гаманці, народжені пачкою: у кожного за ±BURST_MS є ще щонайменше BUNDLE_MIN − 1 гаманців того самого спонсора."""
    t = sorted((born[w], w) for w in wallets if born.get(w))
    out, lo, hi = [], 0, 0
    for i in range(len(t)):
        while t[i][0] - t[lo][0] > tags.BURST_MS:
            lo += 1
        hi = max(hi, i)
        while hi + 1 < len(t) and t[hi + 1][0] - t[i][0] <= tags.BURST_MS:
            hi += 1
        if hi - lo + 1 >= tags.BUNDLE_MIN:
            out.append(t[i][1])
    return out


def _bundles(r, rows):
    """Гаманці зі спільним спонсором (≥ BUNDLE_MIN у цьому списку) → тег bundle.

    Спонсор-біржа чи застосунок (r["services"], див. WalletAge.is_service) роздає SOL випадковим людям у випадковий
    час, тож від нього бандл — лише гаманці, народжені пачкою (tags.BURST_MS). Інакше правило сховало б найважливіший
    випадок: 24.09 на 52qkNp один гаманець за 41 хвилину створив 200 гаманців, і сам через це мав тисячі транзакцій
    на добу, як біржа."""
    from collections import defaultdict
    funders, services = r.get("funders") or {}, set(r.get("services") or [])
    born = {w: a["ms"] for w, a in (r.get("ages") or {}).items() if a and a.get("exact") and a.get("ms")}
    groups = defaultdict(list)
    for w, f in funders.items():
        groups[f].append(w)
    r["bundle"] = {}
    for f, ws in groups.items():
        keep = ws
        if f in services:
            # більшість його гаманців тут народились пачкою — він тут бандлер, а не біржа: рахуються всі (на 52qkNp
            # 274 з 299 були в пачках, решта 25 — ті самі гаманці бандлера); у біржі пачка — випадковий збіг, лише вона
            burst, dated = _burst(ws, born), sum(1 for w in ws if born.get(w))
            keep = ws if len(burst) * 2 > dated else burst
        if len(keep) >= tags.BUNDLE_MIN:
            r["bundle"].update({w: {"funder": f, "n": len(keep)} for w in keep})
    for row in rows:                                    # старі результати без угод: теги прямо в рядках
        tl = row.get("tag_list") or []
        if row["wallet"] in r["bundle"] and "bundle" not in tl:
            row["tag_list"] = tags.with_tag(tl, "bundle")
            row["tags"] = "|".join(row["tag_list"])
        elif row["wallet"] not in r["bundle"] and "bundle" in tl:   # спонсор виявився біржею: тег знімається
            row["tag_list"] = [t for t in tl if t != "bundle"]
            row["tags"] = "|".join(row["tag_list"])


def _check_services(r, ages):
    """Спонсор, що зібрав бандл, — біржа чи застосунок? 1 кредит на спонсора, далі з кешу. r["services"] з'являється
    навіть порожнім: так видно, що результат цю перевірку вже пройшов."""
    check = getattr(ages, "is_service", None)
    services = set(r.get("services") or [])
    if check is not None and not (getattr(ages, "paused", None) or (lambda: False))():
        from collections import Counter
        for f, n in Counter((r.get("funders") or {}).values()).items():
            if n >= tags.BUNDLE_MIN and f not in services and check(f):
                services.add(f)
    r["services"] = sorted(services)


def create_app(st, s, cfg=None, out_dir="output/early/web", store_dir="cache/early", ages=None, assistant=None):
    app = web.Application(middlewares=[errors_mw, auth_mw])
    app.on_response_prepare.append(_security_headers)
    app.on_cleanup.append(_flush_on_exit)
    app["assistant"] = assistant                                   # транспорт до моделі; None — агента на цьому сервері нема
    app["agent"] = agent_mod.Agent(assistant.json_chat, assistant.model) if assistant is not None else None
    app["agent_store"] = AgentStore(Path(out_dir).parent / "agent")   # методика власника, її версії, журнал питань
    app["agent_cache"], app["agent_inflight"] = {}, {}             # картки спільного демо (у файл не пишуться) і ті, що вже пишуться
    app["st"], app["s"], app["cfg"] = st, s, cfg or {}
    app["store_dir"] = store_dir
    app["runs"] = Throttle(max_fails=int(s.get("runs_per_hour", 20)), window_s=3600, block_s=3600)
    # демо безкоштовне, але кожне програвання тримає потік 12 с: з однієї адреси — близько десяти за 10 хвилин
    app["demo_runs"] = Throttle(max_fails=int(s.get("demo_replays_per_10min", 10)), window_s=600, block_s=600)
    app["demo_replays"] = {}                                     # (адреса, діапазон) → id програвання, що ще йде
    app["rows_memo"] = {}                                        # рядки масштабів 24h/48h: рахуються раз, не на кожен перегляд
    app["age_saves"] = {"last": {}, "waiting": {}, "tasks": set()}   # картки: коли писали результат, відкладені записи
    app["st_slots"] = threading.BoundedSemaphore(max(1, int(s.get("st_concurrency", 1) or 1)) + 1)   # +1: сторінка не чекає за прогоном
    app["overview_cache"], app["overview_pending"] = {}, {}
    app["dex_cache"] = JsonCache(str(Path(store_dir) / "dexscreener.json"), ttl_hours=24)   # чужий безкоштовний ендпоінт: добу тримаємо відповідь
    app["profile_cache"] = JsonCache(str(Path(store_dir) / "wallet_profile.json"),             # картка гаманця: 1-5 запитів, добу з кешу
                                     ttl_hours=float(s.get("wallet_profile_ttl_hours", 24)), flush_every=25)   # решту допише зупинка сервера
    app["accounts"] = acct_mod.AccountStore(Path(out_dir).parent / "accounts")   # поруч з web/ і demo/ у output/early
    app["nonces"] = acct_mod.NonceStore()
    # що роблять гаманці і скільки це коштувало, файл на місяць; старий журнал до 26.09.2026 лише читається
    app["events"] = acct_mod.EventLog(Path(out_dir).parent / "usage", legacy=Path(out_dir).parent / "accounts" / "_events.jsonl")
    app["admins"] = {w.strip() for w in os.getenv("ADMIN_WALLETS", "").split(",") if w.strip()}   # чиї гаманці бачать /admin
    app["auth_throttle"] = Throttle(max_fails=10, window_s=300, block_s=600)
    daily_dir = Path(out_dir).parent / "daily"           # добові лічильники переживають деплой
    app["assistant_daily"] = DailyCount(daily_dir / "assistant.json")
    app["browse_daily"] = DailyCount(daily_dir / "browse.json")   # запити на графіки живих токенів: на адресу, на гаманець, на сайт
    app["runs_daily"] = DailyCount(daily_dir / "runs.json")       # живі прогони на весь сайт за добу (будь-який ключ підписує безкоштовно)
    app["usage_daily"] = DailyCount(daily_dir / "usage.json")     # рядків журналу (перегляди, кліки) на гаманець і на сайт за добу
    app["usage_cache"], app["view_last"] = {}, {}                 # порахований дашборд на хвилину; останній перегляд сторінки
    app["credits"] = {"left": None, "at": 0}                     # залишок кредитів Data API: питаємо не частіше ніж раз на 10 хв
    app["ages"] = ages
    _share_st(st, app["st_slots"])

    def runner(job):
        if job.replay:
            return _replay(job, page_size=int(s.get("page_size", 250)), budget_s=float(s.get("replay_s", 12)))
        with st.meter():                                   # стеля прогону рахує лише його власні запити
            req0 = st.requests_here()
            try:
                res = pipeline.run(st, job.mint, job.t_from, job.t_to, dict(s, **(job.s_over or {})),   # стелі прогону залежать від того, хто запустив
                                   log=job.log.append, progress=job.set_progress, store_dir=store_dir)
            finally:
                job.spent = st.requests_here() - req0      # і для невдалого: від цього залежить, чи повертати день
        res["rows_rev"] = ROWS_REV
        return res

    def on_error(job):
        """A live run that failed before it spent much, or was cut by a restart, gives the wallet, the browser and the
        network their run back, and the site its slot. One that already spent real credits keeps the charge: otherwise
        runs that fail late would be free, and the daily caps would not bound what is spent."""
        if not job.owner or job.replay:
            return
        if job.spent is not None and job.spent >= int(s.get("refund_below_requests", 50)):
            job.log.append(f"This run spent {job.spent:,} requests before it stopped, so it counts toward today's analyses.")
            return
        app["accounts"].give_back_run(job.owner)
        if job.owner not in app["admins"]:
            app["runs_daily"].add("global", -1)
            for key in job.charged or []:
                app["runs_daily"].add(key, -1)

    def spend(who, what, **kw):
        _spend(app, who, what, **kw)

    def on_finish(job):
        """Живий прогін закінчився: рядок журналу — хто, що, скільки запитів і що знайшов (дашборд власника)."""
        app["events"].add(job.owner or "system", "run", **usage_mod.run_facts(job))

    identify = ((lambda ws: st.identities(ws, strict=True))               # відмова джерела ≠ «імен нема»
                if (hasattr(st, "identities") and s.get("st_identity", True)) else None)
    app["jobs"] = JobQueue(runner, out_dir, enricher=make_enricher(ages, s, spend) if ages else None, on_error=on_error,
                           enrich_upto=(lambda r: enrich_target(r, s)) if ages else 0,
                           namer=make_namer(identify, st, spend) if identify else None, on_finish=on_finish)
    app.router.add_get("/", index)
    app.router.add_get("/how", how)
    app.router.add_get("/docs", docs_page)
    app.router.add_get("/docs/{slug}", docs_page)
    app.router.add_get("/project", project)
    app.router.add_get("/token", token_page)
    app.router.add_get("/candles.json", candles_json)
    app.router.add_get("/marks.json", marks_json)
    app.router.add_post("/analyze", analyze)
    app.router.add_get("/wallet_trades.json", wallet_trades_json)
    app.router.add_get("/wallet_profile.json", wallet_profile_json)
    app.router.add_get("/job/{id}.state.json", job_state_json)     # before .json: {id} would swallow ".state"
    app.router.add_get("/job/{id}.enrich.json", job_enrich_json)   # before .json: {id} would swallow ".enrich"
    app.router.add_get("/job/{id}.csv", job_csv)     # before /job/{id}: {id} would swallow the dot
    app.router.add_get("/job/{id}.json", job_json)
    app.router.add_post("/job/{id}/agent/cards", job_agent_cards)
    app.router.add_post("/job/{id}/agent/ask", job_agent_ask)
    app.router.add_get("/job/{id}", job_page)
    app.router.add_get("/health", health)
    app.router.add_post("/auth/nonce", auth_nonce)
    app.router.add_post("/auth/verify", auth_verify)
    app.router.add_post("/auth/logout", auth_logout)
    app.router.add_get("/me", me_page)
    app.router.add_get("/me.json", me_json)
    app.router.add_get("/me/wallets.csv", me_wallets_csv)
    app.router.add_post("/me/wallets", me_add_wallets)
    app.router.add_post("/me/wallets/remove", me_remove_wallet)
    app.router.add_post("/me/wallets/tags", me_tags)
    app.router.add_post("/me/lists", me_lists)
    app.router.add_post("/me/lists/{action}", me_lists)
    app.router.add_post("/me/analyses", me_add_analysis)
    app.router.add_post("/me/analyses/remove", me_remove_analysis)
    app.router.add_post("/me/usage", me_usage)
    app.router.add_get("/admin", admin_page)
    app.router.add_post("/admin/demo", admin_demo)
    app.router.add_post("/admin/agent", admin_agent_save)
    app.router.add_post("/admin/agent/preview", admin_agent_preview)
    app.router.add_get("/wallet_age.json", wallet_age_json)
    app.router.add_get("/job/{id}/crossings.json", job_crossings_json)
    app.router.add_post("/job/{id}/delete", job_delete)
    app.router.add_static("/static", str(HERE / "static"))
    return app


SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'",   # без script-src: у сторінках є вбудовані скрипти
}


async def _security_headers(request, response):
    """Кожна відповідь (сторінка, редірект, помилка, статика) несе заголовки захисту сама, а не лише коли їх додав проксі;
    Server не називає версію aiohttp."""
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    response.headers["Server"] = "tracced"


async def _flush_on_exit(app):
    """Зупинка сервера: відкладені записи результатів і кеші — на диск. Сторінки більше не пишуть кеші щоразу."""
    for job, task in list(app["age_saves"]["waiting"].values()):
        task.cancel()
        try:
            await asyncio.to_thread(app["jobs"]._save, job, True)
        except Exception as e:  # noqa: BLE001
            log.warning("save on exit %s: %s", job.id, e)
    fns = [app["profile_cache"].flush, app["dex_cache"].flush]
    if hasattr(app["st"], "flush"):
        fns.append(app["st"].flush)
    if app.get("ages") is not None:
        fns.append(app["ages"].flush)
    for fn in fns:
        try:
            await asyncio.to_thread(fn)
        except Exception as e:  # noqa: BLE001
            log.warning("flush on exit: %s", e)


_METER = contextvars.ContextVar("st_meter", default=None)
_METER_LOCK = threading.Lock()


def _share_st(st, slots):
    """One client for the analysis and every page: at most `slots` calls in flight at once.

    Each caller counts its own calls. `with st.meter():` opens a counter that lives in the context, so the worker
    threads of one analysis (started with contextvars.copy_context()) add to the same counter, and a chart page
    running at the same moment keeps its own. A run's cap and a page's charge read st.requests_here(); a delta of
    the global st.requests would count other people's calls as soon as two things run together. A call is
    counted before it is made: a failed request is paid for too."""
    orig = getattr(st, "_get", None)
    if orig is None:                      # fake client in tests: single-threaded, the global count is the caller's
        st.meter = contextlib.nullcontext
        st.requests_here = lambda: st.requests
        return

    @contextlib.contextmanager
    def meter():
        token = _METER.set({"n": 0})
        try:
            yield
        finally:
            _METER.reset(token)

    def here():
        m = _METER.get()
        return m["n"] if m is not None else st.requests

    def shared(path, *a, **kw):
        with slots:
            m = _METER.get()
            if m is not None:
                with _METER_LOCK:
                    m["n"] += 1
            return orig(path, *a, **kw)
    st.meter, st.requests_here, st._get = meter, here, shared


# ───────────────────────── middleware ─────────────────────────

@web.middleware
async def errors_mw(request, handler):
    try:
        return await handler(request)
    except web.HTTPNotFound as e:
        if request.path.endswith((".json", ".csv")):
            raise
        return render("error.html", request, message=e.text or "There is no such page.", status=404)
    except web.HTTPException:
        raise
    except ConnectRequired as e:
        if request.path.endswith(".json"):
            return _jerr(str(e), 401)
        return render("connect.html", request, mint=e.mint, t_from=e.t_from, t_to=e.t_to,
                      demo_mint=(_demo(request.app) or {}).get("mint"), status=401)
    except WebError as e:
        if request.path.endswith(".json"):
            return _jerr(str(e), e.status)                             # графік читає JSON і показує причину, а не порожнечу
        return render("error.html", request, message=str(e), status=e.status)
    except Exception:
        log.exception("page %s failed", request.path)
        return render("error.html", request,
                      message="Something broke on our side. The log has the details.", status=500)


_RUNTIME_SECRET = secrets.token_hex(32)   # якщо WEB_SECRET не задано: куки живуть до перезапуску


class Throttle:
    """Makes guessing and hammering slow: a few misses from one address and that address waits.

    The site is public and the paid API quota is behind it, so an unlimited rate would hand it away in
    minutes. Pure bookkeeping, no I/O — easy to test.
    """

    def __init__(self, max_fails=5, window_s=300, block_s=900):
        self.max_fails, self.window_s, self.block_s = max_fails, window_s, block_s
        self.fails = {}                       # address -> [misses, first miss (s), blocked until (s)]

    def wait_s(self, key, now):
        """Seconds this address still has to wait; 0 means it may try."""
        f = self.fails.get(key)
        return max(0, int(f[2] - now)) if f else 0

    def miss(self, key, now):
        """Count a miss (or a spend); returns the seconds to wait (0 while under the limit)."""
        f = self.fails.get(key)
        if not f or now - f[1] > self.window_s:
            f = [0, now, 0]
        f[0] += 1
        if f[0] >= self.max_fails:
            f[2] = now + self.block_s * (1 + (f[0] - self.max_fails))   # кожна наступна спроба — довша пауза
        if len(self.fails) > 10_000:                                    # адрес багато: чужі й прострочені записи прибираємо
            self.fails = {k: v for k, v in self.fails.items() if now - v[1] <= self.window_s or v[2] > now}
        self.fails[key] = f
        return max(0, int(f[2] - now))

    def hit(self, key):
        """A success clears the record."""
        self.fails.pop(key, None)


class DailyCount:
    """Скільки разів ключ (гаманець, IP або «global») щось зробив сьогодні; скидається опівночі UTC. З файлом —
    переживає перезапуск і деплой (інакше кожен пуш дарував би сайту нову добу).

    Під замком: settle() кличеться з робочих потоків у той самий час, коли обробник сторінки резервує, а запис
    файлу обходить словник, який інший потік у цю мить перебудовує."""

    def __init__(self, path=None):
        self._lock = threading.RLock()
        self.n = {}                           # key -> [day, count]
        self.path = Path(path) if path else None
        if self.path and self.path.exists():
            try:
                self.n = {k: [int(v[0]), int(v[1])] for k, v in json.loads(self.path.read_text(encoding="utf-8")).items()}
            except Exception:  # noqa: BLE001 — битий файл = чистий лічильник
                self.n = {}

    def _flush(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.n), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass

    def _prune(self, day):
        if len(self.n) > 10_000:                                        # записи минулих днів нікому не потрібні
            self.n = {k: v for k, v in self.n.items() if v[0] == day}

    def take(self, key, cap, now=None):
        """True і +1, якщо стеля ще не досягнута; False — коли досягнута."""
        day = int((time.time() if now is None else now) // 86400)
        with self._lock:
            self._prune(day)
            rec = self.n.get(key)
            if not rec or rec[0] != day:
                rec = [day, 0]
            if rec[1] >= int(cap):
                self.n[key] = rec
                return False
            rec[1] += 1
            self.n[key] = rec
            self._flush()
            return True

    def add(self, key, n, now=None):
        """+n без стелі: коли ціна відома лише після дії (скільки запитів справді пішло в мережу)."""
        day = int((time.time() if now is None else now) // 86400)
        with self._lock:
            self._prune(day)
            rec = self.n.get(key)
            if not rec or rec[0] != day:
                rec = [day, 0]
            rec[1] = max(0, rec[1] + int(n))
            self.n[key] = rec
            self._flush()

    def left(self, key, cap, now=None):
        day = int((time.time() if now is None else now) // 86400)
        with self._lock:
            rec = self.n.get(key)
            return int(cap) - (rec[1] if rec and rec[0] == day else 0)


def _client_ip(request):
    """The address the request really came from: behind our proxy that is the last hop it added. An IPv6 host is
    keyed by its /64, otherwise one machine would own 2^64 separate budgets."""
    xff = request.headers.get("X-Forwarded-For", "")
    raw = (xff.split(",")[-1].strip() if xff else None) or request.remote or "?"
    try:
        ip = ipaddress.ip_address(raw)
        return str(ipaddress.ip_network((ip, 64), strict=False)) if ip.version == 6 else str(ip)
    except ValueError:
        return raw


def _wait_text(s):
    return f"Too many attempts. Try again in {max(1, round(s / 60))} min." if s >= 60 else f"Too many attempts. Try again in {s} s."


EARLY_NOTE = "tracced is early, so the limits are small while we watch the load; they will grow."


class ConnectRequired(Exception):
    """A new live run needs a connected wallet: the page says so, offers to connect and keeps the range (401)."""

    def __init__(self, mint=None, t_from=None, t_to=None, message=None):
        super().__init__(message or "Connect a wallet to run this analysis.")
        self.mint, self.t_from, self.t_to = mint, t_from, t_to


def _is_demo_mint(app, mint):
    demo = _demo(app)
    return bool(demo and demo["mint"] == mint)


OVERVIEW_TTL, OVERVIEW_FAIL_TTL, OVERVIEW_MAX = 600, 120, 200
CREDITS_TTL = 600


async def _credits_left(app):
    """Credits left on the Solana Tracker key, asked at most once per 10 minutes: the question is a request too, and
    asked on every run or every health check it would itself become a noticeable share of the month. None when
    unknown (a failed call, a client without /credits): then nothing is blocked."""
    c, st = app["credits"], app["st"]
    if not hasattr(st, "credits"):
        return None
    if c["at"] and time.time() - c["at"] < CREDITS_TTL:
        return c["left"]

    def ask():
        with st.meter():
            req0 = st.requests_here()
            try:
                return st.credits()
            finally:
                _spend(app, "system", "credits", st=st.requests_here() - req0, bg=1)
    try:
        left = await asyncio.to_thread(ask)
    except Exception:  # noqa: BLE001
        left = None
    c.update(left=int(left) if left is not None else None, at=time.time())
    return c["left"]


def _credits_reserve(s):
    return int(float(s.get("credits_month", 0) or 0) * float(s.get("credits_reserve_pct", 0) or 0) / 100)


def _overview_cached(app, mint):
    hit = app["overview_cache"].get(mint)
    return bool(hit and time.time() - hit[0] < (OVERVIEW_TTL if hit[1] is not None else OVERVIEW_FAIL_TTL))


def _prune_overview(cache):
    now = time.time()
    for k in [k for k, v in cache.items() if now - v[0] >= (OVERVIEW_TTL if v[1] is not None else OVERVIEW_FAIL_TTL)]:
        cache.pop(k, None)
    while len(cache) > OVERVIEW_MAX:                                    # пам'ять не росте з кожним новим токеном
        cache.pop(min(cache, key=lambda k: cache[k][0]), None)


def _browse_budget(request, est=1):
    """Графік живого токена коштує запитів до Solana Tracker (огляд ≈2, кожен шматок свічок 1), а дивитись його може
    будь-хто. Тому добова стеля: на адресу без гаманця, на гаманець, спільна на сайт; адміни поза нею. Кидає 429,
    коли стелю вичерпано; інакше одразу резервує `est` (щоб пачка одночасних запитів не проскочила повз перевірку)
    і повертає settle(actual) — виправити резерв на те, що справді пішло в мережу; кликати у finally, щоб і невдалі
    запити були оплачені. Кеш нічого не коштує."""
    app, s, pk = request.app, request.app["s"], request.get("acct")
    if pk and pk in app["admins"]:
        return lambda n: None
    daily = app["browse_daily"]
    who, cap = (f"acct:{pk}", s.get("browse_per_day", 150)) if pk else (f"ip:{_client_ip(request)}", s.get("browse_per_day_guest", 30))
    gcap = s.get("browse_global_per_day", 300)
    if daily.left("global", gcap) <= 0:
        _limit(app, pk, "browse", "site")
        raise WebError("Today's chart budget for new tokens is used up. The demo is always open; more tomorrow.", 429)
    if daily.left(who, cap) <= 0:
        _limit(app, pk, "browse", "wallet")
        raise WebError("You have used today's chart budget from this address. Connect a wallet for more, or come back tomorrow."
                       if not pk else "You have used today's chart budget for this wallet. The demo is always open; more tomorrow.", 429)
    daily.add(who, est)
    daily.add("global", est)

    def settle(actual):
        d = int(actual) - int(est)
        if d:
            daily.add(who, d)
            daily.add("global", d)
    return settle


def _usage_take(app, pk, n):
    """Скільки з n рядків журналу (перегляди, кліки) цього гаманця ще влазить у сьогоднішні стелі — стільки й списує.

    Перегляд чи клік нічого не коштують, тож без стелі будь-який підключений гаманець міг би циклом писати журнал,
    доки не скінчиться диск: 1000 рядків на гаманець і 30 000 на сайт за добу — у сотні разів більше, ніж клікає людина."""
    s, daily = app["s"], app["usage_daily"]
    ok = min(int(n), daily.left(f"ev:{pk}", int(s.get("usage_events_per_day", 1000))),
             daily.left("ev:global", int(s.get("usage_events_global_per_day", 30000))))
    if ok <= 0:
        return 0
    daily.add(f"ev:{pk}", ok)
    daily.add("ev:global", ok)
    return ok


VIEW_MERGE_MS = 30_000


def _device(request):
    """Телефон (m) чи комп'ютер (d): з User-Agent, грубо, але для «з чого заходять» досить."""
    return "m" if re.search(r"Mobi|Android|iPhone|iPad", request.headers.get("User-Agent", "")) else "d"


def _view(request, page, ref=None, **extra):
    """Підключений гаманець відкрив сторінку: рядок журналу (гостей рахує Umami). Та сама сторінка того самого гаманця
    протягом 30 с — оновлення чи крок назад — рахується одним переглядом."""
    app, pk = request.app, request.get("acct")
    if not pk:
        return
    now, last, key = int(time.time() * 1000), request.app["view_last"], (pk, page, ref)
    if now - last.get(key, 0) < VIEW_MERGE_MS:
        return
    if len(last) > 10_000:
        last.clear()
    last[key] = now
    if _usage_take(app, pk, 1):
        app["events"].add(pk, "view", page=page, ref=ref, dev=_device(request), **extra)


def _spend(app, who, what, st=0, rpc=0, **extra):
    """Кредити одного кроку — рядок журналу: хто (гаманець, "guest" чи "system"), на що і скільки. Нулі не пишемо: кеш
    нічого не коштує. Стелі тут нема: витрати й так обмежені бюджетами, а загублена витрата — хибна сума в дашборді."""
    st, rpc = int(st or 0), int(rpc or 0)
    if st > 0 or rpc > 0:
        app["events"].add(who or "guest", "spend", what=what, st=st or None, rpc=rpc or None, **extra)


def _limit(app, pk, what, kind):
    """Гаманець уперся в стелю: рядок журналу, щоб власник бачив, чи стелі не завузькі. Гостей не пишемо."""
    if pk and _usage_take(app, pk, 1):
        app["events"].add(pk, "limit", what=what, kind=kind)


@web.middleware
async def auth_mw(request, handler):
    request["acct"] = _acct(request)                    # хто увійшов гаманцем (або None); паролів на сайті нема
    return await handler(request)


# ───────────────────────── wallet sign-in and the account ─────────────────────────

def _acct_secret():
    return os.getenv("WEB_SECRET") or _RUNTIME_SECRET


def _device_id(request):
    """Число браузера з куки, якщо воно наше за формою; інакше None (кука з'явиться з першим аналізом)."""
    v = request.cookies.get(DEVICE_COOKIE) or ""
    return v if re.fullmatch(r"[0-9a-f]{32}", v) else None


def _ip_key(ip):
    """Ключ мережі в добовому лічильнику: хеш адреси з секретом сайту, щоб у файлах не лежали самі адреси."""
    return "ip:" + hashlib.sha256(f"{_acct_secret()}|{ip}".encode()).hexdigest()[:16]


def _runs_left(app, pk, dev, ip):
    """(скільки живих аналізів людині лишилось сьогодні, який лічильник це вирішив: "person" чи "network").

    Найменше з трьох лічильників. Гаманець і браузер мають спільну стелю `runs_per_day`, тож інший гаманець у тому ж
    браузері нових спроб не дає; мережа має свою, вищу, `runs_per_ip_per_day`: на неї натрапляє інкогніто з новим
    гаманцем, а люди в одному офісі — рідко. "network" — лише коли людина свої ще має, а вичерпала мережа: тоді вікно
    не каже «ви використали свої п'ять»."""
    s = app["s"]
    cap = int(s.get("runs_per_day", 1))
    person = cap - app["accounts"].runs_today(pk)
    if dev:
        person = min(person, app["runs_daily"].left("dev:" + dev, cap))
    net = app["runs_daily"].left(_ip_key(ip), int(s.get("runs_per_ip_per_day", 10)))
    return max(0, min(person, net)), ("network" if net <= 0 < person else "person")


def _next_midnight_ms(now=None):
    """Коли обнуляються добові лічильники: наступна північ за UTC."""
    return (int((time.time() if now is None else now) // 86400) + 1) * 86_400_000


def _acct(request):
    return acct_mod.read_acct(_acct_secret(), request.cookies.get(ACCT_COOKIE))


def _short(pk):
    return f"{pk[:4]}…{pk[-4:]}"


def _expected_domain(request):
    """Домен у тексті для підпису: Caddy передає Host як є, тож зазвичай це request.host."""
    return os.getenv("WEB_DOMAIN") or request.host


def _same_origin(request):
    """POST з іншого сайту не приймаємо: кука йде з браузером, а чужа сторінка не має цієї перевірки."""
    from urllib.parse import urlsplit
    src = request.headers.get("Origin") or request.headers.get("Referer") or ""
    return bool(src) and urlsplit(src).netloc == request.host


def _jerr(message, status=400):
    return web.json_response({"error": message}, status=status)


async def _json_body(request, limit=16_384):
    """Тіло як словник, або None (завелике, не JSON, не об'єкт)."""
    raw = await request.read()
    if len(raw) > limit:
        return None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _acct_route(fn):
    """Маршрут акаунта: лише з цього сайту (для POST) і лише з кукою гаманця → fn(request, pubkey)."""
    async def wrapped(request):
        if request.method == "POST" and not _same_origin(request):
            return _jerr("Requests must come from this site.", 403)
        pk = request.get("acct")
        if not pk:
            return _jerr("Sign in with your wallet first.", 401)
        return await fn(request, pk)
    wrapped.__name__ = fn.__name__
    return wrapped


async def auth_nonce(request):
    """Одноразовий код і поля, з яких браузер збирає текст для підпису."""
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    now = time.time()
    wait = request.app["auth_throttle"].wait_s(_client_ip(request), now)
    if wait:
        return _jerr(_wait_text(wait), 429)
    return web.json_response({"nonce": request.app["nonces"].issue(now), "domain": _expected_domain(request),
                              "issued_at": acct_mod.issued_at(now), "statement": acct_mod.STATEMENT},
                             headers={"Cache-Control": "no-store"})


def _signin_problem(app, request, pubkey, signature, message, now):
    """Чому вхід не приймаємо, або None. Дешеві перевірки першими; nonce спалюється до перевірки підпису."""
    try:
        m = acct_mod.parse_message(message)
    except ValueError:
        return "The signed message has an unexpected format."
    if m["domain"] != _expected_domain(request):
        return "The message was made for another site."
    if not acct_mod.valid_pubkey(pubkey) or m["pubkey"] != pubkey:
        return "The wallet address does not match the message."
    if not app["nonces"].consume(m["nonce"], now):
        return "This sign-in request expired. Try again."
    iat = acct_mod.parse_issued_at(m["issued_at"])
    if iat is None or abs(now - iat) > 600:
        return "This sign-in request expired. Try again."
    if not acct_mod.verify_signature(pubkey, message, signature):
        return "The signature does not match the wallet."
    return None


async def auth_verify(request):
    """Підпис справжній → кука акаунта на ACCT_DAYS; перший вхід створює акаунт."""
    app = request.app
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    ip, now, th = _client_ip(request), time.time(), app["auth_throttle"]
    wait = th.wait_s(ip, now)
    if wait:
        return _jerr(_wait_text(wait), 429)
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    pubkey, sig, msg = str(body.get("pubkey") or ""), str(body.get("signature") or ""), str(body.get("message") or "")
    why = _signin_problem(app, request, pubkey, sig, msg, now)
    if why:
        th.miss(ip, now)
        return _jerr(why, 401)
    th.hit(ip)
    wallet_app = str(body.get("wallet") or "")[:40]
    app["accounts"].touch(pubkey, wallet_app)
    app["events"].add(pubkey, "signin", wallet=wallet_app)
    resp = web.json_response({"ok": True, "pubkey": pubkey, "short": _short(pubkey)})
    resp.set_cookie(ACCT_COOKIE, acct_mod.sign_acct(_acct_secret(), pubkey, int(now) + ACCT_DAYS * 86400),
                    httponly=True, samesite="Lax", secure=True, max_age=ACCT_DAYS * 86400)
    return resp


async def auth_logout(request):
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    if request.get("acct"):                             # кука ще тут: хто саме вийшов
        request.app["events"].add(request["acct"], "signout")
    resp = web.json_response({"ok": True})
    resp.del_cookie(ACCT_COOKIE)
    return resp


def _demo_job_ids(app):
    demo = _demo(app)
    return {r["job"] for r in demo["ranges"]} if demo else set()


def _job_visible(request, job):
    """Готові результати публічні: платить той, хто запускає, а не той, хто дивиться."""
    return bool(job and job.status == "done" and job.result)


def _wallet_snapshot(job, row):
    """Що лягає в «мій список»: факти рядка на момент збереження + звідки він."""
    return {"wallet": row["wallet"], "from_job": job.id, "mint": job.mint, "symbol": job.symbol,
            "entry_mcap": row.get("entry_range_mcap") or row.get("entry_mcap_avg") or 0,
            "invested_usd": row.get("invested_in_range_usd") or 0, "multiple": row.get("multiple") or 0,
            "tags": list(row.get("tag_list") or [])}


def _analysis_snapshot(job, rows, sm):
    return {"mint": job.mint, "symbol": job.symbol, "t_from": job.t_from, "t_to": job.t_to,
            "n": sm.get("n") or len(rows), "best": sm.get("best_multiple") or 0}


async def _visible_job(request, body):
    """Аналіз із тіла запиту, або відповідь-помилка."""
    job = request.app["jobs"].get(str(body.get("job") or ""))
    if not job or job.status != "done" or not job.result:
        return None, _jerr("No result yet.", 404)
    return job, None


@_acct_route
async def me_add_wallets(request, pk):
    app = request.app
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    job, err = await _visible_job(request, body)
    if err:
        return err
    want = body.get("wallets")
    if not isinstance(want, list) or not want:
        return _jerr("Pick at least one wallet.")
    if len(want) > acct_mod.MAX_WALLETS:
        return _jerr(f"At most {acct_mod.MAX_WALLETS} wallets per request.")
    rows, _ = await _rows_async(app, job.result, "all")
    by = {r["wallet"]: r for r in rows}
    items = [_wallet_snapshot(job, by[w]) for w in dict.fromkeys(str(w) for w in want) if w in by]
    if not items:
        return _jerr("Nothing to save from this analysis.")
    lid = str(body.get("list") or acct_mod.MAIN_LIST)
    try:
        added, total = app["accounts"].add_wallets(pk, items, lid)
    except acct_mod.AccountError as e:
        return _jerr(str(e))
    app["events"].add(pk, "save_wallets", n=added, job=job.id, symbol=job.symbol)
    return web.json_response({"ok": True, "added": added, "total": total, "skipped": len(want) - len(items),
                              "wallets": [i["wallet"] for i in items], "list": lid})


@_acct_route
async def me_remove_wallet(request, pk):
    """One wallet ({wallet}) or several ({wallets: [...]})."""
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    want = body.get("wallets") if isinstance(body.get("wallets"), list) else [body.get("wallet")]
    want = [w for w in want[: acct_mod.MAX_WALLETS] if acct_mod.valid_pubkey(w)]   # сміття не доходить до файлу
    lid = str(body["list"]) if body.get("list") else None          # без списку — з усіх списків
    # один запис файлу на весь вибір, і не в циклі подій: 500 адрес по запису на кожну вішали сайт на секунди
    removed = await asyncio.to_thread(request.app["accounts"].remove_wallets, pk, want, lid) if want else 0
    if removed:
        request.app["events"].add(pk, "remove_wallet", n=removed)
    return web.json_response({"ok": bool(removed), "removed": removed})


@_acct_route
async def me_lists(request, pk):
    """Списки спостереження: створити ({name}), перейменувати ({id, name}) чи прибрати ({id}) — за адресою."""
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    acc, action = request.app["accounts"], request.match_info.get("action") or "create"
    try:
        if action == "create":
            lid, name = acc.create_list(pk, body.get("name"))
            out = {"id": lid, "name": name}
        elif action == "rename":
            acc.rename_list(pk, str(body.get("id") or ""), body.get("name"))
            out = {}
        elif action == "remove":
            out = {"removed_wallets": acc.delete_list(pk, str(body.get("id") or ""))}
        else:
            return _jerr("Unknown action.", 404)
    except acct_mod.AccountError as e:
        return _jerr(str(e))
    request.app["events"].add(pk, "list_" + action)
    return web.json_response(dict(out, ok=True, lists=acc.load(pk)["lists"]))


@_acct_route
async def me_tags(request, pk):
    """Власні мітки гаманця: коротке слово, за яким список можна відібрати, замість вільної нотатки."""
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    tags_in = body.get("tags")
    if not isinstance(tags_in, list):
        return _jerr("Tags must be a list.")
    out = request.app["accounts"].set_my_tags(pk, str(body.get("wallet") or ""), tags_in)
    if out is not False:
        request.app["events"].add(pk, "tags", count=len(out))   # лише скільки: слова тегів — справа людини
    return web.json_response({"ok": True, "tags": out}) if out is not False else _jerr("That wallet is not in your list.", 404)


@_acct_route
async def me_usage(request, pk):
    """Кліки підключеного гаманця пачкою зі сторінки (EarlyUI.use): лише назви з білого списку і короткі значення, без
    адрес і без набраного тексту. Де клікали, каже Referer цього ж сайту. Відповідь завжди 204 — сторінці нічого з нею
    робити; що не влізло в добові стелі журналу, просто не пишеться."""
    app = request.app
    body = await _json_body(request, limit=8192)
    where = usage_mod.page_of(request.headers.get("Referer", ""), request.host)
    evs = usage_mod.clean_batch(body, int(time.time() * 1000)) if body is not None and where else []
    n = _usage_take(app, pk, len(evs)) if evs else 0
    if n:
        page, ref = where
        app["events"].add_many([{"ts_ms": e["ts"], "pubkey": pk, "event": "ui", "name": e["name"], "page": page,
                                 **({"ref": ref} if ref else {}), **e["p"]} for e in evs[:n]])
    return web.Response(status=204)


@_acct_route
async def me_add_analysis(request, pk):
    app = request.app
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    job, err = await _visible_job(request, body)
    if err:
        return err
    rows, sm = await _rows_async(app, job.result, "all")
    try:
        added, total = app["accounts"].add_analysis(pk, job.id, _analysis_snapshot(job, rows, sm))
    except acct_mod.AccountError as e:
        return _jerr(str(e))
    if added:
        app["events"].add(pk, "save_analysis", job=job.id, symbol=job.symbol)
    return web.json_response({"ok": True, "added": added, "total": total})


@_acct_route
async def me_remove_analysis(request, pk):
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    ok = request.app["accounts"].remove_analysis(pk, str(body.get("job") or ""))
    if ok:
        request.app["events"].add(pk, "remove_analysis", job=str(body.get("job") or "")[:80])
    return web.json_response({"ok": ok})


def _account_view(app, pk):
    a = app["accounts"].load(pk)
    wallets = sorted((dict(v, wallet=w) for w, v in a["wallets"].items()), key=lambda v: v.get("added_ms") or 0, reverse=True)
    analyses = sorted((dict(v, job=j) for j, v in a["analyses"].items()), key=lambda v: v.get("added_ms") or 0, reverse=True)
    return a, wallets, analyses


@_acct_route
async def me_json(request, pk):
    a = request.app["accounts"].load(pk)
    return web.json_response({"pubkey": pk, "short": _short(pk), "wallets": a["wallets"], "analyses": a["analyses"],
                              "lists": a["lists"]}, headers={"Cache-Control": "no-store"})


async def me_page(request):
    pk, demo = request.get("acct"), _demo(request.app)
    if not pk:
        return render("me.html", request, wallets=[], analyses=[], max_my_tags=acct_mod.MAX_MY_TAGS)
    a, wallets, analyses = _account_view(request.app, pk)
    lists = [dict(v, id=k, n=sum(1 for w in wallets if k in (w.get("lists") or []))) for k, v in a["lists"].items()]
    _view(request, "me")
    return render("me.html", request, wallets=wallets, analyses=analyses, max_my_tags=acct_mod.MAX_MY_TAGS,
                  demo_mint=(demo or {}).get("mint"), lists=lists, max_lists=acct_mod.MAX_LISTS, TAGS=tags.DEFS)


async def admin_demo(request):
    """Адмін робить готовий аналіз демо-токеном: знімок свічок і результату, і демо перемикається одразу.

    Свічки за все життя токена — десяток запитів, один раз. Далі демо програється без жодного запиту, як і раніше."""
    app = request.app
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    pk = request.get("acct")
    if not pk or pk not in app["admins"]:
        return _jerr("Only the owner's wallet can choose the demo.", 403)
    body = await _json_body(request) or {}
    job = app["jobs"].get(str(body.get("job") or ""))
    if not job or job.status != "done" or not job.result or job.replay:
        return _jerr("Choose a finished analysis.", 400)
    st, d = app["st"], str(Path(app["jobs"].dir).parent / "demo")

    def work():
        with st.meter():
            req0 = st.requests_here()
            try:
                _, first = demo_mod.capture(st, [job.to_dict()], d, chart_fn=pipeline._chart, log=lambda m: log.info("demo: %s", m))
                demo_mod.write_override(d, first)
                st.flush()
                return first
            finally:
                _spend(app, pk, "demo", st=st.requests_here() - req0, job=job.id)
    try:
        first = await asyncio.to_thread(work)
    except Exception as e:  # noqa: BLE001
        log.warning("demo capture %s: %s", job.id, e)
        return _jerr("Could not make the demo: " + str(e)[:120], 502)
    app.pop("demo", None)                                   # наступна сторінка прочитає новий знімок
    app["events"].add(pk, "set_demo", job=first, symbol=job.symbol)
    return web.json_response({"ok": True, "job": first, "mint": job.mint})


async def wallet_age_json(request):
    """Вік і перший спонсор одного гаманця, коли відкрили його картку.

    Сам аналіз перевіряє повністю лише перших за PnL (age_full_top), решту — дешево, бо кожен виклик коштує кредитів
    RPC. Чого дешева перевірка не дочитала (вік зайнятого гаманця, спонсора гаманця застосунку) і гаманці старших
    результатів — тут, по одному, коли хтось справді дивиться: 1-3 виклики ноди, тиждень у кеші, і відповідь лягає
    в результат для всіх.

    `checked: false` — сервер цього гаманця не перевіряв (демо, пауза бюджету, денна стеля карток): сторінка каже
    «не перевірено», а не «історії нема». Демо і його програвання спільні для всіх і лише читаються."""
    app, s = request.app, request.app["s"]
    job = app["jobs"].get(request.query.get("job", ""))
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    wallet = request.query.get("wallet", "")
    if not MINT_RE.match(wallet):
        raise WebError("That does not look like a wallet address.")
    r = job.result
    rows = r.get("rows") or []
    row = next((x for x in rows if x.get("wallet") == wallet), None)
    if row is None:
        raise web.HTTPNotFound(text="That wallet is not in this analysis.")
    ages = app.get("ages")
    cached = await asyncio.to_thread(ages.cached, wallet) if ages is not None else None   # вік з кешу нічого не коштує; замок кешу — не на циклі подій
    pending = await asyncio.to_thread(ages.funder_pending, wallet) if ages is not None else False   # дешева перевірка не шукала далі першої транзакції
    stored = (r.get("ages") or {}).get(wallet)
    demo_ids = _demo_job_ids(app)
    shared = bool(job.replay) or job.id in demo_ids or (job.canon or "") in demo_ids   # демо спільне для всіх: лише читається

    def age_of(a):
        return {"ms": a["oldest_ms"], "exact": bool(a.get("exact")), "n": a.get("n")} if a and a.get("oldest_ms") else None

    def best_age():
        # точний вік кращий за «щонайменше»: кеш міг дочитати історію глибше, ніж пам'ятає результат. Вік, за яким
        # гаманець народився після власної покупки, хибний: його не показуємо, картка перечитає
        c = age_of(cached)
        st = None if stored and _after_buy({"exact": stored.get("exact"), "oldest_ms": stored.get("ms")}, row) else stored
        if c and _after_buy(cached, row):
            c = None
        if st and (st.get("exact") or not (c and c["exact"])):
            return st
        return c or st

    def known(**extra):
        out = {"age": best_age(), "funder": (r.get("funders") or {}).get(wallet), "bundle": (r.get("bundle") or {}).get(wallet),
               "fresh": "fresh" in (row.get("tag_list") or []), "checked": stored is not None or cached is not None}
        return web.json_response(dict(out, **extra))
    if ages is None:
        return known()
    now_age = best_age()
    # зайнятий гаманець: 6 000 останніх транзакцій не дійшли до першої. Картку відкрили — гортаємо глибше, один раз
    busy = bool(now_age) and not now_age.get("exact") and not (cached or {}).get("deep")
    bad_cached = _after_buy(cached, row)                 # кеш каже «народився після покупки»: перечитати
    reread = bad_cached or (cached is None and stored is not None and now_age is None)
    if not busy and not pending and not reread and (stored is not None or wallet in set(r.get("funder_checked") or []) or shared):
        return known()
    pk = request.get("acct")
    settle = None
    if cached is None or busy or pending or reread:     # платний шлях: ці виклики ноди ще не робились
        if ages.paused():
            _limit(app, pk, "age-card", "month")
            return known(checked=False, paused=True)
        if not pk:
            raise ConnectRequired(message="Connect a wallet to check this wallet's age and funder.")
        who = None
        if pk not in app["admins"]:
            # своя стеля для карток, окремо від графіків: глибоке читання — одна картка з тих самих 50 на день
            daily, who = app["browse_daily"], "age:acct:" + pk
            mine = daily.left(who, s.get("age_card_per_day", 50)) <= 0
            if mine or daily.left("age:global", s.get("age_card_global_per_day", 500)) <= 0:
                _limit(app, pk, "age-card", "wallet" if mine else "site")
                return known(checked=False, capped=True)
        settle = _browse_budget(request, 1)
        if who:
            daily.add(who, 1)
            daily.add("age:global", 1)

    def work():                                         # кеш віку пише себе кожні 25 записів і при зупинці сервера
        with wallet_age_mod.rpc_meter() as m:
            try:
                age = ages.oldest_tx_deep(wallet) if busy else ages.oldest_tx(wallet, refresh=bad_cached)
                fund = ages.funder(wallet, age["oldest_sig"]) if age.get("exact") and age.get("oldest_sig") else None
                svc = None                              # цей спонсор замикає бандл: біржа чи застосунок?
                if fund and hasattr(ages, "is_service") and list((r.get("funders") or {}).values()).count(fund) + 1 >= tags.BUNDLE_MIN:
                    svc = ages.is_service(fund)
                return age, fund, svc
            finally:
                _spend(app, pk, "card-age", rpc=m["credits"], job=job.canon or job.id)
    try:
        age, fund, svc = await asyncio.to_thread(work)
    except Exception as e:  # noqa: BLE001
        log.warning("wallet age %s: %s", wallet[:8], e)
        raise WebError("The chain node did not answer. Try again in a minute.", 502)
    finally:
        if settle:
            settle(1)
    if shared:                                          # демо не змінюємо: відповідь — лише цій людині, кеш — для всіх
        return web.json_response({"age": age_of(age), "funder": fund, "bundle": (r.get("bundle") or {}).get(wallet),
                                  "fresh": "fresh" in (row.get("tag_list") or []), "checked": True})
    if age and age.get("oldest_ms"):
        r.setdefault("ages", {})[wallet] = age_of(age)
        stored = r["ages"][wallet]
        if tags.is_fresh(row.get("first_buy_ms"), age) and "fresh" not in (row.get("tag_list") or []):
            row["tag_list"] = tags.with_tag(row.get("tag_list"), "fresh")
            row["tags"] = "|".join(row["tag_list"])
            fw = r.setdefault("fresh_wallets", [])       # як у збагаченні: звідси тег бачать експорт, агент і списки
            if wallet not in fw:
                fw.append(wallet)
    if fund:
        r.setdefault("funders", {})[wallet] = fund
        if svc:
            r["services"] = sorted(set(r.get("services") or []) | {fund})
        _bundles(r, rows)                                   # новий спонсор може замкнути бандл з уже відомими
    r["funder_checked"] = sorted(set(r.get("funder_checked") or []) | {wallet})
    _save_soon(app, job)
    return known(checked=True)


AGE_SAVE_S = 30


def _save_soon(app, job):
    """Картка дописала вік у результат. Файл аналізу — мегабайти, тож з карток він пишеться не частіше ніж раз на
    AGE_SAVE_S: перша зміна — одразу, решта вікна — одним записом у кінці (збагачення зберігає і саме)."""
    saves = app["age_saves"]
    if job.id in saves["waiting"]:
        return                                              # запис уже чекає і візьме й цю зміну
    delay = max(0.0, saves["last"].get(job.id, 0) + AGE_SAVE_S - time.monotonic())

    async def later():
        await asyncio.sleep(delay)
        saves["waiting"].pop(job.id, None)                  # зміна під час запису замовить наступний
        saves["last"][job.id] = time.monotonic()
        try:
            await asyncio.to_thread(app["jobs"]._save, job, True)
        except Exception as e:  # noqa: BLE001 — відповідь уже є в пам'яті; збережеться з наступним записом
            log.warning("wallet age save %s: %s", job.id, e)
    task = asyncio.get_running_loop().create_task(later())
    saves["waiting"][job.id] = (job, task)
    saves["tasks"].add(task)                                # цикл подій тримає задачі лише слабко
    task.add_done_callback(saves["tasks"].discard)


async def _admin_json(request, limit=32_768):
    """Тіло запиту адміна або відповідь-відмова."""
    app = request.app
    pk = request.get("acct")
    if not app["admins"] or not pk or pk not in app["admins"]:
        return None, None, _jerr("Only the owner's wallet can change the agent.", 403)
    if not _same_origin(request):
        return None, None, _jerr("Requests must come from this site.", 403)
    body = await _json_body(request, limit=limit)
    if body is None:
        return None, None, _jerr("Bad request body.")
    return pk, body, None


async def admin_agent_save(request):
    """Нова версія методики агента: одразу для всіх нових карток і питань (зроблені картки лишаються під своєю версією)."""
    pk, body, err = await _admin_json(request)
    if err:
        return err
    cfg = request.app["agent_store"].save(body, by=pk)
    request.app["events"].add(pk, "agent_method", v=cfg["v"])
    return web.json_response({"ok": True, "config": cfg})


async def admin_agent_preview(request):
    """Картки демо з методикою, яку власник ще не зберіг: побачити різницю до збереження. Нічого не кешується."""
    app = request.app
    pk, body, err = await _admin_json(request)
    if err:
        return err
    if app.get("agent") is None:
        return _jerr("The agent is not switched on on this server: set ASSISTANT_KEY in .env.", 503)
    demo = _demo(app)
    if not demo or not demo.get("ranges"):
        return _jerr("There is no demo to try it on.", 404)
    rng = next((r for r in demo["ranges"] if r["job"] == body.get("job")), demo["ranges"][0])
    cfg = dict(agent_mod.normalize_config(body.get("config") or {}), v="preview")
    lang, t0 = agent_mod.lang_name(body.get("lang")), time.monotonic()
    try:
        cards, dropped, usage = await asyncio.to_thread(app["agent"].cards, rng["result"], cfg, lang)
    except assistant_mod.AssistantError as e:
        _agent_event(app, pk, "preview", rng["job"], t0, usage=e.usage, ok=0, err=str(e)[:80], lang=lang)
        return _jerr(str(e), 502)
    app["agent_store"].log({"pk": pk, "job": rng["job"], "kind": "preview", "lang": lang, "dropped": dropped, "usage": usage,
                            "model": cards.get("model")})
    _agent_event(app, pk, "preview", rng["job"], t0, usage=usage, ok=1, dropped=len(dropped) or None, lang=lang)
    return web.json_response({"cards": cards, "dropped": dropped, "usage": usage, "range": rng.get("label")})


async def admin_page(request):
    """Хто підключився і що робив. Лише для гаманців з ADMIN_WALLETS; без них сторінки не існує."""
    app = request.app
    if not app["admins"]:
        raise web.HTTPNotFound(text="Not configured.")
    pk = request.get("acct")
    if not pk or pk not in app["admins"]:
        return render("error.html", request, message="This page is for the owner's wallet. Connect it first.", status=403)
    accounts = app["accounts"].all()
    now, week = int(time.time() * 1000), int(time.time() * 1000) - 7 * 86_400_000
    totals = {"accounts": len(accounts),
              "new_7d": sum(1 for a in accounts if (a.get("created_ms") or 0) >= week),
              "active_7d": sum(1 for a in accounts if (a.get("last_seen_ms") or 0) >= week),
              "wallets": sum(len(a.get("wallets") or {}) for a in accounts),
              "analyses": sum(len(a.get("analyses") or {}) for a in accounts)}
    left = await _credits_left(app)
    ages = app.get("ages")
    budget = {"credits_left": left, "credits_at": int(app["credits"]["at"] * 1000) or None,
              "credits_month": int(app["s"].get("credits_month", 0) or 0), "reserve": _credits_reserve(app["s"]),
              "runs_today": int(app["s"].get("runs_global_per_day", 10)) - app["runs_daily"].left("global", int(app["s"].get("runs_global_per_day", 10))),
              "rpc": ages.budget.state() if ages is not None and getattr(ages, "budget", None) else None}
    store = app["agent_store"]
    return render("admin.html", request, accounts=accounts, totals=totals, events=app["events"].tail(100), now=now, budget=budget,
                  agent_cfg=store.config(), agent_history=store.history(10), agent_log=store.recent(50),
                  agent_on=app.get("agent") is not None, agent_model=getattr(app.get("assistant"), "model", ""),
                  excludable=agent_mod.EXCLUDABLE, default_method=agent_mod.DEFAULT_METHOD)


ME_COLUMNS = ["wallet", "symbol", "mint", "from_job", "entry_mcap", "invested_usd", "multiple", "tags", "my_tags", "lists", "added_utc"]


@_acct_route
async def me_wallets_csv(request, pk):
    a, wallets, _ = _account_view(request.app, pk)
    only = request.query.get("list")                                    # ?list=<id> — один список
    if only:
        wallets = [w for w in wallets if only in (w.get("lists") or [])]
    names = {k: v["name"] for k, v in a["lists"].items()}
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ME_COLUMNS, extrasaction="ignore")
    w.writeheader()
    def cell(v):                                                        # таблиці виконують клітинки з = + - @ як формули
        return "'" + v if isinstance(v, str) and v[:1] in "=+-@\t\r" else ("" if v is None else v)
    for r in wallets:
        w.writerow({**{k: cell(r.get(k)) for k in ME_COLUMNS},
                    "tags": "|".join(r.get("tags") or []), "my_tags": "|".join(r.get("my_tags") or []),
                    "lists": cell("|".join(names.get(x, x) for x in r.get("lists") or [])),
                    "added_utc": chart.fmt_dt(r.get("added_ms") or 0, year=True, utc=True)})
    request.app["events"].add(pk, "export", format="csv", what="list" if only else "lists")
    return web.Response(text=buf.getvalue(), content_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="watchlist.csv"'})


# ───────────────────────── helpers ─────────────────────────

def render(name, request, status=200, **ctx):
    ctx.setdefault("request", request)
    acct = request.get("acct") if request is not None else None
    ctx.setdefault("acct", acct)
    ctx.setdefault("acct_short", _short(acct) if acct else "")
    if request is not None:
        ctx.setdefault("s", request.app["s"])                   # квоти в текстах беруться з налаштувань, не з голови
        ctx.setdefault("demo_token", (_demo(request.app) or {}).get("mint", ""))   # підвал веде на демо, якщо воно є
        ctx.setdefault("assistant_on", request.app.get("assistant") is not None)   # без ключа сторінки не обіцяють агента
        ctx.setdefault("early_note", EARLY_NOTE)
    ctx.setdefault("umami_id", os.getenv("UMAMI_WEBSITE_ID", ""))   # аналітика вмикається лише там, де задано id
    ctx.setdefault("umami_domains", os.getenv("UMAMI_DOMAINS", "tracced.xyz,www.tracced.xyz"))   # і лише на цих доменах: локальні запуски з тим самим id не рахуються
    html = env.get_template(name).render(**ctx)
    return web.Response(text=html, content_type="text/html", status=status)


def _mint(v):
    v = (v or "").strip()
    if not MINT_RE.match(v):
        raise WebError("This doesn't look like a Solana token address (32–44 base58 characters).")
    return v


async def _overview(app, mint, charge=None, who=None):
    """token_info + detector hints, cached in memory for 10 minutes (a failure for 2, so a bad address is not bought
    again on every hit). Concurrent viewers of one new token share a single load. `charge(n)` gets the number of
    requests that really went out, success or failure; the usage log gets them too, on `who` (a wallet or a guest)."""
    cache = app["overview_cache"]
    hit = cache.get(mint)
    if hit and time.time() - hit[0] < (OVERVIEW_TTL if hit[1] is not None else OVERVIEW_FAIL_TTL):
        if hit[1] is None:
            raise WebError(hit[2])
        return hit[1], hit[2]
    pending = app["overview_pending"]
    fut = pending.get(mint)
    if fut is not None:                                                 # хтось уже вантажить цей токен: чекаємо на нього
        return await asyncio.shield(fut)
    fut = pending[mint] = asyncio.get_running_loop().create_future()
    st, s = app["st"], app["s"]

    def load():
        with st.meter():                                  # лічильник саме цієї сторінки, не прогону поруч
            req0 = st.requests_here()
            try:
                info = pipeline.token(st, mint)
                ov = pipeline.overview(st, mint, info, s, app["cfg"])   # кеш свічок пише себе сам і при зупинці сервера
                return info, {"interval": ov["interval"], "hints": ov["hints"]}   # свічки не тримаємо: з кешу їх ніхто не читає
            finally:
                n = st.requests_here() - req0
                if charge:
                    charge(n)
                _spend(app, who, "overview", st=n, mint=mint)
    try:
        try:
            info, ov = await asyncio.to_thread(load)
        except pipeline.EarlyError as e:
            raise WebError(str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("overview %s: %s", mint[:8], e)
            raise WebError("Solana Tracker returned no data for this token. Check the address or try again later.")
    except WebError as e:
        cache[mint] = (time.time(), None, str(e))
        fut.set_exception(e)
    else:
        cache[mint] = (time.time(), info, ov)
        fut.set_result((info, ov))
    finally:
        pending.pop(mint, None)
        _prune_overview(cache)
    return await fut


# ───────────────────────── pages ─────────────────────────

def _home_data(jobs):
    """Totals, the sample job and background lines for the home page — from stored results only."""
    done = [j for j in jobs if j.status == "done" and j.result]
    totals = {"wallets": sum((j.result.get("counts") or {}).get("n_early", 0) for j in done),
              "tokens": len({j.mint for j in done}),
              "trades": sum((j.result.get("counts") or {}).get("n_trades", 0) for j in done)}
    sample = next((j for j in done if j.result.get("mode") == "trades" and j.result.get("rows")), None) \
        or next((j for j in done if j.result.get("rows")), None)
    lines = []
    if sample:
        for r in (sample.result.get("rows") or [])[:16]:
            if r.get("first_buy_ms") and r.get("invested_in_range_usd"):
                lines.append(f"{r['wallet'][:4]}…{r['wallet'][-4:]}  buy  {_usd(r['invested_in_range_usd'])}  @ "
                             f"{chart.fmt_mcap(r.get('entry_mcap_avg'))}  {chart.fmt_dt(r['first_buy_ms'])}")
    return totals, sample, lines


def _replay(job, page_size=250, budget_s=12.0):
    """Demo: play a believable run built from the stored result's own numbers, then return that result (0 requests).

    The replay shows the snapshot's own result object, not a copy: nothing writes to a replay (no enrichment, no names,
    no saves, and the card treats it as read-only), and a copy per press cost 5-25 MB each."""
    return replay.play(job, job.replay["result"], job.t_from, job.t_to, page_size=page_size, budget_s=budget_s)


def _demo_ranges(snap):
    """Ranges of a snapshot as one list, whichever way it was written (one range, or several)."""
    if snap.get("ranges"):
        return [r for r in snap["ranges"] if r.get("job") and r.get("result") and r.get("from") and r.get("to")]
    r = snap.get("range") or {}
    if snap.get("job") and snap.get("result") and r.get("from"):
        return [{"label": "Demo range", "from": r["from"], "to": r["to"], "job": snap["job"],
                 "log": snap.get("log") or [], "result": snap["result"]}]
    return []


def _demo(app):
    """Snapshot of the demo token: info, candles, and every recorded range with its log and result.

    Read straight from output/early/demo/<mint>.json, which the app never writes. Nothing here depends on the
    job files, so a restart in the middle of a replay cannot turn the demo token back into a live, paid run.
    """
    if "demo" in app:
        return app["demo"]
    app["demo"] = None
    d = Path(app["jobs"].dir).parent / "demo"
    jid = demo_mod.read_override(str(d)).get("demo_job") or app["s"].get("demo_job")   # вибір адміна сильніший за конфіг
    if jid and d.is_dir():
        from ..early.report import upgrade_result
        for path in sorted(d.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    snap = json.load(f)
            except Exception as e:  # noqa: BLE001
                log.warning("demo snapshot unreadable: %s", e)
                continue
            ranges = _demo_ranges(snap)
            if not snap.get("mint") or not any(r["job"] == jid for r in ranges):
                continue
            for r in ranges:
                upgrade_result(r["result"])                # знімок міг бути зроблений до перейменувань
            snap["ranges"], snap["job_id"] = ranges, jid
            app["demo"] = snap
            break
    return app["demo"]


def _by_token(jobs, example_id=None):
    """Один запис на токен: скільки діапазонів по ньому проаналізовано і що з них вийшло.

    На головній цікавий токен, а не окремий прогін: рядок веде на сторінку токена, де діапазони видно
    на графіку і кожен відкривається своїм результатом.
    """
    groups = {}
    for j in jobs:
        groups.setdefault(j.mint, []).append(j)
    out = []
    for mint, js in groups.items():
        done = [j for j in js if j.status == "done" and j.result]
        best = max(((j.result.get("summary") or {}).get("best_multiple") or 0 for j in done), default=0)
        out.append({
            "mint": mint,
            "symbol": next((j.symbol for j in js if j.symbol), mint[:6]),
            "ranges": len(js),
            "t_from": min(j.t_from for j in js),
            "t_to": max(j.t_to for j in js),
            "best": best,
            "status": "running" if any(j.status in ("queued", "running") for j in js) else ("done" if done else "error"),
            "example": any(j.id == example_id for j in js),
            "at": max(j.created_ms or 0 for j in js),
        })
    out.sort(key=lambda g: (not g["example"], -g["at"]))               # приклад першим, далі найсвіжіші
    return out


async def index(request):
    app = request.app
    jobs = app["jobs"].recent(60)
    jobs = [j for j in jobs if j.status != "error"]                    # помилки на головній — шум
    totals, sample, lines = _home_data(jobs)
    want = (demo_mod.read_override(str(Path(app["jobs"].dir).parent / "demo")).get("example_job")
            or app["s"].get("example_job") or "")
    example = app["jobs"].get(want) if want else None
    if not example or example.status != "done":
        done = [j for j in jobs if j.status == "done" and j.result and j.result.get("rows")]
        example = min(done, key=lambda j: j.created_ms or 0) if done else None      # найстарший готовий = показовий
    my_n = len(app["accounts"].load(request["acct"])["analyses"]) if request.get("acct") else 0
    _view(request, "home")
    return render("index.html", request, tokens=_by_token(jobs, example.id if example else None),
                  totals=totals, sample=sample, bg_lines=lines, my_n=my_n)


async def docs_page(request):
    """Документація: markdown з docs/ поруч із кодом, той самий деплой, те саме оформлення сайту."""
    slug = request.match_info.get("slug") or "index"
    body, title = docs_mod.page(DOCS_DIR, slug, {"s": request.app["s"], "TAGS": tags.DEFS, "assistant_on": request.app.get("assistant") is not None})
    if body is None:
        raise web.HTTPNotFound(text="There is no such page in the documentation.")
    prev, nxt = docs_mod.around(DOCS_DIR, slug)
    _view(request, "docs", slug)
    return render("docs.html", request, body=body, title=title, nav=docs_mod.nav(DOCS_DIR, slug), prev=prev, nxt=nxt)


async def how(request):
    raise web.HTTPFound("/docs/how-it-works")      # один опис, а не два, що розходяться


async def project(request):
    raise web.HTTPFound("/docs/project")      # сторінка проєкту живе в документації, а не окремим островом


async def token_page(request):
    app = request.app
    mint = _mint(request.query.get("mint"))
    s = app["s"]
    demo = _demo(app)
    pk = request.get("acct")                                            # гість бачить графік і ставить межі; гаманець потрібен для Analyze
    hints = []                                                          # для «Find the pump»: підказки детектора (демо — записані діапазони)
    if demo and demo["mint"] == mint:                                   # демо-токен: усе зі знімка, 0 запитів
        info = demo["info"]
        rows = [{"n": i + 1, "label": r.get("label") or f"Demo range {i + 1}", "job": r.get("job"),
                 "from": chart.to_input(r["from"]), "to": chart.to_input(r["to"])}
                for i, r in enumerate(demo["ranges"])]
    else:
        info, ov = await _overview(app, mint, _browse_budget(request, 2) if not _overview_cached(app, mint) else None, pk)   # огляд ≈2 запити, кеш — 0
        rows = []                                                       # голий графік: діапазони ставить людина або кнопка
        hints = [{"from": h["acc_start"], "to": h["pump_start"], "base": h["base_mcap"], "peak": h["peak_mcap"], "mag": h["magnitude"]}
                 for h in ov["hints"][: int(s.get("finder_pumps", 2))]]
    detect_cfg = dict(CFG_DEFAULTS.get("detect") or {}, **((app["cfg"] or {}).get("detect") or {}))
    q = request.query
    preset = None
    admin = bool(pk) and pk in app["admins"]
    runs_left, runs_why = _runs_left(app, pk, _device_id(request), _client_ip(request)) if pk and not admin else (None, None)
    notice = q.get("notice") if q.get("notice") in ("limit", "netcap", "sitecap") else None   # Analyze bounced off a daily cap
    if notice in ("limit", "netcap") and not runs_left == 0:
        notice = None                                   # стара адреса, чуже посилання чи гість: вікно лише тому, кому справді нема
    # яке вікно показати: людина вичерпала свої, мережа — спільні, чи сайт — день
    limit_kind = notice or (("netcap" if runs_why == "network" else "limit") if runs_left == 0 else None)
    if chart.from_input(q.get("from")) and chart.from_input(q.get("to")):
        preset = {"n": None, "label": "Your range" if notice else "From the result", "from": q.get("from"), "to": q.get("to")}
    done_jobs = sorted((j for j in app["jobs"].jobs.values() if j.mint == mint and j.status == "done"),
                       key=lambda j: j.t_from or 0)
    jobs_done = [j.id for j in done_jobs]
    seen = {(r["from"], r["to"]) for r in rows}
    for j in done_jobs:                                 # готові аналізи видно на будь-якому пристрої, не лише там, де їх робили
        key = (chart.to_input(j.t_from), chart.to_input(j.t_to))
        if key in seen:
            continue
        seen.add(key)
        n = ((j.result or {}).get("counts") or {}).get("n_early")
        rows.append({"n": len(rows) + 1, "label": f"Analyzed · {n:,} wallets" if n else "Analyzed",
                     "job": j.id, "from": key[0], "to": key[1],
                     "deletable": bool(pk) and (j.owner == pk or pk in app["admins"])})
    if not rows:
        rows = [{"n": 1, "label": "Range 1", "from": "", "to": ""}]
    _view(request, "token", mint, demo=1 if demo and demo["mint"] == mint else None)
    return render("token.html", request, info=info, mint=mint, s=s, is_demo=bool(demo and demo["mint"] == mint),
                  runs_left=runs_left, notice=notice, limit_kind=limit_kind, reset_ms=_next_midnight_ms(), demo_mint=(demo or {}).get("mint"),
                  n_demo=len(demo["ranges"]) if demo and demo["mint"] == mint else 0, bounced=q.get("notice") == "demo", created=info.get("created_time") or 0, now=int(time.time() * 1000),
                  rows_json=json.dumps(rows), jobs_json=json.dumps(jobs_done), preset_json=json.dumps(preset),
                  hints_json=json.dumps(hints), min_peak=int(detect_cfg.get("min_peak_mcap") or 1_000_000))


async def marks_json(request):
    """Події життя токена для графіка: коли торгівля переїхала з лаунчпада і коли платили DexScreener.

    Міграція вже лежить у відповіді про токен, за яку заплачено при аналізі, тож нових запитів до Solana Tracker
    нема. DexScreener — чужий публічний ендпоінт без ключа, відповідь кешується на добу; якщо він мовчить,
    повертається порожній список і графік просто малюється без цих міток."""
    app = request.app
    mint = _mint(request.query.get("mint"))
    out = {"migration": None, "paid": []}
    job = app["jobs"].get(request.query.get("job", "")) if request.query.get("job") else None
    info = ((job.result or {}).get("info") if job and job.result else None) or {}
    if not info.get("migration"):
        demo = _demo(app)                                     # демо живе зі знімка і не робить запитів
        if demo and demo.get("mint") == mint:
            info = demo.get("info") or {}
    if not info.get("migration"):
        hit = app["overview_cache"].get(mint)                 # огляд уже куплений кимось — беремо звідти
        info = (hit[1] if hit and hit[1] is not None else None) or {}
    if info.get("migration") and (info.get("mint") == mint or job):
        out["migration"] = info["migration"]
    if info.get("pools") and (info.get("mint") == mint or job):
        out["pools"] = info["pools"]                          # де токен торгувався: для пояснення графіка
    hit = app["overview_cache"].get(mint)
    known = (_is_demo_mint(app, mint) or (hit and hit[1] is not None)
             or any(j.mint == mint for j in list(app["jobs"].jobs.values())))
    if not known:                                             # чужу адресу DexScreener за наш рахунок не питаємо
        out.pop("paid")
        return web.json_response(out, headers={"Cache-Control": "public, max-age=600"})
    out["paid"] = await asyncio.to_thread(dexscreener.orders, mint, app.get("dex_cache"))
    return web.json_response(out, headers={"Cache-Control": "public, max-age=600"})


async def candles_json(request):
    """Market-cap candles for the browser chart: ?mint&tf&a&b (a, b in unix seconds). Open to everyone; a live token's
    chunks cost a request each, so they count against the day's chart budget (cached chunks are free)."""
    app = request.app
    q = request.query
    mint = _mint(q.get("mint"))
    tf = q.get("tf") if q.get("tf") in chart.TFS else "1h"
    try:
        a, b = int(float(q.get("a", 0))), int(float(q.get("b", 0)))
    except (ValueError, OverflowError):
        raise WebError("Bad time range.")
    if b <= a:
        return web.json_response([])
    demo = _demo(app)
    if demo and demo["mint"] == mint:
        cs = [c for c in (demo.get("candles") or {}).get(tf) or [] if a * 1000 <= c["time"] <= b * 1000]
        ours = await asyncio.to_thread(_trade_candles, app, mint)
        return web.json_response(chart.fill_gaps(chart.candles_mcap(cs, demo["info"]["supply"]), ours, a, b, tf, demo["info"]["supply"]))
    st = app["st"]
    info, _ = await _overview(app, mint, _browse_budget(request, 2) if not _overview_cached(app, mint) else None, request.get("acct"))
    now = int(time.time())
    created = int((info.get("created_time") or 0) // 1000)
    a, b = chart.snap_range(max(a, created - 3600), min(b, now + 3600), tf)
    a = max(a, b - chart.TF_SEC[tf] * MAX_CANDLES)      # Solana Tracker truncates a huge span without saying so and
    if b <= a:                                          # returns only the newest slice; keep every request answerable
        return web.json_response([])
    # замок кешу клієнта буває зайнятий записом файлів з інших потоків: перевірка йде в потоці, не в циклі подій
    cached = await asyncio.to_thread(st.chart_cached, mint, tf, a * 1000, b * 1000)
    settle = _browse_budget(request, 1) if not cached else None   # шматок = 1 запит

    who = request.get("acct")

    def load():
        with st.meter():
            req0 = st.requests_here()
            try:
                return pipeline._chart(st, mint, tf, a * 1000, b * 1000, info)   # кеш запише себе сам і при зупинці
            finally:
                n = st.requests_here() - req0
                if settle:
                    settle(n)
                _spend(app, who, "chart", st=n, mint=mint)
    candles = await asyncio.to_thread(load)
    out = chart.candles_mcap(candles, info["supply"])
    ours = await asyncio.to_thread(_trade_candles, app, mint)        # діри джерела — з угод, які ми вже маємо
    return web.json_response(chart.fill_gaps(out, ours, a, b, tf, info["supply"]))


def _trade_candles(app, mint):
    """Наші хвилинні свічки токена з диска, у пам'яті, доки файл не змінився (новий аналіз його переписує)."""
    from ..early.store import candles_path, load_candles
    path = candles_path(app["store_dir"], mint)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    memo = app.setdefault("trade_candles", {})
    hit = memo.get(mint)
    if hit and hit[0] == mtime:
        return hit[1]
    data = load_candles(app["store_dir"], mint)
    if len(memo) > 50:
        memo.clear()
    memo[mint] = (mtime, data)
    return data


def _demo_replay(request, ip, mint, r, demo):
    """Куди веде Analyze на записаному діапазоні демо: на програвання, а коли нове не на часі — на сам результат.

    Програвання безкоштовне, але кожне тримає потік ~12 с і пам'ять, тож: та сама адреса з тим самим діапазоном, поки
    її програвання ще йде, повертається до нього; нове — лише з цього сайту і не частіше за `demo_replays_per_10min`.
    Інакше — збережений результат одразу, без програвання."""
    app, jobs = request.app, request.app["jobs"]
    mine, key = app["demo_replays"], (ip, r["job"])

    def playing(jid):
        j = jobs.get(jid or "")
        return bool(j) and j.status in ("queued", "running")
    if playing(mine.get(key)):
        return f"/job/{mine[key]}"
    stored = jobs.get(r["job"])
    now, th = time.time(), app["demo_runs"]
    if not _same_origin(request) or th.wait_s(ip, now):
        if stored and stored.status == "done" and stored.result:
            return f"/job/{stored.id}"
        if not _same_origin(request):
            raise WebError("Requests must come from this site.", 403)
        raise WebError(_wait_text(th.wait_s(ip, now)), 429)
    th.miss(ip, now)
    job = jobs.submit(mint, r["from"], r["to"], symbol=demo["info"].get("symbol"),
                      replay={"log": list(r.get("log") or []), "result": r["result"]})
    if len(mine) > 1000:                                                # прибираємо ті, що вже відіграли
        for k in [k for k, jid in mine.items() if not playing(jid)]:
            mine.pop(k, None)
    mine[key] = job.id
    return f"/job/{job.id}"


async def analyze(request):
    """Demo ranges replay for everyone and an existing result opens for everyone. A new live run needs a connected
    wallet: a token holds at most `ranges_per_token` analyses, a wallet gets `runs_per_day` runs a day, and one run
    may spend at most `run_cap_requests` — none of that applies to the admin wallets."""
    app, s = request.app, request.app["s"]
    ip = _client_ip(request)
    form = await request.post()
    mint = _mint(form.get("mint"))
    t_from, t_to = chart.from_input(form.get("from")), chart.from_input(form.get("to"))
    demo = _demo(app)
    if demo and demo["mint"] == mint:
        for r in demo["ranges"]:                                        # демо: програємо збережений аналіз зі знімка
            if t_from and t_to and abs(t_from - r["from"]) <= 60_000 and abs(t_to - r["to"]) <= 60_000:
                raise web.HTTPFound(_demo_replay(request, ip, mint, r, demo))
        raise web.HTTPFound(f"/token?mint={mint}&notice=demo")           # інший діапазон — без живого (платного) прогону

    def same_range():
        """Той самий діапазон уже є (іде чи готовий): відкриваємо його, без витрат і без гаманця."""
        cur = app["jobs"].get(make_id(mint, t_from, t_to)) if (t_from and t_to) else None
        if cur and cur.mint != mint:                                    # id збігся у двох токенів з однаковим початком адреси
            raise WebError("Another token with a similar address already holds this exact range. Shift a bound by a minute.")
        if cur and (cur.status in ("queued", "running") or (cur.status == "done" and cur.result)):
            raise web.HTTPFound(f"/job/{cur.id}")
        return cur
    cur = same_range()
    pk = request.get("acct")
    admin = bool(pk) and pk in app["admins"]
    cap_tok = int(s.get("ranges_per_token", 3))                         # усе, що можна перевірити до гаманця, — до гаманця
    others = [j for j in app["jobs"].jobs.values() if j.mint == mint and j.status != "error" and not j.replay and j is not cur]
    if len(others) >= cap_tok:
        mine = bool(pk) and any(j.owner == pk for j in others)
        _limit(app, pk, "run", "token")
        raise WebError(f"This token already has {cap_tok} analyses. Delete one of yours to add another." if mine or admin else
                       f"This token already has {cap_tok} analyses by other wallets. Open one of them, or ask its owner to free a slot.")
    info, _ = await _overview(app, mint, _browse_budget(request, 2) if not _overview_cached(app, mint) else None, request.get("acct"))
    errs = window.validate(t_from, t_to, info.get("created_time"), int(time.time() * 1000),
                           max_window_ms=int(s.get("max_window_hours", 0) * HOUR) or None)
    if errs:
        raise WebError(" ".join(errs))
    if not pk:                                                          # гість дійшов до Analyze з чинними межами: просимо гаманець, межі не губимо
        raise ConnectRequired(mint, chart.to_input(t_from), chart.to_input(t_to))
    runs = app["runs"]                                                  # платний шлях: спершу гальмо по адресі
    wait = runs.wait_s(ip, time.time())
    if wait:
        _limit(app, pk, "run", "hourly")
        raise WebError(f"Too many analyses from this address. Try again in {max(1, round(wait / 60))} min.", 429)
    back = f"/token?mint={mint}&from={chart.to_input(t_from)}&to={chart.to_input(t_to)}"   # the range survives the notice
    gcap = int(s.get("runs_global_per_day", 10))
    if not admin and app["runs_daily"].left("global", gcap) <= 0:
        _limit(app, pk, "run", "site")
        raise web.HTTPFound(back + "&notice=sitecap")
    reserve = _credits_reserve(s)
    if reserve:
        # the month is what nothing else protected: a run has its cap, the day has its count, but thirty busy days
        # in a row could still spend five times the plan. A run starts only while the worst case of it leaves the reserve.
        left = await _credits_left(app)
        same_range()                                                    # друге натискання під час цього очікування йде на перший прогін, а не в резерв
        worst = int(s.get("run_cap_requests", 0) or 0)
        # runs already queued or running have not spent their worst case yet, and the balance is up to 10 minutes old
        in_flight = sum(1 for j in list(app["jobs"].jobs.values()) if j.status in ("queued", "running") and not j.replay
                        and j.owner and j.owner not in app["admins"])
        if left is not None and left - (in_flight + 1) * worst < reserve:
            if not admin:
                _limit(app, pk, "run", "month")
                raise WebError("This month's data budget is nearly used up, so new live analyses wait until it renews. "
                               "The demo and every saved result stay open.", 503)
            log.warning("admin run with %s credits left (reserve %s)", left, reserve)
    same_range()                                                        # друге натискання, поки перше чекало огляд чи баланс: не платить удруге
    # one person, one day's runs: the wallet, the browser and the network are counted together, so connecting another
    # wallet in the same browser adds nothing. No awaits from here to submit: the check and the charge are one step.
    dev, new_dev, charged = _device_id(request), None, []
    if not admin:
        left_today, why = _runs_left(app, pk, dev, ip)
        if left_today <= 0 and why == "network":
            _limit(app, pk, "run", "network")
            raise web.HTTPFound(back + "&notice=netcap")                # свої ще є, а мережа свої вичерпала: вікно каже саме це
        if left_today <= 0 or not app["accounts"].take_run(pk, int(s.get("runs_per_day", 1))):
            _limit(app, pk, "run", "wallet")
            raise web.HTTPFound(back + "&notice=limit")
        if not dev:
            dev = new_dev = secrets.token_hex(16)
        charged = ["dev:" + dev, _ip_key(ip)]
        for key in charged:
            app["runs_daily"].add(key, 1)
    runs.miss(ip, time.time())                                          # звідси починаються витрати — рахуємо цей запуск
    if not admin:
        app["runs_daily"].add("global", 1)
    over = {"budget_guard_pct": 0, "run_cap_requests": 0 if admin else int(s.get("run_cap_requests", 2000))}
    job = app["jobs"].submit(mint, t_from, t_to, symbol=info.get("symbol"), owner=pk, s_over=over, charged=charged)
    app["events"].add(pk, "analyze", job=job.id, symbol=info.get("symbol") or mint[:6])
    resp = web.HTTPFound(f"/job/{job.id}")
    if new_dev:
        resp.set_cookie(DEVICE_COOKIE, new_dev, httponly=True, samesite="Lax", secure=True, max_age=DEVICE_DAYS * 86400)
    raise resp


@_acct_route
async def job_crossings_json(request, pk):
    """Гаманці цього аналізу, які вже зустрічались у інших аналізах, збережених САМЕ цією людиною.

    Це наш варіант «розумних грошей», і він відрізняється від чужих міток тим, що перевіряється: значок
    означає рівно «цей гаманець був раннім покупцем у стількох вікнах, які ти сам розмітив і зберіг»,
    з посиланням на кожне. Рахується з уже збережених результатів, жодного запиту до Solana Tracker.
    """
    app = request.app
    job = app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    saved = list((app["accounts"].load(pk).get("analyses") or {}).keys())
    here = {r["wallet"] for r in (job.result.get("rows") or [])}

    def cross():
        out = {}
        for jid in saved:
            other = app["jobs"].get(jid)
            if jid == job.id or not other or other.status != "done" or not other.result:
                continue
            if other.mint == job.mint and other.t_from == job.t_from and other.t_to == job.t_to:
                continue                                   # той самий діапазон під іншим id — не перетин
            for r in other.result.get("rows") or []:
                w = r.get("wallet")
                if w in here:
                    out.setdefault(w, []).append({"job": jid, "symbol": other.symbol, "mint": other.mint,
                                                  "from": other.t_from, "to": other.t_to,
                                                  "mult": r.get("multiple") or 0,
                                                  "real": r.get("realized_usd") or 0})
        return out
    wallets = await asyncio.to_thread(cross)
    return web.json_response({"saved": len(saved), "n": len(wallets), "wallets": wallets},
                             headers={"Cache-Control": "no-store"})


@_acct_route
async def job_delete(request, pk):
    """The wallet that ran an analysis (or an admin) can delete it: the token's slot is free again."""
    app = request.app
    job = app["jobs"].get(request.match_info["id"])
    if not job:
        return _jerr("No such analysis.", 404)
    if job.id in _demo_job_ids(app):
        return _jerr("The demo analyses stay.", 403)
    if job.owner != pk and pk not in app["admins"]:
        return _jerr("Only the wallet that ran this analysis (or the admin) can delete it.", 403)
    if job.status in ("queued", "running"):
        return _jerr("This analysis is still running. Wait for it to finish.", 409)
    await asyncio.to_thread(app["jobs"].remove, job.id)                 # remove чекає на запис файлу, що йде: не на циклі подій
    app["events"].add(pk, "delete_analysis", job=job.id, symbol=job.symbol)
    return web.json_response({"ok": True})


def _hours_text(ms):
    h = ms / HOUR
    return f"{h:.1f}" if h < 1 else f"{h:.0f}"


def _back_link(job):
    return f"/token?mint={job.mint}&from={chart.to_input(job.t_from)}&to={chart.to_input(job.t_to)}"


async def job_page(request):
    app = request.app
    jid = request.match_info["id"]
    job = app["jobs"].get(jid)
    if not job:
        canon = app["jobs"].get(jid[:-8]) if re.search(r"_r[0-9a-f]{6}$", jid) else None
        if canon:
            raise web.HTTPFound(f"/job/{canon.id}")                     # програвання демо вже прибране: показуємо збережений аналіз
        raise web.HTTPNotFound(text="No such analysis.")
    created = ((job.result or {}).get("info") or {}).get("created_time") or 0
    if not created and job.status == "done" and _overview_cached(app, job.mint):   # лише з кешу: сторінка результату нічого не купує
        try:
            info, _ = await _overview(app, job.mint)
            created = info.get("created_time") or 0
        except WebError:
            created = 0
    status, result = job.status, job.result             # знімок: статус міняється з робочого потоку
    sm, sc = None, _scope(request, app["s"])
    if status == "done" and result:
        rows, sm = await _rows_async(app, result, sc)
        result = dict(result, rows=rows)
    else:
        result = None
    is_demo = job.id in _demo_job_ids(app) or (job.canon or "") in _demo_job_ids(app)
    _view(request, "job", job.canon or job.id, state={"done": "done", "error": "err"}.get(status, "run"), demo=1 if is_demo else None)
    return render("job.html", request, job=job, save_id=job.canon or job.id, jstatus=status, result=result, s=app["s"], back=_back_link(job),
                  rows_json=_json_script(_table(result["rows"])) if result else "", bundle_min=tags.BUNDLE_MIN, burst_ms=tags.BURST_MS,
                  max_my_tags=acct_mod.MAX_MY_TAGS, is_admin=bool(request.get("acct")) and request.get("acct") in app["admins"],
                  age_read=wallet_age_mod.MAX_PAGES * wallet_age_mod.LIMIT,   # скільки транзакцій гаманця читає перевірка віку
                  is_demo=is_demo,
                  sm=sm, TAGS=tags.DEFS, created=created or (job.t_from - 24 * HOUR), now=int(time.time() * 1000),
                  cov_text=report.coverage_text((result or {}).get("coverage")), 
                  assistant_on=app.get("assistant") is not None,
                  scope=sc, scopes=scope.scopes_for(app["s"]), has_scopes=bool((result or {}).get("wallet_trades")),
                  scope_end=(scope.end_for(sc, job.t_to, (result or {}).get("window", {}).get("end", 0)) if result else None))


# поля рядка таблиці результату в тому порядку, в якому їх віддає _table
TABLE = ("w", "inv", "invsol", "tot", "totsol", "got", "gotsol", "real", "realsol", "unreal",
         "mult", "sold", "buys", "sells", "hold", "exit", "entry", "etime", "exitcap", "tags", "eavg")


def _rnd(v, digits):
    """Число для таблиці з потрібною точністю; None, NaN і нескінченність стають null."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    x = round(x, digits)
    return int(x) if x == int(x) else x


def _table(rows):
    """Рядки таблиці результату як дані, не як розмітка. Сторінка малює лише видиму сотню, а сортує, фільтрує, виділяє
    й експортує по цих числах. Раніше кожен рядок приходив готовим HTML: на 2 481 гаманці це 5.6 МБ і 75 тисяч
    елементів, від яких сторінка підвисала на телефоні з малою пам'яттю."""
    out = []
    for r in rows:
        has_sol = r.get("invested_in_range_sol") is not None      # результат, збережений до сум у SOL, їх не має зовсім

        def sol(v):
            return _rnd(v or 0, 4) if has_sol else None
        out.append([r["wallet"],
                    _rnd(r.get("invested_in_range_usd") or 0, 2), sol(r.get("invested_in_range_sol")),
                    _rnd(r.get("invested_usd") or 0, 2), sol(r.get("invested_sol")),
                    _rnd(r.get("proceeds_usd") or 0, 2), sol(r.get("proceeds_sol")),
                    _rnd(r.get("realized_usd") or 0, 2), sol(r.get("realized_sol")),
                    _rnd(r.get("unrealized_usd") or 0, 2),
                    _rnd(r.get("multiple") or 0, 4), _rnd(r.get("sold_share_pct") or 0, 1),
                    int(r.get("buys") or 0), r.get("sells"), _rnd(r.get("hold_minutes"), 1),
                    1 if r.get("first_sell_ms") else 0,
                    _rnd(r.get("entry_range_mcap") or r.get("entry_mcap_avg"), 0),
                    int(r.get("first_range_buy_ms") or r.get("first_buy_ms") or 0),
                    _rnd(r.get("exit_mcap_avg"), 0),
                    " ".join(r.get("tag_list") or []),
                    _rnd(r.get("entry_mcap_avg"), 0)])            # «Exit vs entry» ділить на середній вхід усіх купівель, а не на вхід у діапазоні
    return {"f": TABLE, "r": out}


def _json_script(obj):
    """JSON усередині <script type="application/json">: без пробілів, і ніщо в ньому не закриє тег."""
    s = json.dumps(obj, separators=(",", ":"))
    return Markup(s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _scope(request, s):
    sc = request.query.get("scope", "all")
    return sc if sc in scope.scopes_for(s) else "all"


def _stored_rows(result):
    rows = result.get("rows") or []
    for r in rows:                                          # результати до появи тегів
        r.setdefault("tag_list", (r.get("tags") or "").split("|") if r.get("tags") else [])
    return rows, {**report.summary(rows), **(result.get("summary") or {})}


def _as_stored(result, sc):
    """«Уся історія» результату без угод або знятого цим самим кодом (rows_rev) — це збережені рядки: прогін записав
    саме rows_for(result, "all"), а збагачення дописує в них fresh і bundle. Перераховувати їх нема чого."""
    return sc == "all" and (not result.get("wallet_trades") or result.get("rows_rev") == ROWS_REV)


def _rows(result, sc, s):
    """Рядки за масштабом з угод у результаті; старі результати без угод — як збережено."""
    if _as_stored(result, sc):
        return _stored_rows(result)
    out = scope.rows_for(result, sc, s)
    return out if out else _stored_rows(result)


ROWS_MEMO_MAX = 12


async def _rows_async(app, result, sc):
    """_rows без блокування циклу подій: перерахунок усіх гаманців (0.2-1 с на великому результаті) іде в потоці і
    пам'ятається, доки збагачення не додало тегів. Ключ — сам об'єкт результату: програвання демо ділять один."""
    if _as_stored(result, sc):
        return _stored_rows(result)
    memo = app["rows_memo"]
    key = (id(result), sc, len(result.get("fresh_wallets") or []), len(result.get("bundle") or {}),
           len(result.get("funders") or {}))
    hit = memo.get(key)
    if hit and hit[0] is result:
        return hit[1]
    out = await asyncio.to_thread(_rows, result, sc, app["s"])
    memo[key] = (result, out)                               # тримаємо й результат: інакше його id міг би дістатись іншому
    while len(memo) > ROWS_MEMO_MAX:
        memo.pop(next(iter(memo)))
    return out


def _csv_text(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=report.COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in report.COLUMNS})
    return buf.getvalue()


async def job_csv(request):
    job = request.app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    sc = _scope(request, request.app["s"])
    rows, _ = await _rows_async(request.app, job.result, sc)
    return web.Response(text=await asyncio.to_thread(_csv_text, rows), content_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{job.id}-{sc}.csv"'})


async def job_json(request):
    """The result as data (for client-side selection/export)."""
    job = request.app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    r = job.result
    sc = _scope(request, request.app["s"])
    rows, _ = await _rows_async(request.app, r, sc)
    body = {"id": job.id, "mint": job.mint, "window": r["window"], "mode": r.get("mode"),
            "scope": sc, "coverage": r.get("coverage"), "columns": report.COLUMNS, "rows": rows}
    return web.Response(text=await asyncio.to_thread(json.dumps, body), content_type="application/json")


def _agent_gate(request):
    """Спільне для карток і питань: готовий аналіз, агент увімкнений, запит з цього сайту, підключений гаманець."""
    app = request.app
    job = app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        return None, _jerr("No result yet.", 404)
    if app.get("agent") is None:
        return None, _jerr("The agent is not switched on on this server.", 503)
    if not _same_origin(request):
        return None, _jerr("Requests must come from this site.", 403)
    if not request.get("acct"):
        return None, _jerr("Connect a wallet to use the agent.", 401)
    return job, None


def _agent_take(app, pk, kind):
    """Добові стелі агента: своя на гаманець для карток і для питань, спільна на сайт. Повертає (відмова, повернути)."""
    s, daily = app["s"], app["assistant_daily"]
    who, cap = (f"agent-ask:{pk}", int(s.get("agent_questions_per_day", 10))) if kind == "ask" else \
        (f"agent-cards:{pk}", int(s.get("agent_cards_per_day", 20)))
    gcap = int(s.get("agent_global_per_day", 300))
    if pk not in app["admins"]:
        if daily.left("agent-global", gcap) <= 0:
            _limit(app, pk, "agent-" + kind, "site")
            return _jerr("The agent has answered all it can today. Back tomorrow.", 429), None
        if not daily.take(who, cap):
            _limit(app, pk, "agent-" + kind, "wallet")
            return _jerr(f"You have used today's {cap} questions to the agent. More tomorrow." if kind == "ask" else
                         "You have opened the agent on too many analyses today. More tomorrow.", 429), None
        daily.take("agent-global", gcap)

    def give_back():
        if pk not in app["admins"]:
            daily.add(who, -1)
            daily.add("agent-global", -1)
    return None, give_back


def _agent_event(app, pk, kind, job_id, t0, usage=None, free=False, **extra):
    """Рядок журналу про звернення до агента: що, скільки тривало, скільки токенів і доларів. Готові картки нічого не
    коштують, тож ідуть під добову стелю журналу, як кліки; оплачене пишеться завжди, зокрема відповідь, що не вдалась."""
    if free and not _usage_take(app, pk, 1):
        return
    u = usage or {}
    app["events"].add(pk, "agent", kind=kind, job=job_id, ms=int((time.monotonic() - t0) * 1000),
                      ai_in=u.get("prompt_tokens") or None, ai_out=u.get("completion_tokens") or None,
                      ai_usd=round(float(u["cost"]), 6) if u.get("cost") else None, **extra)


def _agent_left(app, pk):
    return app["assistant_daily"].left(f"agent-ask:{pk}", int(app["s"].get("agent_questions_per_day", 10)))


async def job_agent_cards(request):
    """Три картки про аналіз мовою браузера. Зроблені раз — безкоштовні для всіх: лежать у результаті (у спільного демо —
    у пам'яті) під мовою і версією методики. Нові — з добової стелі гаманця на картки і спільної стелі агента."""
    app = request.app
    job, err = _agent_gate(request)
    if err:
        return err
    body, t0 = await _json_body(request) or {}, time.monotonic()
    pk, lang, cfg = request.get("acct"), agent_mod.lang_name(body.get("lang")), app["agent_store"].config()
    jid = job.canon or job.id
    demo_ids = _demo_job_ids(app)
    shared = bool(job.replay) or job.id in demo_ids or (job.canon or "") in demo_ids
    ckey = (job.canon or job.id, cfg["v"], lang)
    store = app["agent_cache"] if shared else job.result.setdefault("agent_cards", {})
    skey = ckey if shared else f"{cfg['v']}:{lang}"

    def reply(cards, cached):
        return web.json_response({"cards": cards, "cached": cached, "chips": cfg["chips"], "left": _agent_left(app, pk)},
                                 headers={"Cache-Control": "no-store"})
    if store.get(skey):
        _agent_event(app, pk, "cards", jid, t0, free=True, ok=1, cached=1, lang=lang)
        return reply(store[skey], True)
    busy = app["agent_inflight"].get(ckey)
    if busy is not None:                                     # ці самі картки вже пишуться для когось іншого: чекаємо їх
        try:
            cards = await asyncio.shield(busy)
            _agent_event(app, pk, "cards", jid, t0, free=True, ok=1, cached=1, lang=lang)
            return reply(cards, True)
        except Exception:  # noqa: BLE001 — у того запиту не вийшло: пробуємо самі
            pass
    refuse, give_back = _agent_take(app, pk, "cards")
    if refuse:
        return refuse
    fut = asyncio.get_running_loop().create_future()
    app["agent_inflight"][ckey] = fut
    try:
        cards, dropped, usage = await asyncio.to_thread(app["agent"].cards, job.result, cfg, lang)
    except assistant_mod.AssistantError as e:
        give_back()
        fut.set_exception(e)
        fut.exception()                                        # позначено як прочитане: без попередження в журналі
        app["agent_store"].log({"pk": pk, "job": jid, "kind": "cards", "lang": lang, "error": str(e), "usage": e.usage})
        _agent_event(app, pk, "cards", jid, t0, usage=e.usage, ok=0, err=str(e)[:80], lang=lang)
        return _jerr(str(e), 502)
    finally:
        app["agent_inflight"].pop(ckey, None)
    store[skey] = cards
    fut.set_result(cards)
    if not shared:
        _save_soon(app, job)
    app["agent_store"].log({"pk": pk, "job": jid, "kind": "cards", "lang": lang, "v": cfg["v"],
                            "dropped": dropped, "usage": usage, "model": cards.get("model")})
    _agent_event(app, pk, "cards", jid, t0, usage=usage, ok=1, cached=0, dropped=len(dropped) or None, lang=lang)
    return reply(cards, False)


async def job_agent_ask(request):
    """Питання про цей аналіз. Відповідь — мовою питання (кнопка-підказка — мовою браузера), лише факти з аналізу;
    стороннє питання отримує одну незмінну відповідь, а спроба все одно рахується."""
    app = request.app
    job, err = _agent_gate(request)
    if err:
        return err
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    q = " ".join(str(body.get("q") or "").split())
    if not q:
        return _jerr("Ask something about this analysis.")
    if len(q) > agent_mod.MAX_QUESTION:
        return _jerr(f"Keep the question under {agent_mod.MAX_QUESTION} characters.")
    pk, cfg, t0, jid = request.get("acct"), app["agent_store"].config(), time.monotonic(), job.canon or job.id
    chip = bool(body.get("chip"))
    lang = agent_mod.lang_name(body.get("lang")) if chip else "the language of the user's question"
    # кнопка-підказка — текстом (його написав власник, це не слова людини); інакше лише «своє питання»
    said = (q[:80] if q in cfg["chips"] else 1) if chip else None
    refuse, give_back = _agent_take(app, pk, "ask")
    if refuse:
        return refuse
    try:
        out, dropped, usage = await asyncio.to_thread(app["agent"].ask, job.result, cfg, q, lang)
    except assistant_mod.AssistantError as e:
        give_back()
        app["agent_store"].log({"pk": pk, "job": jid, "kind": "ask", "q": q, "chip": chip, "error": str(e), "usage": e.usage})
        _agent_event(app, pk, "ask", jid, t0, usage=e.usage, ok=0, err=str(e)[:80], chip=said)
        return _jerr(str(e), 502)
    app["agent_store"].log({"pk": pk, "job": jid, "kind": "ask", "q": q, "chip": chip, "on_topic": out["on_topic"],
                            "v": cfg["v"], "dropped": dropped, "usage": usage, "model": out.get("model")})
    _agent_event(app, pk, "ask", jid, t0, usage=usage, ok=1, off=None if out["on_topic"] else 1,
                 dropped=len(dropped) or None, chip=said)
    return web.json_response(dict(out, left=_agent_left(app, pk)), headers={"Cache-Control": "no-store"})


async def job_state_json(request):
    """Live state for the terminal while the analysis runs (never 404 for a known id)."""
    job = request.app["jobs"].get(request.match_info["id"])
    if not job:
        return web.json_response({"error": "No such analysis."}, status=404)
    try:
        since = max(0, int(request.query.get("since", 0)))
    except ValueError:
        since = 0
    status, error = job.status, job.error                 # знімок статусу ДО зрізу журналу
    extra = {"open": f"/job/{job.canon}"} if job.canon and status == "done" else {}   # демо: результат живе під збереженим id
    if status == "done" and not job.result:
        status, error = "error", "The analysis finished without a result. Details are in the container log."
    n = len(job.log)
    return web.json_response(
        {**extra, "id": job.id, "mint": job.mint, "symbol": job.symbol, "status": status, "error": error,
         "started_ms": job.started_ms or job.created_ms, "finished_ms": job.finished_ms,
         "now_ms": int(time.time() * 1000), "since": min(since, n), "n_lines": n,
         "log": job.log[since:n] if since < n else [], "progress": job.progress},
        headers={"Cache-Control": "no-store"})


def _tail(d, since):
    """Записи словника після перших `since`: фонові перевірки лише дописують, тож порядок вставки стабільний.
    Якщо сторінка знає більше, ніж є (результат перезаписали), — усе заново."""
    items = list((d or {}).items())
    return dict(items[since:] if 0 <= since <= len(items) else items), len(items)


async def job_enrich_json(request):
    """Progress of the background checks and what they found since the page last asked.

    The page sends how many funders (`f`) and first transactions (`a`) it already holds and whether it has the names
    (`i=1`); the answer carries only the rest. The whole state every five seconds was 177 KB on a 2,500-wallet result.
    Bundles are not sent: the page counts them from the funders by the same rule.

    Names count as done when nobody will ask for them: a demo or its replay (a snapshot), or a server without the
    names lookup; otherwise a page polled forever for results made before names existed. `paused` holds only while the
    RPC budget is paused right now: in a new month the paused enrichment is queued again instead."""
    app = request.app
    job = app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    r = job.result

    def since(key):
        try:
            return int(request.query.get(key, 0))
        except ValueError:
            return 0
    e = r.get("enrich") or {"done": 0, "total": 0, "fresh": 0}
    fresh = [row["wallet"] for row in r.get("rows") or [] if "fresh" in (row.get("tag_list") or [])]
    funders, n_funders = _tail(r.get("funders"), since("f"))
    ages, n_ages = _tail(r.get("ages"), since("a"))
    demo_ids = _demo_job_ids(app)
    snapshot = bool(job.replay) or job.id in demo_ids or (job.canon or "") in demo_ids
    rpc = app.get("ages")
    paused = e.get("paused") if rpc is not None and rpc.paused() else None
    if e.get("paused") and not paused and not snapshot:
        app["jobs"].resume_enrich(job)                  # бюджет відновився: доробляємо, не чекаючи рестарту
    out = {"done": e.get("done", 0), "total": e.get("total", 0), "fresh": fresh,
           "funders_done": e.get("funders_done", 0), "paused": paused,
           "funders": funders, "n_funders": n_funders, "ages": ages, "n_ages": n_ages, "services": r.get("services") or [],
           "identities_done": bool(r.get("identities_done")) or snapshot or app["jobs"].namer is None}
    if request.query.get("i") != "1":
        out["identities"] = r.get("identities") or {}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def wallet_profile_json(request):
    """The wallet's last days on every token, counted by our own ledger from its raw swaps: PnL, win rate, holds.

    1-5 requests, cached for a day. Only wallets that appear in this analysis are looked up (the site does not
    resell Solana Tracker for arbitrary addresses). A cached profile is free for anyone; a new one needs a
    connected wallet and is paid from the same daily budget as charts."""
    app = request.app
    job = app["jobs"].get(request.query.get("job", ""))
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    wallet = request.query.get("wallet", "")
    if not MINT_RE.match(wallet):
        raise WebError("That does not look like a wallet address.")
    if wallet not in {r.get("wallet") for r in job.result.get("rows") or []}:
        raise web.HTTPNotFound(text="That wallet is not in this analysis.")
    cache, key = app["profile_cache"], f"v{profile.VERSION}:{wallet}"
    hit = cache.get(key)
    if hit is not None:
        return web.json_response(hit)
    if not request.get("acct"):
        raise ConnectRequired(message="Connect a wallet to load this wallet's last 30 days.")
    st, s = app["st"], app["s"]
    if not hasattr(st, "wallet_swaps"):
        raise WebError("This data source cannot list a wallet's trades.", 501)
    settle, pk = _browse_budget(request, 3), request.get("acct")

    def work():
        with st.meter():
            req0 = st.requests_here()
            try:
                return _profile_now(app, wallet)
            finally:
                n = st.requests_here() - req0
                settle(n)
                _spend(app, pk, "card-profile", st=n, job=job.canon or job.id)
    try:
        out = await asyncio.to_thread(work)
    except Exception as e:  # noqa: BLE001
        log.warning("wallet profile %s: %s", wallet[:8], e)
        raise WebError("Solana Tracker did not answer for this wallet. Try again in a minute.", 502)
    return web.json_response(out)


def _profile_now(app, wallet):
    """30 днів гаманця нашим леджером, зараз: 1-5 запитів, і відповідь лягає в кеш картки (його ж читає дашборд власника).
    Кличеться в потоці, під лічильником запитів того, хто питає."""
    st, s = app["st"], app["s"]
    days, pages = int(s.get("profile_days", 30)), int(s.get("profile_max_pages", 5))
    now = int(time.time() * 1000)
    raw, partial = st.wallet_swaps(wallet, now - days * 86_400_000, pages)
    evs = [ev for r in reversed(raw) for ev in profile.normalize_wallet_swap(r, wallet)]   # джерело віддає новіші першими
    out = profile.card(evs, wallet, now, partial)
    out["computed_ms"] = now
    app["profile_cache"].put(f"v{profile.VERSION}:{wallet}", out)
    return out


def _store_trades_of(store_dir, mint, wallet, a, b):
    """Угоди одного гаманця з кешу угод токена, не вантажачи весь файл: TradeStore на 500 тисяч угод — це ~700 МБ
    пам'яті на запит. Розбираємо лише рядки, де трапляється адреса; дублі відкидаємо так само, як сховище."""
    path = os.path.join(store_dir, f"trades_{mint}.jsonl")
    out, seen = [], set()
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if wallet not in line:
                    continue
                try:
                    tr = json.loads(line)
                except ValueError:
                    continue                                # обірваний рядок після збою
                key = TradeStore._key(tr)
                if tr.get("wallet") != wallet or key in seen or tr.get("time") is None or not a <= tr["time"] <= b:
                    continue
                seen.add(key)
                out.append(tr)
    except FileNotFoundError:
        pass
    return out


async def wallet_trades_json(request):
    """One wallet's buys and sells on the analysed token, for the chart markers.

    Stored in the result (every row since v0.3): no requests. An older full-trades result: this wallet's lines of the
    cached token feed (no requests). An older per-wallet result: the wallet's own trades from Solana Tracker (1 request,
    cached, needs a wallet and the chart budget). Exact trade times; market cap = price × supply."""
    app = request.app
    job = app["jobs"].get(request.query.get("job", ""))
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    wallet = request.query.get("wallet", "")
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", wallet):
        raise WebError("That does not look like a wallet address.")
    st, s, mint = app["st"], app["s"], job.mint
    a, b = job.t_from, job.t_exit or int(time.time() * 1000)
    supply = (job.result.get("info") or {}).get("supply") or 0
    stored = (job.result.get("wallet_trades") or {}).get(wallet)
    settle = None
    if stored is None:
        # чужі адреси не купуємо і не шукаємо ні в Solana Tracker, ні в сотнях мегабайт угод токена — у будь-якому режимі
        if wallet not in {r.get("wallet") for r in job.result.get("rows") or []}:
            raise web.HTTPNotFound(text="That wallet is not in this analysis.")
        demo_ids = _demo_job_ids(app)
        if job.replay or job.id in demo_ids or (job.canon or "") in demo_ids:   # демо живе без запитів
            return web.json_response({"wallet": wallet, "n": 0, "truncated": False, "trades": [], "complete": False})
        if job.result.get("mode") != "trades":
            if not request.get("acct"):
                raise ConnectRequired(message="Connect a wallet to load this wallet's trades.")   # цей шлях купує угоди гаманця…
            settle = _browse_budget(request, 1)                        # …і платить за них з добового бюджету

    def work():
        if stored is not None:                                        # уся історія гаманця вже в результаті
            return scope.unpack(wallet, stored.get("trades") or [])
        if job.result.get("mode") == "trades":
            return _store_trades_of(app["store_dir"], mint, wallet, a, b)
        with st.meter():                                  # run_in_executor не переносить контекст: лічильник відкриваємо тут
            req0 = st.requests_here()
            try:
                return [t for t in st.wallet_token_trades(wallet, mint, s.get("max_wallet_trade_pages", 4))
                        if t["time"] is not None and a <= t["time"] <= b]
            finally:
                n = st.requests_here() - req0
                if settle:
                    settle(n)
                _spend(app, request.get("acct"), "card-trades", st=n, job=job.canon or job.id)
    trs = await asyncio.get_running_loop().run_in_executor(None, work)
    trs.sort(key=lambda t: t["time"] or 0)
    cap = int(s.get("markers_max", 200))
    out = [{"t": t["time"], "side": t["type"], "usd": t.get("usd"), "qty": t.get("qty"), "sol": t.get("sol"),
            "mcap": (t.get("price") or 0) * supply} for t in trs[:cap] if t["type"] in ("buy", "sell")]
    return web.json_response({"wallet": wallet, "n": len(trs), "truncated": len(trs) > cap, "trades": out,
                              "complete": (stored or {}).get("source") != "entry-only" if stored is not None else True})


async def health(request):
    """For the proxy and the deploy script: 503 when results cannot be written (the one failure that looks fine and
    loses every analysis); running/queued counts let a deploy wait for an analysis in flight."""
    jobs = request.app["jobs"]
    try:
        (Path(jobs.dir) / ".health").write_text(str(int(time.time())), encoding="utf-8")
        ok = True
    except OSError:
        ok = False
    st = [j.status for j in jobs.jobs.values()]
    return web.json_response({"ok": ok, "jobs": len(st), "running": st.count("running"), "queued": st.count("queued"),
                              "demo": _demo(request.app) is not None,
                              "credits": request.app["credits"]["left"],          # лише кешоване число: /health не витрачає запитів
                              "job_errors": jobs.load_errors[-5:]},              # файли аналізів, що не прочитались чи не записались
                             status=200 if ok else 503)
