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
import hmac
import ipaddress
import datetime
import os
import secrets
import io
import json
import logging
import math
import re
import threading
import time
import urllib.error
import urllib.parse
from pathlib import Path

import aiohttp
from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from ..cache import JsonCache
from ..early import agent as agent_mod, assistant as assistant_mod, exchanges as exch_mod, labels as labels_mod, ledger, pipeline, profile, report, scope, tags, wallet_age as wallet_age_mod, window
from ..early.store import TradeStore
from ..providers import dexscreener
from . import accounts as acct_mod, after as after_mod
from . import activity as activity_mod
from . import alerts as alerts_mod
from . import fresh as fresh_mod
from . import docs as docs_mod
from . import chart
from . import demo as demo_mod
from . import replay
from . import partner_api as api_mod
from . import usage as usage_mod
from .agent_store import AgentStore
from .feedback import FeedbackStore, KINDS as FEEDBACK_KINDS, MAX_CONTACT as FEEDBACK_CONTACT, MAX_PAGE as FEEDBACK_PAGE, MAX_TEXT as FEEDBACK_TEXT
from .feedback import links as feedback_links
from .jobs import JobQueue, make_id, unnamed

log = logging.getLogger("early.web")
HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE.parent.parent / "docs"      # сторінки документації лежать у репозиторії поруч із кодом
HOUR = 3_600_000
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
MAX_CANDLES = 1500          # скільки свічок має сенс просити за раз: більше — і джерело мовчки обріже відповідь
ACCT_COOKIE = "early_acct"          # вхід гаманцем — єдиний вхід на сайті
DEVICE_COOKIE = "early_dev"         # випадкове число браузера для добової стелі аналізів; нічого іншого в ньому нема
DEVICE_DAYS = 90            # лічильник доби не потребує року: 90 днів — і менше, що пояснювати в політиці (юр. огляд 01.10)
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
# IBM Carbon icons from one sprite (owner, 02.10: not the Lucide look of AI-made sites); ui.js has the same for scripts
env.globals["icon"] = lambda name, cls="": Markup(f'<svg class="ci{" " + cls if cls else ""}" aria-hidden="true">'
                                                 f'<use href="/static/icons.svg?v={env.globals["v"]}#i-{name}"/></svg>')
from .. import __version__                                   # noqa: E402 — product version for the footer
env.globals["version"] = ".".join(__version__.split(".")[:2])
env.globals["news"] = docs_mod.latest(DOCS_DIR)                # the bell beside the wallet: which update is the newest
env.filters["dt"] = chart.fmt_dt
env.filters["dtu"] = lambda ms: chart.fmt_dt(ms, year=True, utc=True)   # експорт: у файлі колонка мусить назвати зону
env.filters["dty"] = lambda ms: chart.fmt_dt(ms, year=True)            # на сторінці зону називає перемикач у підвалі
env.filters["dtl"] = chart.to_input
env.filters["day"] = chart.fmt_day
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


def _ago(ms, now_ms=None):
    """Скільки минуло: now, 5m, 3h, 2d."""
    try:
        m = ((now_ms or time.time() * 1000) - float(ms)) / 60_000
    except (TypeError, ValueError):
        return ""
    return "now" if m < 1 else f"{int(m)}m" if m < 60 else f"{int(m // 60)}h" if m < 1440 else f"{int(m // 1440)}d"   # униз: 59m, не 60m


env.filters["ago"] = _ago


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


def make_enricher(ages, s, spend=None, labels=None):
    """Після аналізу, у фоні: вік кожного гаманця з RPC → тег `fresh` і перший спонсор → `bundle`; прогрес у
    result["enrich"]. Кредити ноди йдуть у журнал (`spend`) на кожному збереженні: деплой dev перезапускає сервер
    посеред збагачення, і витрачене до рестарту інакше загубилось би."""
    body = _enrich_body(ages, s, labels)

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


def _enrich_body(ages, s, labels=None):
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
        if not e.get("done") and r.get("dormant_at") is None:
            r["dormant_run"] = True                        # this pass reads «dormant» with each age
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
            _dormant(r, row, age, ages, is_paused())
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
        if r.get("dormant_at") is None:
            # a result checked before «dormant» existed (owner, 04.10): its first full_top get it once, from the age in the
            # cache and one signature each (1 credit); a new run has just done it in the pass above
            if e.get("done", 0) >= n and n and not r.get("dormant_run"):
                kept = r.get("ages") or {}                 # the cache keeps an age a week; the result keeps it for good
                for row in rows[:min(n, top or n)]:
                    a = kept.get(row["wallet"])
                    age = cached(row["wallet"]) or ({"oldest_ms": a["ms"], "exact": bool(a.get("exact"))} if a and a.get("ms") else None)
                    _dormant(r, row, age, ages, is_paused())
            r["dormant_at"] = int(time.time() * 1000)
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
            if is_paused() and getattr(ages, "cache", None) is not None and ages.funder_unread(w):   # запис без версії — теж платний
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
        _label_funders(r, labels, s, job)
        services()
        _bundles(r, rows)
        r["bundle_rev"] = tags.BUNDLE_REV                   # бандли пораховані чинним правилом
        save(job)
        ages.flush()
    return enrich


def _label_funders(r, labels, s, job=None):
    """Мітки InsightX (власник, 04.10: «подивимось, як це працює і що дає додатково») для спонсорів, яких не знає наш
    список бірж: спершу тих, хто дав SOL кільком гаманцям (там мітка вирішує, бандл це чи біржа), далі решти. Не більше
    insightx_calls_per_run запитів по 100 адрес; результат пам'ятає, коли його питали, щоб не питати знову."""
    if labels is None:
        return
    from collections import Counter
    known = r.get("labels") or {}
    cnt = Counter((r.get("funders") or {}).values())
    want = [f for f, _ in cnt.most_common() if f not in exch_mod.KNOWN and f not in known]
    before = labels.requests
    found = labels.lookup(want, max_calls=int(s.get("insightx_calls_per_run", 3))) if want else {}
    if found:
        r["labels"] = dict(known, **{a: [x["name"], x["label"], x.get("kind") or ""] for a, x in found.items()})
    r["labels_at"] = int(time.time() * 1000)
    used = labels.requests - before
    if used and job is not None:
        ex = sum(1 for x in found.values() if x.get("kind") == "exchange")
        job.log.append(f"InsightX named {len(found)} funders ({ex} exchanges) in {used} request{'' if used == 1 else 's'}")
    labels.flush()


def _dormant(r, row, age, ages, paused=False):
    """`dormant` (owner, 04.10): the transaction right before its first buy in the range is a week old or older. The age
    check has just read that page, so this is mostly a cache hit; a fresh wallet cannot be asleep. A failure leaves the
    tag off: missing a sleeper is the safe side."""
    at, sig = row.get("first_range_buy_ms") or row.get("first_buy_ms"), row.get("entry_tx")
    prev_tx = getattr(ages, "prev_tx", None)
    if not (prev_tx and age and at and sig) or tags.is_fresh(row.get("first_buy_ms"), age):
        return
    try:
        prev = prev_tx(row["wallet"], sig, cached_only=paused)
    except Exception:  # noqa: BLE001
        return
    days = tags.dormant_days(at, prev)
    if not days:
        return
    r.setdefault("dormant", {})[row["wallet"]] = days
    if "dormant" not in (row.get("tag_list") or []):
        row["tag_list"] = tags.with_tag(row.get("tag_list"), "dormant")
        row["tags"] = "|".join(row["tag_list"])


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
    # відома біржа (список Dune у early/data) — сервіс без жодного запиту: і кредит не йде, і бандла від неї не буде
    services |= {f for f in set((r.get("funders") or {}).values()) if exch_mod.name_of(f)}
    services |= {a for a, v in (r.get("labels") or {}).items() if len(v) > 2 and v[2] in labels_mod.SERVICE_KINDS}
    if check is not None and not (getattr(ages, "paused", None) or (lambda: False))():
        from collections import Counter
        for f, n in Counter((r.get("funders") or {}).values()).items():
            if n >= tags.BUNDLE_MIN and f not in services and check(f):
                services.add(f)
    r["services"] = sorted(services)


def create_app(st, s, cfg=None, out_dir="output/early/web", store_dir="cache/early", ages=None, assistant=None, background=False,
               labels=None):
    app = web.Application(middlewares=[errors_mw, auth_mw, private_mw])
    app.on_response_prepare.append(_security_headers)
    app["bg"] = {}                                                 # фонові задачі сервера (лише з background=True, не в тестах)
    app["fresh"], app["fresh_peaks"] = {"at": 0, "ok_at": 0, "rows": [], "busy": False, "live": background, "day": "", "n": 0}, {}   # свіжі пампи на головній
    if background:
        app.on_startup.append(_start_background)
        app.on_cleanup.append(_stop_background)
    app.on_cleanup.append(_flush_on_exit)          # після зупинки фону: потік не дописує лічильники в уже записаний файл
    app["assistant"] = assistant                                   # транспорт до моделі; None — агента на цьому сервері нема
    app["agent"] = agent_mod.Agent(assistant.json_chat, assistant.model) if assistant is not None else None
    app["agent_store"] = AgentStore(Path(out_dir).parent / "agent")   # методика власника, її версії, журнал питань
    app["agent_cache"], app["agent_inflight"] = {}, {}             # картки спільного демо (у файл не пишуться) і ті, що вже пишуться
    app["st"], app["s"], app["cfg"] = st, s, cfg or {}
    app["store_dir"] = store_dir
    app["runs"] = Throttle(max_fails=int(s.get("runs_per_hour", 20)), window_s=3600, block_s=3600)
    app["wallet_gate"] = {}                             # гаманець → (коли читали, чи новий або порожній): див. _wallet_gate
    app["home_totals"] = {}                             # лічильники головної за всіма аналізами, раз на хвилину: _home_totals
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
    app["usage_dir"] = Path(out_dir).parent / "usage"            # там же список тестових гаманців і on-chain факти користувачів
    app["events"] = acct_mod.EventLog(app["usage_dir"], legacy=Path(out_dir).parent / "accounts" / "_events.jsonl")
    app["admins"] = {w.strip() for w in os.getenv("ADMIN_WALLETS", "").split(",") if w.strip()}   # чиї гаманці бачать /admin
    app["auth_throttle"] = Throttle(max_fails=10, window_s=300, block_s=600)
    app["nonce_throttle"] = Throttle(max_fails=30, window_s=300, block_s=300)   # кодів входу з однієї мережі: 30 за 5 хв
    app["heavy_throttle"] = Throttle(max_fails=int(s.get("heavy_per_min", 90)), window_s=60, block_s=60)   # сторінки результату з мережі за хвилину
    daily_dir = Path(out_dir).parent / "daily"           # добові лічильники переживають деплой
    app["fresh_file"] = daily_dir / "fresh.json"         # стрічка пампів теж: піки не питаються вдруге, стеля доби не скидається
    _fresh_load(app)
    app["assistant_daily"] = DailyCount(daily_dir / "assistant.json")
    app["auth_daily"] = DailyCount(daily_dir / "auth.json")       # нові акаунти: з мережі і на сайт за добу
    app["browse_daily"] = DailyCount(daily_dir / "browse.json")   # запити на графіки живих токенів: на адресу, на гаманець, на сайт
    app["runs_daily"] = DailyCount(daily_dir / "runs.json")       # живі прогони на весь сайт за добу (будь-який ключ підписує безкоштовно)
    app["usage_daily"] = DailyCount(daily_dir / "usage.json")     # рядків журналу (перегляди, кліки) на гаманець і на сайт за добу
    app["alerts_st_daily"] = DailyCount(daily_dir / "alerts_st.json")   # запити Solana Tracker від сповіщень за добу
    app["alerts_day"] = DailyCount(daily_dir / "alerts_day.json")   # надіслані сповіщення на акаунт за добу (і чи вже попередили)
    app["feedback"] = FeedbackStore(Path(out_dir).parent / "feedback" / "feedback.jsonl")   # «Contact»: листи власнику
    app["feedback_throttle"] = Throttle(max_fails=5, window_s=3600, block_s=3600)       # п'ять листів на годину з однієї адреси
    app["after_memo"] = {}                                        # «після алертів», порахований на 15 хвилин, на людину
    app["usage_cache"], app["view_last"] = {}, {}                 # порахований дашборд на хвилину; останній перегляд сторінки
    app["credits"] = {"left": None, "at": 0}                     # залишок кредитів Data API: питаємо не частіше ніж раз на 10 хв
    app["ai_balance"] = {"v": None, "at": 0}                     # залишок на відповіді агента (OpenRouter): так само раз на 10 хв
    app["api_keys"] = api_mod.KeyStore(Path(out_dir).parent / "api" / "keys.json")   # ключі партнерів: лише відбитки
    app["api_cache"] = {}                                         # відповідь Solana Tracker на монету: хвилину з пам'яті
    app["api_throttle"] = Throttle(max_fails=int(s.get("api_per_10s", 50)), window_s=10, block_s=10)   # запитів ключа за 10 с
    app["api_bad"] = Throttle(max_fails=20, window_s=60, block_s=60)
    # сповіщення в Telegram: ключ бота — лише з оточення; слухає потік і бот лише там, де ALERTS=1 (одне місце на ключ)
    app["tg"] = {"token": os.getenv("TELEGRAM_BOT_TOKEN") or "", "name": os.getenv("TELEGRAM_BOT_NAME") or "",
                 "on": os.getenv("ALERTS") == "1"}
    app["tg_codes"] = alerts_mod.LinkCodes()
    app["alerts_state"] = {"on": False, "connected": False, "url": "", "wallets": 0, "events": 0, "sent": 0, "last_ms": None, "errors": 0}
    app["alerts_wm"], app["alerts_seen"], app["alerts_tok"], app["alerts_hour"], app["sol_px"] = {}, {}, {}, {}, [0.0, 0.0]
    app["alerts_ca"] = {}             # чат → токени, адресу яких він уже отримав (у пам'яті: після перезапуску адреса прийде ще раз)
    app["activity"] = activity_mod.Activity(Path(out_dir).parent / "usage" / "activity.json")   # угоди гаманців зі списків, для Lists
    app["alerts_fails"], app["alerts_tok_wait"], app["alerts_pending"] = {}, {}, 0   # збої за годину; токени, які саме питаємо; черга
    app["alerts_sem"] = asyncio.Semaphore(int(s.get("alerts_parallel", 4)))         # запитів до ноди водночас
    app["alerts_pace"], app["alerts_flood"] = _Pace(s.get("alerts_rps", 12)), {}    # темп запитів до ноди; угоди гаманця за хвилину
    app["alerts_conn_at"] = 0.0                                                     # коли підключився нинішній потік
    app["alerts_poll_wake"], app["alerts_chat_locks"] = asyncio.Event(), {}         # розбудити страховку; черга відправки на чат
    app["alerts_inflight"] = set()                                                  # угоди, які саме розбираються
    for key in app["activity"].recent_done():                                       # оброблене до перезапуску: не вдруге
        app["alerts_seen"][key] = time.time()   # спроб з невірним ключем з однієї мережі за хвилину
    app["ages"] = ages
    app["labels"] = labels                                      # InsightX: мітки спонсорів; None — без ключа (і в тестах)
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
        if not job.charged:                             # the owner's and beta testers' runs took no count, so they give none back
            return
        app["accounts"].give_back_run(job.owner)
        app["runs_daily"].add("global", -1)
        for key in job.charged:
            app["runs_daily"].add(key, -1)

    def spend(who, what, **kw):
        _spend(app, who, what, **kw)

    def on_finish(job):
        """Живий прогін закінчився: рядок журналу — хто, що, скільки запитів і що знайшов (дашборд власника); і те, що
        він витратив, лягає в денний бюджет запитів на нові аналізи (прогони власника — поза ним)."""
        app["events"].add(job.owner or "system", "run", **usage_mod.run_facts(job))
        if job.owner and job.owner not in app["admins"] and not job.replay and job.spent:
            app["runs_daily"].add("req:global", int(job.spent))

    identify = ((lambda ws: st.identities(ws, strict=True))               # відмова джерела ≠ «імен нема»
                if (hasattr(st, "identities") and s.get("st_identity", True)) else None)
    app["jobs"] = JobQueue(runner, out_dir, enricher=make_enricher(ages, s, spend, labels) if ages else None, on_error=on_error,
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
    app.router.add_get("/robots.txt", robots_txt)
    app.router.add_post("/auth/nonce", auth_nonce)
    app.router.add_post("/auth/verify", auth_verify)
    app.router.add_post("/auth/logout", auth_logout)
    app.router.add_get("/me", me_page)
    app.router.add_get("/feedback", feedback_page)
    app.router.add_post("/feedback", feedback_post)
    app.router.add_get("/me.json", me_json)
    app.router.add_get("/me/wallets.csv", me_wallets_csv)
    app.router.add_post("/me/wallets", me_add_wallets)
    app.router.add_post("/me/wallets/remove", me_remove_wallet)
    app.router.add_post("/me/wallets/tags", me_tags)
    app.router.add_post("/me/wallets/alert", me_wallet_alert)
    app.router.add_post("/me/lists", me_lists)
    app.router.add_post("/me/lists/{action}", me_lists)
    app.router.add_post("/me/analyses", me_add_analysis)
    app.router.add_post("/me/analyses/remove", me_remove_analysis)
    app.router.add_post("/me/usage", me_usage)
    app.router.add_post("/me/telegram/link", me_tg_link)
    app.router.add_post("/me/telegram/unlink", me_tg_unlink)
    app.router.add_get("/me/telegram.json", me_tg_status)
    app.router.add_get("/me/wallet.json", me_wallet_json)
    app.router.add_get("/me/after.json", me_after_json)
    app.router.add_post("/me/alerts", me_alerts)
    app.router.add_get("/admin", admin_page)
    app.router.add_get("/admin/w/{pk}", admin_wallet_page)
    app.router.add_post("/admin/usage/exclude", admin_usage_exclude)
    app.router.add_post("/admin/beta", admin_beta)
    app.router.add_post("/admin/labels", admin_labels)
    app.router.add_post("/admin/feedback", admin_feedback)
    app.router.add_post("/admin/api", admin_api)
    app.router.add_get("/api/v1/check", api_check)
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


ONCHAIN_FIRST_S, ONCHAIN_EVERY_S = 600, 6 * 3600


async def _start_background(app):
    loop = asyncio.get_running_loop()
    app["bg"]["usage"] = loop.create_task(_usage_loop(app))
    fresh_age = time.time() * 1000 - app["fresh"]["at"]
    if app["s"].get("fresh_on") and fresh_age > float(app["s"].get("fresh_refresh_min", 10)) * 60_000:
        app["bg"]["fresh"] = loop.create_task(_fresh_refresh(app))       # головна не чекає; свіжий список з файла — не питаємо знову
    if app["tg"]["token"] and os.getenv("ALERTS") == "1":
        app["alerts_state"]["on"] = True
        app["bg"]["tg_bot"] = loop.create_task(_tg_bot_loop(app))
        app["bg"]["alerts"] = loop.create_task(_alerts_loop(app))
        app["bg"]["alerts_poll"] = loop.create_task(_alerts_poll_loop(app))


def _fresh_load(app):
    saved = usage_mod.load_json(app["fresh_file"], {})
    if not isinstance(saved, dict):
        return
    # файл свій, але зіпсований руками чи диском не має валити головну (рев'ю 01.10): лише числа і рядки-словники
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    peaks = saved.get("peaks") if isinstance(saved.get("peaks"), dict) else {}
    app["fresh_peaks"].update({m: tuple(v) for m, v in peaks.items() if isinstance(v, list) and len(v) == 3 and all(num(x) for x in v)})
    rows = saved.get("rows")
    if isinstance(rows, list) and all(isinstance(r, dict) and isinstance(r.get("mint"), str) and num(r.get("peak")) and num(r.get("cap")) for r in rows):
        app["fresh"]["rows"] = rows
    for k, kind in (("day", str), ("n", int), ("at", int), ("ok_at", int)):
        if isinstance(saved.get(k), kind):
            app["fresh"][k] = saved[k]


def _fresh_save(app):
    f = app["fresh"]
    try:
        app["fresh_file"].parent.mkdir(parents=True, exist_ok=True)
        usage_mod.save_json(app["fresh_file"], {"peaks": {m: list(v) for m, v in app["fresh_peaks"].items()},
                                                **{k: f[k] for k in ("day", "n", "rows", "at", "ok_at")}})
    except OSError as e:
        log.warning("fresh pumps save: %s", e)


async def _fresh_refresh(app):
    """Свіжі пампи для головної: не частіше ніж раз на fresh_refresh_min і лише коли головну відкривають (уночі — ні).
    Кредити — «system/fresh»; поки ST нижче місячного резерву, список лишається старим."""
    f, s, st = app["fresh"], app["s"], app["st"]
    if f["busy"] or not hasattr(st, "_get"):
        return
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if f["day"] != day:
        f["day"], f["n"] = day, 0
    if f["n"] >= int(s.get("fresh_max_refresh_per_day", 150)):   # стеля на добу: головну смикають і боти (рев'ю 30.09)
        return
    f["busy"] = True
    if not await _st_open(app):                     # залишок перечитується раз на 10 хв, а не береться з пам'яті (рев'ю 30.09)
        f["busy"] = False
        return
    f["n"] += 1

    def work():
        with st.meter():
            n0 = st.requests_here()
            try:
                return fresh_mod.refresh(st, s, app["fresh_peaks"])
            finally:
                _spend(app, "system", "fresh", st=st.requests_here() - n0)
    try:
        f["rows"], f["at"] = await asyncio.to_thread(work), int(time.time() * 1000)
        f["ok_at"] = f["at"]
    except Exception as e:  # noqa: BLE001 — головна показує попередній список
        log.warning("fresh pumps: %s", e)
        f["at"] = int(time.time() * 1000) - int(float(s.get("fresh_refresh_min", 10)) * 60_000) + 120_000   # спроба знову за 2 хв
    finally:
        try:
            await asyncio.to_thread(_fresh_save, app)   # ще під busy: наступний прохід не міняє піки, поки їх пишемо
        finally:
            f["busy"] = False


async def _stop_background(app):
    for task in app["bg"].values():
        task.cancel()


async def _usage_loop(app):
    """Фон дашборда власника: за 10 хвилин після старту (деплой dev перезапускає сервер часто), далі кожні 6 годин —
    on-chain факти активних гаманців і чистка журналу, старшого за usage_keep_months. Збій проходу — лише в журнал."""
    await asyncio.sleep(ONCHAIN_FIRST_S)
    while True:
        try:
            n = await asyncio.to_thread(refresh_onchain, app)
            if n:
                log.info("usage: on-chain facts of %s wallets refreshed", n)
            await asyncio.to_thread(app["events"].prune, int(app["s"].get("usage_keep_months", 13)))
        except Exception as e:  # noqa: BLE001
            log.warning("usage refresh: %s", e)
        await asyncio.sleep(ONCHAIN_EVERY_S)


def refresh_onchain(app, now=None):
    """On-chain факти гаманців, активних за usage_active_days, раз на ~добу: хто це (Solana Tracker, з кешу), SOL
    (публічна нода, 0 кредитів), вік (Helius, кеш тиждень) і 30 днів торгівлі нашим леджером (1-5 запитів; кеш картки
    гаманця спільний). Нових профілів — не більше usage_profiles_per_day на добу і лише поки ключ далеко від резерву.
    Витрачене — одним рядком `system`. Кличеться в потоці; повертає, скільки гаманців оновлено."""
    s, st, ages = app["s"], app["st"], app.get("ages")
    now = now or int(time.time() * 1000)
    path = app["usage_dir"] / "onchain.json"
    data = usage_mod.load_json(path, {}) or {}
    events = app["events"].read(now - int(s.get("usage_active_days", 7)) * 86_400_000)
    due = usage_mod.due_wallets(events, data, now, cap=int(s.get("usage_onchain_max_wallets", 100)))
    if not due:
        return 0
    left, reserve = app["credits"]["left"], _credits_reserve(s)
    with st.meter(), wallet_age_mod.rpc_meter() as m:              # один лічильник на прохід: вкладені ховали б запити
        req0 = st.requests_here()
        try:
            idn, bal = {}, {}
            if hasattr(st, "identities") and s.get("st_identity", True):
                try:
                    idn = st.identities(due) or {}
                except Exception as e:  # noqa: BLE001
                    log.warning("usage: names: %s", e)
            if ages is not None and hasattr(ages, "balances"):
                try:
                    bal = ages.balances(due)
                except Exception as e:  # noqa: BLE001 — лишається вчорашній баланс
                    log.warning("usage: balances: %s", e)
            for w in due:
                rec = dict(data.get(w) or {}, at=now, idn=idn.get(w) or (data.get(w) or {}).get("idn") or {})
                if w in bal:
                    rec["sol"] = bal[w]
                if ages is not None and not ages.paused():
                    try:
                        age = ages.oldest_tx(w, full=True)
                        if age.get("oldest_ms"):
                            rec["age_ms"], rec["age_exact"] = age["oldest_ms"], bool(age.get("exact"))
                    except Exception as e:  # noqa: BLE001
                        log.warning("usage: age of %s: %s", w[:6], e)
                card = app["profile_cache"].get(f"v{profile.VERSION}:{w}")
                if (card is None and hasattr(st, "wallet_swaps") and (left is None or left > reserve)
                        and app["usage_daily"].take("onchain:profiles", int(s.get("usage_profiles_per_day", 50)))):
                    try:
                        card = _profile_now(app, w)
                    except Exception as e:  # noqa: BLE001
                        log.warning("usage: 30 days of %s: %s", w[:6], e)
                if card is not None:
                    rec["p30"] = usage_mod.compact_profile(card)
                data[w] = rec
        finally:
            _spend(app, "system", "onchain", st=st.requests_here() - req0, rpc=m["credits"], bg=1)
    usage_mod.save_json(path, data)
    return len(due)


async def _flush_on_exit(app):
    """Зупинка сервера: відкладені записи результатів і кеші — на диск. Сторінки більше не пишуть кеші щоразу."""
    for job, task in list(app["age_saves"]["waiting"].values()):
        task.cancel()
        try:
            await asyncio.to_thread(app["jobs"]._save, job, True)
        except Exception as e:  # noqa: BLE001
            log.warning("save on exit %s: %s", job.id, e)
    fns = [app["profile_cache"].flush, app["dex_cache"].flush]
    snap = app["activity"].snapshot()                 # знімок — тут, у циклі подій, де живуть усі зміни; запис — у потоці
    fns.append(lambda: app["activity"].write(snap))
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

def _error_event(request, status, msg):
    """Підключений гаманець побачив помилку: де і яку (дашборд власника показує, що ламається в людей). Ліміти
    (429) пишуться окремо як `limit`; гостей не пишемо."""
    pk = request.get("acct")
    if not pk or status == 429 or not _usage_take(request.app, pk, 1, _ip_key(_client_ip(request))):
        return
    where = request.path.strip("/").split("/")[0] or "home"
    request.app["events"].add(pk, "error", where=where[:40], status=int(status), msg=str(msg or "")[:120])


# мертві посилання: сторінка «rugged» з Wick. Решта 404 (немає гаманця в аналізі тощо) — звичайна помилка з причиною
RUGGED = {"No such analysis.", "There is no such page in the documentation."}


@web.middleware
async def errors_mw(request, handler):
    try:
        return await handler(request)
    except web.HTTPNotFound as e:
        _error_event(request, 404, e.text)
        if request.path.endswith((".json", ".csv")):
            raise
        text = "" if (e.text or "").startswith("404:") else (e.text or "")   # маршрут не знайдено: aiohttp пише «404: Not Found»
        return render("error.html", request, status=404, rugged=not text or text in RUGGED,
                      message=text or "The link you followed is gone, like the liquidity.")
    except web.HTTPException:
        raise
    except ConnectRequired as e:
        if request.path.endswith(".json"):
            return _jerr(str(e), 401)
        return render("connect.html", request, mint=e.mint, t_from=e.t_from, t_to=e.t_to,
                      demo_mint=(_demo(request.app) or {}).get("mint"), status=401)
    except WebError as e:
        _error_event(request, e.status, str(e))
        if request.path.endswith(".json"):
            return _jerr(str(e), e.status)                             # графік читає JSON і показує причину, а не порожнечу
        return render("error.html", request, message=str(e), status=e.status)
    except Exception:
        log.exception("page %s failed", request.path)
        _error_event(request, 500, "Something broke on our side.")
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

    def count(self, key, now=None):
        """Скільки ключ набрав сьогодні."""
        day = int((time.time() if now is None else now) // 86400)
        with self._lock:
            rec = self.n.get(key)
            return rec[1] if rec and rec[0] == day else 0

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


async def _ai_balance(app):
    """Скільки лишилось на відповіді агента: ліміт ключа і гроші на акаунті OpenRouter, не частіше ніж раз на 10 хв (запити
    безкоштовні, але не на кожне відкриття дашборда). None — агента на сервері нема або провайдер не відповів."""
    c, a = app["ai_balance"], app.get("assistant")
    if a is None or not hasattr(a, "balance"):
        return None
    if c["at"] and time.time() - c["at"] < CREDITS_TTL:
        return c["v"]
    try:
        v = await asyncio.to_thread(a.balance)
    except Exception:  # noqa: BLE001
        v = None
    c.update(v=v, at=time.time())
    return v


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
    daily, net = app["browse_daily"], _ip_key(_client_ip(request))
    # a wallet counts for itself and for its network: wallets are free, so seven of them from one address would
    # otherwise take the whole site's day and close every new token for everyone until midnight
    keys = [(f"acct:{pk}", s.get("browse_per_day", 150)), (f"net:{net}", s.get("browse_per_day_net", 600))] if pk \
        else [(f"ip:{net}", s.get("browse_per_day_guest", 30))]
    gcap = s.get("browse_global_per_day", 300)
    if daily.left("global", gcap) <= 0:
        _limit(app, pk, "browse", "site")
        raise WebError("Today's chart budget for new tokens is used up. The demo is always open; more tomorrow.", 429)
    for key, cap in keys:
        if daily.left(key, cap) <= 0:
            _limit(app, pk, "browse", "wallet" if key.startswith("acct:") else "network")
            raise WebError("You have used today's chart budget from this address. Connect a wallet for more, or come back tomorrow."
                           if not pk else "You have used today's chart budget for this wallet. The demo is always open; more tomorrow."
                           if key.startswith("acct:") else "Your network has used today's chart budget. The demo is always open; more tomorrow.", 429)
    for key, _ in keys + [("global", 0)]:
        daily.add(key, est)

    def settle(actual):
        d = int(actual) - int(est)
        if d:
            for key, _ in keys + [("global", 0)]:
                daily.add(key, d)
    return settle


def _usage_take(app, pk, n, net=None):
    """Скільки з n рядків журналу (перегляди, кліки) цього гаманця ще влазить у сьогоднішні стелі — стільки й списує.

    Перегляд чи клік нічого не коштують, тож без стелі будь-який підключений гаманець міг би циклом писати журнал,
    доки не скінчиться диск: 1000 рядків на гаманець, 3000 на мережу (гаманці безкоштовні: тридцять нових з однієї адреси
    інакше заповнили б спільну стелю підробленими кліками) і 30 000 на сайт за добу."""
    s, daily = app["s"], app["usage_daily"]
    keys = [(f"ev:{pk}", int(s.get("usage_events_per_day", 1000)))]
    if net:
        keys.append((f"ev:net:{net}", int(s.get("usage_events_net_per_day", 3000))))
    keys.append(("ev:global", int(s.get("usage_events_global_per_day", 30000))))
    ok = min([int(n)] + [daily.left(k, cap) for k, cap in keys])
    if ok <= 0:
        return 0
    for k, _ in keys:
        daily.add(k, ok)
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


# Закрита копія сайту (dev.tracced.xyz, власник 30.09: «щоб тільки я мав доступ до робочих сторінок»): сторінки, дані й
# API — лише гаманцям власника (ADMIN_WALLETS). Решта бачить закриті двері з кнопкою входу і нічого більше; пошуковикам —
# noindex. Відкрите лише те, без чого не працює сам вхід: статика, /auth/*, /health (перевірка автодеплою), robots.txt.
PRIVATE_OPEN = ("/static/", "/auth/", "/health", "/robots.txt", "/favicon.ico")


def _private_site(app):
    """Цей сервер — закрита копія цілком: його власна адреса (SITE_URL) серед private_hosts. Тоді закрито під будь-яким
    ім'ям, з яким до нього прийшли, — другий замок, якщо колись у проксі з'явиться ще одне ім'я для нього (власник, 30.09:
    «ніколи більше такого не допускай, щоб до dev був доступ у пабліка»)."""
    host = (urllib.parse.urlparse(_site_url(app)).hostname or "").lower().rstrip(".")
    return bool(host) and host in {str(h).lower().rstrip(".") for h in (app["s"].get("private_hosts") or [])}


def _private_host(request):
    if _private_site(request.app):
        return True
    host = (request.host or "").split(":")[0].lower().strip().rstrip(".")   # з крапкою в кінці — те саме ім'я (рев'ю 01.10)
    return host in {str(h).lower().rstrip(".") for h in (request.app["s"].get("private_hosts") or [])}


@web.middleware
async def private_mw(request, handler):
    if not _private_host(request):
        return await handler(request)
    shut = not request.path.startswith(PRIVATE_OPEN) and request.get("acct") not in request.app["admins"]
    if shut and (request.method != "GET" or request.path.endswith((".json", ".csv")) or request.path.startswith("/api/")):
        resp = web.json_response({"error": "This copy of tracced is private."}, status=403)
    elif shut:
        resp = render("private.html", request, status=403)
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as e:
            e.headers["X-Robots-Tag"] = "noindex, nofollow"
            raise
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


async def robots_txt(request):
    """Закрита копія — нікому нічого; публічний сайт — усе, крім кабінетів і входу."""
    if _private_host(request):
        return web.Response(text="User-agent: *\nDisallow: /\n")
    return web.Response(text="User-agent: *\nDisallow: /admin\nDisallow: /me\nDisallow: /auth/\nDisallow: /api/\n")


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


GATE_TTL_S = 6 * 3600       # вік і баланс гаманця для денної стелі читаються знову через шість годин: баланс рухається


def _wallet_gate(app, pk, now=None):
    """Чи гаманець новий або порожній (власник, 05.10: денну стелю обходили, щоразу підключаючи свіжий гаманець).
    Молодший за `new_wallet_days` чи з балансом під `new_wallet_min_sol` SOL — тоді `runs_per_day_new_wallet` живих
    аналізів на добу. Баланс — публічна нода (0 кредитів), вік — одна сторінка підписів (1 кредит Helius, у кеші віку).
    Вік рахується лише точний: гаманець з тисячею транзакцій за тиждень — це торгівля, а не свіжий гаманець для обходу.
    Не вдалось прочитати — не обмежуємо: наш збій не має карати людей, а решта стель стоїть. Синхронна: у потоці."""
    s, now = app["s"], time.time() if now is None else now
    hit = app["wallet_gate"].get(pk)
    if hit and now - hit[0] < GATE_TTL_S:
        return hit[1]
    ages, sol, age_days = app.get("ages"), None, None
    if ages is not None:
        try:
            sol = ages.balances([pk]).get(pk)
        except Exception:  # noqa: BLE001 — нода не відповіла: балансу не знаємо
            sol = None
        try:
            if not ages.paused():
                o = ages.oldest_tx(pk, full=False) or {}
                if o.get("exact") and o.get("oldest_ms"):
                    age_days = (now * 1000 - o["oldest_ms"]) / 86_400_000
        except Exception:  # noqa: BLE001 — вік не прочитали: віку не знаємо
            age_days = None
    why = ("new" if age_days is not None and age_days < float(s.get("new_wallet_days", 7)) else
           "empty" if sol is not None and sol < float(s.get("new_wallet_min_sol", 0.01)) else None)
    out = {"limited": bool(why), "why": why, "sol": sol, "age_days": None if age_days is None else round(age_days, 1)}
    if len(app["wallet_gate"]) > 20_000:
        app["wallet_gate"].clear()
    app["wallet_gate"][pk] = (now, out)
    return out


def _gate_cached(app, pk):
    """Те саме з пам'яті, без мережі: сторінка токена показує лічильник, поки Analyze не перевірив гаманець сам."""
    hit = app["wallet_gate"].get(pk) if pk else None
    return hit[1] if hit and time.time() - hit[0] < GATE_TTL_S else None


def _runs_left(app, pk, dev, ip):
    """(скільки живих аналізів людині лишилось сьогодні, який лічильник це вирішив: "person" чи "network").

    Найменше з трьох лічильників. Гаманець і браузер мають спільну стелю `runs_per_day`, тож інший гаманець у тому ж
    браузері нових спроб не дає; мережа має свою, вищу, `runs_per_ip_per_day`: на неї натрапляє інкогніто з новим
    гаманцем, а люди в одному офісі — рідко. "network" — лише коли людина свої ще має, а вичерпала мережа: тоді вікно
    не каже «ви використали свої п'ять»."""
    s = app["s"]
    cap = int(s.get("runs_per_day", 1))
    own = _person_cap(app, pk) - app["accounts"].runs_today(pk)     # новий чи порожній гаманець: своя, менша стеля
    person = own
    if dev:
        person = min(person, app["runs_daily"].left("dev:" + dev, cap))
    net = app["runs_daily"].left(_ip_key(ip), int(s.get("runs_per_ip_per_day", 10)))
    gate = _gate_cached(app, pk)
    why = "network" if net <= 0 < person else ("newwallet" if gate and gate["limited"] and own <= 0 else "person")
    return max(0, min(person, net)), why


def _person_cap(app, pk):
    """Денна стеля людини: `runs_per_day`, а гаманцю, який Analyze визнав новим чи порожнім, — `runs_per_day_new_wallet`."""
    s, gate = app["s"], _gate_cached(app, pk)
    cap = int(s.get("runs_per_day", 1))
    return min(cap, int(s.get("runs_per_day_new_wallet", 1))) if gate and gate["limited"] else cap


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


def _cross_origin(request):
    """Браузер надіслав форму з іншого сайту: Origin чи Referer є і не наш. Піддомен (dev.tracced.xyz) — той самий «сайт»
    для кук SameSite=Lax, тож кука гаманця поїхала б; без заголовків (не браузер) — не вважаємо чужим."""
    from urllib.parse import urlsplit
    src = request.headers.get("Origin") or request.headers.get("Referer") or ""
    return bool(src) and urlsplit(src).netloc != request.host


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


WRITE_ROUTES = {"me_wallets_csv"}          # GET, але пише в журнал (експорт): рахується, як і будь-який POST


def _acct_route(fn):
    """Маршрут акаунта: лише з цього сайту (для POST) і лише з кукою гаманця → fn(request, pubkey). Зміни акаунта
    (POST і експорт) — не більше `acct_writes_per_day` на гаманець: кожна перечитує й переписує файл акаунта і пише
    рядок журналу, тож безкоштовний гаманець у циклі інакше роздував би диск і журнал без меж."""
    async def wrapped(request):
        if request.method == "POST" and not _same_origin(request):
            return _jerr("Requests must come from this site.", 403)
        pk = request.get("acct")
        if not pk:
            return _jerr("Sign in with your wallet first.", 401)
        app = request.app
        if (request.method == "POST" or fn.__name__ in WRITE_ROUTES) and pk not in app["admins"]:
            daily, s = app["usage_daily"], app["s"]
            if daily.left("w:global", int(s.get("acct_writes_global_per_day", 20000))) <= 0 \
                    or not daily.take("w:" + pk, int(s.get("acct_writes_per_day", 500))):
                return _jerr("Too many changes from this wallet today. More tomorrow.", 429)
            daily.add("w:global", 1)                    # і на весь сайт: гаманці, зібрані тижнями, теж не роздують журнал
        return await fn(request, pk)
    wrapped.__name__ = fn.__name__
    return wrapped


# ───────────────────────── сповіщення в Telegram ─────────────────────────

UA_HEADERS = {"User-Agent": "tracced/0.5 (+https://tracced.xyz)"}   # Jupiter відповідає 403 на типовий підпис бібліотеки


def _alerts_live(app):
    """Сповіщення справді працюють на цьому сервері: є ключ бота і ALERTS=1 (тоді запущені бот і потік). Лише ключ —
    замало: картка обіцяла б прив'язку, яку ніхто не прийме (рев'ю 30.09)."""
    return bool(app["tg"]["token"]) and bool(app["tg"].get("on"))


def _alerts_allowed(app, pk):
    """Поки закритий тест — лише гаманці власника; потім alerts_open у налаштуваннях відкриває всім."""
    return bool(pk) and (pk in app["admins"] or bool(app["s"].get("alerts_open")))


def _site_url(app):
    return (os.getenv("SITE_URL") or ("https://" + os.getenv("WEB_DOMAIN") if os.getenv("WEB_DOMAIN") else "https://tracced.xyz")).rstrip("/")


@_acct_route
async def me_tg_link(request, pk):
    """Посилання в бота з одноразовим кодом: відкриваєш, тиснеш Start — і цей Telegram прив'язано до цього гаманця."""
    app = request.app
    if not _alerts_allowed(app, pk):
        return _jerr("Alerts are in a closed test for now.", 403)
    if not _alerts_live(app):
        return _jerr("Alerts are not set up on this server yet.", 503)
    if not app["tg"]["name"] or not app["tg"].get("checked"):   # ім'я ще не підтвердив сам Telegram: код не піде чужому боту (рев'ю 01.10)
        return _jerr("Telegram is still starting on this server. Try again in a minute.", 503)
    code = app["tg_codes"].issue(pk)
    app["events"].add(pk, "tg_link")                        # натиснув Connect: чи дійшов до Start, скаже подія telegram
    return web.json_response({"url": f"https://t.me/{app['tg']['name']}?start={code}"}, headers={"Cache-Control": "no-store"})


@_acct_route
async def me_tg_unlink(request, pk):
    request.app["accounts"].clear_telegram(pk)
    _unwatch(request.app, pk)
    request.app["events"].add(pk, "telegram", on=0, via="site")
    return web.json_response({"ok": True})


@_acct_route
async def me_wallet_json(request, pk):
    """Картка гаманця зі списку (власник, 30.09): хто це (ім'я, X, застосунок), вік, спонсор і біржа, і в яких ще збережених
    аналізах людини він траплявся. Лише про сам гаманець — нічого про токен, з аналізу якого його зберегли (власник, 01.10):
    ні міток, ні угод, ні «скільки гаманців профінансував той самий спонсор». Усе з уже збережених результатів — жодного
    запиту до Solana Tracker; 30 днів — окремо, /wallet_profile.json."""
    app = request.app
    w = request.query.get("wallet", "")
    acct = app["accounts"].load(pk)
    meta = (acct.get("wallets") or {}).get(w)
    if not meta:
        raise web.HTTPNotFound(text="That wallet is not in your watchlist.")

    def build():
        jobs = app["jobs"]
        src = jobs.get(meta.get("from_job") or "")
        src = src if src and src.status == "done" and src.result else None
        out = {"wallet": w, "idn": None, "age": None, "funder": None, "exchange": None, "service": False, "seen": []}
        if src:
            r = src.result
            fnd = (r.get("funders") or {}).get(w)
            out.update(idn=(r.get("identities") or {}).get(w), age=(r.get("ages") or {}).get(w), funder=fnd,
                       exchange=exch_mod.KNOWN.get(fnd) if fnd else None, service=bool(fnd) and fnd in set(r.get("services") or []))
        saved = sorted((acct.get("analyses") or {}).items(), key=lambda kv: -((kv[1] or {}).get("added_ms") or 0))
        for jid, _ in saved[:200]:                               # «Seen in», як на результаті: збережене самою людиною, новіше першим
            other = jobs.get(jid)
            if not other or other.status != "done" or not other.result:
                continue
            if src and (other.id == src.id or (other.mint == src.mint and other.t_from == src.t_from and other.t_to == src.t_to)):
                continue
            row = next((x for x in other.result.get("rows") or [] if x.get("wallet") == w), None)
            if row:
                out["seen"].append({"job": other.canon or other.id, "symbol": other.symbol, "from": other.t_from, "to": other.t_to,
                                    "mult": row.get("multiple") or 0, "real": row.get("realized_usd") or 0})
            if not out["idn"]:
                out["idn"] = (other.result.get("identities") or {}).get(w)
        return out
    return web.json_response(await asyncio.to_thread(build), headers={"Cache-Control": "no-store"})


AFTER_TTL = 900


def _after_on(request):
    """«After the alerts» лишається на закритій копії, поки власник його допрацьовує (04.10: «це ще допрацюю потім»).
    after_alerts: draft (так за замовчуванням) — лише на private_hosts; on — усюди; off — ніде."""
    v = str(request.app["s"].get("after_alerts", "draft"))
    return v == "on" or (v == "draft" and _private_host(request))


@_acct_route
async def me_after_json(request, pk):
    """«Що було після алерту» (власник, 04.10): перші покупки токенів гаманцями з дзвіночком за останні дні і що токен
    зробив далі, від ціни покупки (after.py). Нема жодного дзвіночка — найновіші гаманці зі списку. 30 днів гаманця — з
    кешу картки або 1-5 запитів, доба свічок після покупки — 1-2 запити; усе під денним бюджетом графіків людини
    (власник поза ним). Порахована відповідь живе AFTER_TTL секунд."""
    app, s = request.app, request.app["s"]
    if not _after_on(request):
        return _jerr("Not here yet.", 404)
    hit = app["after_memo"].get(pk)
    if hit and time.time() - hit[0] < AFTER_TTL:
        return web.json_response(hit[1], headers={"Cache-Control": "no-store"})
    ws = app["accounts"].load(pk).get("wallets") or {}
    pick = [w for w, m in ws.items() if (m or {}).get("alert")]
    basis = "bells" if pick else "newest"
    if not pick:
        pick = [w for w, _ in sorted(ws.items(), key=lambda kv: -((kv[1] or {}).get("added_ms") or 0))]
    pick = pick[:int(s.get("after_wallets", 10))]
    now, st, stop = int(time.time() * 1000), app["st"], []

    def budget(est):
        """Денний бюджет графіків людини: вичерпано — рахуємо те, що вже є, і кажемо про це."""
        try:
            return _browse_budget(request, est)
        except WebError as e:
            stop.append(str(e))
            return None

    def paid(what, fn, est, mint=None):
        settle = budget(est)
        if settle is None:
            return None
        with st.meter():
            req0 = st.requests_here()
            try:
                return fn()
            except Exception as e:  # noqa: BLE001 — один токен чи гаманець не валить решту
                log.warning("after %s: %s", what, e)
                return None
            finally:
                n = st.requests_here() - req0
                settle(n)
                _spend(app, pk, what, st=n, mint=mint)

    def cards():
        out = {}
        for w in pick:
            c = app["profile_cache"].get(f"v{profile.VERSION}:{w}")
            if c is None and not stop and hasattr(st, "wallet_swaps"):
                c = paid("after-profile", lambda w=w: _profile_now(app, w), 3)
            if c is not None:
                out[w] = c
        return out
    got = await asyncio.to_thread(cards)
    ms = sorted((m for w, c in got.items() for m in after_mod.moments(c, w, now)), key=lambda m: -m["t"])[:int(s.get("after_rows", 40))]
    infos = {m["mint"]: hit[1] for m in ms if (hit := app["overview_cache"].get(m["mint"])) and hit[1] is not None}

    def candles():
        out = {}
        for m in ms:
            key = (m["mint"], m["t"])
            if stop or key in out:
                continue
            a, b = m["t"] - after_mod.STEP, min(now, m["t"] + after_mod.HOURS * HOUR)

            def load(m=m, a=a, b=b):
                info = infos.get(m["mint"])
                if info is None:                       # міграція з кривої: без неї свічки до переїзду пропали б
                    try:
                        info = infos[m["mint"]] = pipeline.token(st, m["mint"])
                    except Exception:  # noqa: BLE001
                        info = None
                return pipeline._chart(st, m["mint"], "5m", a, b, info)
            out[key] = paid("after-chart", load, 2, m["mint"])
        return out
    cs = await asyncio.to_thread(candles)
    rows = []
    for m in ms:
        trades = next((t.get("trades") or [] for t in got[m["wallet"]].get("recent") or [] if t.get("mint") == m["mint"]), [])
        o = after_mod.outcome(m, cs.get((m["mint"], m["t"])), trades, now) if cs.get((m["mint"], m["t"])) is not None else {}
        rows.append(dict(m, **o, tags=((ws.get(m["wallet"]) or {}).get("my_tags") or [])[:2]))
    out = {"rows": rows, "summary": after_mod.summary(rows), "basis": basis, "wallets": len(pick), "days": after_mod.DAYS,
           "hours": after_mod.HOURS, "partial": stop[0] if stop else None, "at": now}
    if not stop:
        app["after_memo"][pk] = (time.time(), out)
        if len(app["after_memo"]) > 500:
            app["after_memo"].clear()
    return web.json_response(out, headers={"Cache-Control": "no-store"})


@_acct_route
async def me_tg_status(request, pk):
    """Чи прив'язано Telegram (сторінка питає, поки людина тисне Start у боті) і налаштування; власнику — ще й стан потоку."""
    app = request.app
    a = app["accounts"].load(pk)
    tg = a.get("telegram") or {}
    out = {"linked": bool(tg.get("chat")), "user": tg.get("user") or "", "prefs": alerts_mod.prefs_of(a.get("alerts"), app["s"].get("alerts_min_usd"))}
    if pk in app["admins"]:
        out["state"] = dict(app["alerts_state"], st_today=int(app["s"].get("alerts_st_per_day", 3000)) - _alerts_st_left(app),
                            st_per_day=int(app["s"].get("alerts_st_per_day", 3000)))
    return web.json_response(out, headers={"Cache-Control": "no-store"})


@_acct_route
async def me_alerts(request, pk):
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    if not _alerts_allowed(request.app, pk):
        return _jerr("Alerts are in a closed test for now.", 403)
    prefs = alerts_mod.prefs_of(body, request.app["s"].get("alerts_min_usd"))
    request.app["accounts"].set_alerts(pk, prefs)
    return web.json_response({"ok": True, "prefs": prefs})


def tg_reply(app, update):
    """Відповідь бота на одне оновлення: (чат, текст) або None. /start <код> прив'язує чат до гаманця, /stop відв'язує.
    Лише особисті чати: у групі сповіщення бачили б усі."""
    m = (update or {}).get("message") or {}
    chat_o = m.get("chat") or {}
    chat, text = chat_o.get("id"), str(m.get("text") or "").strip()
    if not isinstance(chat, int) or chat_o.get("type") != "private":
        return None
    site, acc = _site_url(app), app["accounts"]
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        pk = app["tg_codes"].consume(parts[1].strip() if len(parts) > 1 else "")
        if not pk:
            return chat, f"This link has expired or was used already. Open {site}/me and press <b>Connect Telegram</b> again."
        # один чат — один гаманець. Уже прив'язаний до іншого — не переходить мовчки: інакше чуже посилання, надіслане
        # людині, вимикало б її сповіщення і показувало б відправнику її нік у Telegram (рев'ю 01.10)
        other = next((a["pubkey"] for a in acc.all() if (a.get("telegram") or {}).get("chat") == chat and a["pubkey"] != pk), None)
        if other:
            return chat, (f"This chat already gets alerts for wallet <code>{alerts_mod.short(other)}</code>. "
                          f"Send /stop here first, then press <b>Connect Telegram</b> again at {site}/me.")
        user = str((m.get("from") or {}).get("username") or "")
        acc.set_telegram(pk, chat, "@" + user if user else "")
        app["events"].add(pk, "telegram", on=1)
        return chat, (f"Connected to wallet <code>{alerts_mod.short(pk)}</code>.\n"
                      f"Turn on the bell for a list at {site}/me, and its wallets' buys and sells come here. /stop ends it.")
    if text == "/stop":
        n = 0
        for a in acc.all():
            if (a.get("telegram") or {}).get("chat") == chat:
                acc.clear_telegram(a["pubkey"])
                _unwatch(app, a["pubkey"])
                app["events"].add(a["pubkey"], "telegram", on=0, via="bot")
                n += 1
        return chat, (f"Alerts stopped. Connect again at {site}/me." if n else "This chat is not connected to any wallet.")
    return chat, f"I send buys and sells of the wallets in your tracced lists. Connect at {site}/me."


class TgError(RuntimeError):
    def __init__(self, msg, code=None, retry=None):
        super().__init__(msg)
        self.code, self.retry = code, retry


async def _tg_call(http, token, method, **params):
    async with http.post(f"https://api.telegram.org/bot{token}/{method}", json=params,
                         timeout=aiohttp.ClientTimeout(total=45)) as r:
        d = await r.json(content_type=None)
    if not d.get("ok"):
        raise TgError(f"telegram {method}: {str(d.get('description'))[:120]}", d.get("error_code"),
                      (d.get("parameters") or {}).get("retry_after"))
    return d.get("result")


async def _tg_send(app, http, chat, text, pk=None):
    """Одне повідомлення. 429 — одна пауза стільки, скільки просить Telegram, і ще спроба; 403 (бота заблоковано чи чат
    зник) — чат відв'язується від гаманця, інакше він вічно коштував би запитів і нікому не приходив (рев'ю 30.09)."""
    for attempt in (0, 1):
        try:
            await _tg_call(http, app["tg"]["token"], "sendMessage", chat_id=chat, text=text, parse_mode="HTML",
                           disable_web_page_preview=True)
            return True
        except TgError as e:
            if e.code == 429 and attempt == 0 and (e.retry or 0) <= 30:
                await asyncio.sleep(float(e.retry or 3))
                continue
            app["alerts_state"]["errors"] += 1
            log.warning("telegram send to %s: %s", str(chat)[-4:], e)
            if e.code == 403 and pk:
                await asyncio.to_thread(app["accounts"].clear_telegram, pk)
                app["events"].add(pk, "telegram", on=0, via="blocked", bg=True)
                _unwatch(app, pk)                               # лише цей підписник, решта отримує далі (рев'ю 01.10)
            _alert_fail(app, pk or "system", "tg_blocked" if e.code == 403 else "tg_429" if e.code == 429 else "tg_other")
            return False
        except Exception as e:  # noqa: BLE001 — мережа: лише в журнал
            app["alerts_state"]["errors"] += 1
            log.warning("telegram send to %s: %s", str(chat)[-4:], e)
            _alert_fail(app, pk or "system", "tg_other")
            return False
    return False


async def _tg_bot_loop(app):
    """Бот: довге опитування getUpdates, відповіді на /start і /stop. Ключ не потрапляє в журнал."""
    token, offset = app["tg"]["token"], 0
    async with aiohttp.ClientSession(headers=UA_HEADERS) as http:
        while True:
            try:
                if not app["tg"].get("checked"):    # ім'я — завжди від самого Telegram: у .env могла бути описка чи «@»
                    app["tg"]["name"] = (await _tg_call(http, token, "getMe") or {}).get("username") or ""
                    app["tg"]["checked"] = bool(app["tg"]["name"])
                    app["alerts_state"]["bot"] = app["tg"]["name"]
                ups = await _tg_call(http, token, "getUpdates", offset=offset, timeout=30, allowed_updates=["message"])
                for u in ups or []:
                    offset = max(offset, int(u.get("update_id") or 0) + 1)
                    reply = await asyncio.to_thread(tg_reply, app, u)
                    if reply:
                        await _tg_send(app, http, *reply)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("telegram bot: %s", e)
                app["alerts_state"]["bot_error"] = str(e)[:160]   # власник бачить у /me/telegram.json, чому Connect не працює
                await asyncio.sleep(10)


class _Pace:
    """Спільний темп запитів сповіщень до безкоштовної ноди. Схема KOLS-радара (08.08): publicnode тримає ≈20 запитів на
    секунду на весь проєкт; відмова «Rate limit» — це «пригальмуй», а не «нода впала»: пауза для всіх, а не швидкі
    повтори, які лише додають навантаження (живий прогін 01.10: 1 513 відмов за 2,5 хв на ботах)."""

    def __init__(self, rps):
        self.gap, self.next, self.paused, self.lock = 1.0 / max(0.1, float(rps)), 0.0, 0.0, asyncio.Lock()

    async def wait(self):
        while True:
            async with self.lock:
                now = time.monotonic()
                at = max(now, self.next, self.paused)
                self.next = at + self.gap
            if at > now:
                await asyncio.sleep(at - now)
            if time.monotonic() >= self.paused:       # пауза, що почалась, поки чекали свого місця, діє і на нас (рев'ю 01.10)
                return

    def slow(self, seconds):
        self.paused = max(self.paused, time.monotonic() + seconds)


def _limited(e):
    s = str(e).lower()
    return "-32005" in s or "429" in s or "rate limit" in s or "too many" in s


async def _alert_rpc(app, http, method, params):
    """Запит сповіщень до ноди: у спільному темпі; на відмову за лімітом — пауза для всіх і виняток."""
    await app["alerts_pace"].wait()
    try:
        async with app["alerts_sem"]:
            return await _rpc(http, app["s"].get("alerts_rpc_url"), method, params)
    except Exception as e:  # noqa: BLE001
        if _limited(e):
            app["alerts_pace"].slow(float(app["s"].get("alerts_slow_s", 1.5)))
        raise


def _unwatch(app, pk):
    """Прибрати один гаманець-підписник з карти потоку одразу, не чекаючи перевірки (раз на alerts_check_s), і не чіпаючи решту."""
    wm = app.get("alerts_wm") or {}
    app["alerts_wm"] = {w: kept for w, v in wm.items() if (kept := [x for x in v if x.get("pk") != pk])}


def _alert_fail(app, pk, why):
    """Рядок журналу про збій сповіщення, не більше 30 на причину за годину: зайнятий гаманець у списку чи лежача нода
    інакше писали б рядок на кожну транзакцію (рев'ю 01.10). Лічильник errors у стані рахує все."""
    hour, rec = int(time.time() // 3600), app["alerts_fails"]
    n = rec.get(why)
    n = rec[why] = [hour, 1] if not n or n[0] != hour else [hour, n[1] + 1]
    if n[1] <= 30:
        app["events"].add(pk, "alert_fail", why=why, bg=True)


def _watch_now(app):
    s = app["s"]
    return alerts_mod.watch_map(app["accounts"].all(), app["admins"], bool(s.get("alerts_open")),
                                int(s.get("alerts_max_wallets", 10)), s.get("alerts_min_usd"))


async def _rpc(http, url, method, params):
    async with http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                         timeout=aiohttp.ClientTimeout(total=20)) as r:
        d = await r.json(content_type=None)
    if d.get("error"):                                  # помилка ноди — не «транзакції ще нема» (рев'ю 30.09)
        raise RuntimeError(f"rpc {method}: {str(d['error'])[:120]}")
    return d.get("result")


async def _sol_price(app, http):
    """Ціна SOL у доларах: Jupiter без ключа, п'ять хвилин з пам'яті; збій — остання відома."""
    px, at = app["sol_px"]
    if px and time.time() - at < 300:
        return px
    try:
        async with http.get("https://lite-api.jup.ag/price/v3?ids=" + alerts_mod.WSOL, timeout=aiohttp.ClientTimeout(total=10)) as r:
            v = float(((await r.json(content_type=None)).get(alerts_mod.WSOL) or {}).get("usdPrice") or 0)
        if v > 0:
            app["sol_px"] = [v, time.time()]
            return v
    except Exception as e:  # noqa: BLE001
        log.warning("sol price: %s", e)
    return px


def _token_cached(app, mint):
    """Назва й капа з пам'яті (10 хв), без запиту: для повідомлення, якому платити вже не можна."""
    hit = app["alerts_tok"].get(mint)
    return hit[1] if hit and time.time() - hit[0] < 600 else {}


async def _token_facts(app, mint):
    """Назва і капа токена для повідомлення: один запит Solana Tracker на новий токен, далі 10 хвилин з пам'яті."""
    hit = app["alerts_tok"].get(mint)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    wait = app["alerts_tok_wait"].get(mint)
    if wait:                                         # той самий токен уже питаємо: чекаємо ту відповідь, а не платимо вдруге
        return await asyncio.shield(wait)
    fut, facts = asyncio.get_running_loop().create_future(), {}
    app["alerts_tok_wait"][mint] = fut
    try:
        facts = await _token_facts_fetch(app, mint)
    finally:
        app["alerts_tok_wait"].pop(mint, None)
        fut.set_result(facts)
    return facts


async def _token_facts_fetch(app, mint):
    st = app["st"]

    def work():
        with st.meter():
            n0 = st.requests_here()
            try:
                return alerts_mod.token_facts(st.token_report(mint))
            except Exception:  # noqa: BLE001 — без назви повідомлення все одно йде: з адресою
                return {}
            finally:
                _alerts_spent(app, st.requests_here() - n0, mint)
    facts = await asyncio.to_thread(work)
    if len(app["alerts_tok"]) > 2000:
        app["alerts_tok"].clear()
    app["alerts_tok"][mint] = (time.time(), facts)
    return facts


async def _sold_share(app, wallet, ev):
    """Угоди гаманця на цьому токені з Solana Tracker (1 запит, свіжі) → скільки позиції продано з початку. None — не вийшло:
    повідомлення тоді каже частку цієї угоди від того, що було перед нею."""
    st = app["st"]

    def work():
        with st.meter():
            n0 = st.requests_here()
            try:
                return st.wallet_token_trades(wallet, ev["mint"], max_pages=2, fresh=True, store=False)
            except Exception:  # noqa: BLE001
                return None
            finally:
                _alerts_spent(app, st.requests_here() - n0, ev["mint"])
    trades = await asyncio.to_thread(work)
    return alerts_mod.sold_share(trades, ev) if trades else None


def _alerts_spent(app, n, mint):
    """Запити Solana Tracker, які щойно пішли на сповіщення: у журнал витрат і в добовий лічильник сповіщень."""
    _spend(app, "system", "alerts", st=n, mint=mint)
    if n:
        app["alerts_st_daily"].add("all", n)


def _alerts_st_left(app):
    """Скільки запитів Solana Tracker сповіщенням лишилось на сьогодні (UTC)."""
    return app["alerts_st_daily"].left("all", int(app["s"].get("alerts_st_per_day", 3000)))


def _hour_rec(app, chat):
    hour = int(time.time() // 3600)
    rec = app["alerts_hour"].get(chat)
    if not rec or rec[0] != hour:
        rec = app["alerts_hour"][chat] = [hour, 0]
    return rec


def _day_budget(app, pk):
    """Не більше alerts_per_day надісланих повідомлень на акаунт за добу UTC (власник, 02.10: 200). None — можна (і місце
    вже зайняте); 'day' — ліміт вичерпано, одне попередження на добу; False — мовчимо до 00:00 UTC. Рахуються лише ті, що
    підуть: пропущене годинною стелею місця в добовій не займає (див. _day_undo)."""
    cap, dc = int(app["s"].get("alerts_per_day", 200)), app["alerts_day"]
    if dc.take("a:" + pk, cap):
        return None
    return "day" if dc.take("w:" + pk, 1) else False


def _day_undo(app, pk):
    """Місце, яке зайняв _day_budget, звільняється: повідомлення не піде (годинна стеля)."""
    app["alerts_day"].add("a:" + pk, -1)


def _wallet_budget(app, pk, wallet):
    """Не більше alerts_per_wallet_day повідомлень від одного гаманця на акаунт за добу UTC (власник, 02.10: 50): бот, що
    торгує щохвилини, не з'їдає добову стелю всіх інших. None — можна (місце зайняте); 'wallet' — щойно вичерпано, одне
    попередження про цей гаманець; False — він мовчить до 00:00 UTC."""
    cap, dc = int(app["s"].get("alerts_per_wallet_day", 50)), app["alerts_day"]
    if dc.take("c:" + pk + ":" + wallet, cap):
        return None
    return "wallet" if dc.take("cw:" + pk + ":" + wallet, 1) else False


def _wallet_undo(app, pk, wallet):
    """Місце, яке зайняв _wallet_budget, звільняється: повідомлення не піде (стеля доби чи години)."""
    app["alerts_day"].add("c:" + pk + ":" + wallet, -1)


def _hour_budget(app, chat):
    """Не більше alerts_per_hour повідомлень на чат за годину. None — можна; 'first' — щойно вичерпано (одне
    попередження); False — мовчимо до наступної години."""
    cap, rec = int(app["s"].get("alerts_per_hour", 30)), _hour_rec(app, chat)
    rec[1] += 1
    return None if rec[1] <= cap else ("first" if rec[1] == cap + 1 else False)


def _st_open_now(app):
    """Те саме, що _st_open, але без очікування — для сповіщень: повідомлення не стоїть, поки Solana Tracker відповідає
    про залишок (до 1,5 хв, рев'ю 01.10). Залишок старший за 10 хв оновлюється у фоні; невідомий — можна."""
    reserve = _credits_reserve(app["s"])
    if not reserve:
        return True
    c = app["credits"]
    if not c["at"] or time.time() - c["at"] >= CREDITS_TTL:
        task = app.get("credits_task")
        if task is None or task.done():
            app["credits_task"] = asyncio.get_running_loop().create_task(_credits_left(app))
    return c["left"] is None or c["left"] >= reserve


async def _st_open(app):
    """Чи можна сповіщенням платити Solana Tracker: місячний залишок вище резерву (невідомий — можна). Нижче резерву
    повідомлення йде без назви, капи й частки проданого, але йде."""
    reserve = _credits_reserve(app["s"])
    if not reserve:
        return True
    left = await _credits_left(app)
    return left is None or left >= reserve


async def _alert_tx_safe(app, http, wallet, sig, via="stream", bt=None):
    """Задача на одну транзакцію; True — оброблено (чи нема що робити), False — не вийшло, страховка спробує знову.
    Черга не безмежна: зайнятий гаманець чи пил, що згадує гаманець, інакше ставили б тисячі задач, і алерти всіх
    запізнювались би без кінця — понад alerts_queue транзакція не береться (і не позначається обробленою). Несподіваний
    збій — у журнал і лічильник, а не «Task exception was never retrieved» (рев'ю 01.10)."""
    if app["alerts_pending"] >= int(app["s"].get("alerts_queue", 200)):
        _alert_fail(app, "system", "busy")
        return False
    app["alerts_pending"] += 1
    try:
        return await _alert_tx(app, http, wallet, sig, via, bt)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        app["alerts_seen"].pop(sig + ":" + wallet, None)
        app["alerts_state"]["errors"] += 1
        _alert_fail(app, "system", "crash")
        log.warning("alert %s: %s", sig[:10], e)
        return False
    finally:
        app["alerts_pending"] -= 1


async def _alert_tx(app, http, wallet, sig, via="stream", bt=None):
    """Одна транзакція гаманця зі списків: розібрати, відсіяти, надіслати кожному, хто за ним стежить. True — оброблено;
    False — транзакцію чи ціну SOL не отримали: позначку «оброблено» знято, страховка спробує знову (рев'ю 01.10: інакше
    угода губилась назавжди)."""
    if not app["alerts_wm"].get(wallet):              # за гаманцем уже ніхто не стежить (відв'язав Telegram, вимкнув дзвіночок)
        return True
    key = sig + ":" + wallet
    seen, inflight = app["alerts_seen"], app["alerts_inflight"]
    if key in seen:
        # ще в роботі в іншої задачі (потік читає, страховка дійшла): «не оброблено», щоб страховка не перескочила її
        # закладкою — якщо та спроба провалиться, наступне опитування візьме угоду знову (рев'ю 01.10)
        return key not in inflight
    seen[key] = time.time()
    inflight.add(key)
    try:
        return await _alert_tx_work(app, http, wallet, sig, via, bt, key)
    finally:
        inflight.discard(key)


async def _alert_tx_work(app, http, wallet, sig, via, bt, key):
    seen = app["alerts_seen"]
    st, s = app["alerts_state"], app["s"]
    if via == "poll":                                # потік цієї угоди не приніс за alerts_poll_grace_s: страховка спрацювала
        st["poll_caught"] = st.get("poll_caught", 0) + 1
        if bt and bt >= app["alerts_conn_at"] + float(s.get("alerts_poll_grace_s", 15)):
            st["poll_caught_live"] = st.get("poll_caught_live", 0) + 1   # угода вже при живому з'єднанні: потік її пропустив
    if len(seen) > 5000:                            # за віком, не за кількістю: ключ мусить дожити, поки страховка пройде повз
        edge = time.time() - float(s.get("alerts_backfill_min", 10)) * 60 - 2 * max(60.0, float(s.get("alerts_poll_s", 60)))
        for k in [k for k, v in seen.items() if v < edge]:
            del seen[k]
        if len(seen) > 50_000:
            for k in sorted(seen, key=seen.get)[:10_000]:
                del seen[k]
    params = [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": wallet_age_mod.TX_VERSION, "commitment": "confirmed"}]
    tx, err = None, None
    for pause in (0, 0.4, 0.8, 1.5, 3):              # п'ять спроб: нода ще не встигла віддати чи збій (замір 01.10: 25 з 25 з першої)
        if pause:
            await asyncio.sleep(pause)
        try:
            tx, err = await _alert_rpc(app, http, "getTransaction", params), None
        except Exception as e:  # noqa: BLE001
            err = e
        if tx:
            break
    if not tx:                                       # не мовчки (рев'ю 30.09) і не назавжди (рев'ю 01.10)
        seen.pop(key, None)
        st["errors"] += 1
        _alert_fail(app, "system", "rpc" if err else "tx_null")
        if err:
            log.warning("alerts getTransaction %s: %s", sig[:10], err)
        return False
    px = await _sol_price(app, http)
    if not px:                                       # без ціни SOL купівлю за SOL не відрізнити від переказу
        seen.pop(key, None)
        st["errors"] += 1
        _alert_fail(app, "system", "price")
        return False
    evs = alerts_mod.classify(tx, wallet, px)
    st["events"] += 1
    if app["activity"].done(wallet, sig):            # оброблене переживає перезапуск; повтор після невдалої відправки не рахується
        for ev in evs:                               # активність гаманця для Lists: кожна угода, хоч би що обрали підписники
            app["activity"].bump(wallet, ev["side"], int(ev.get("ts") or 0) * 1000 or None, ev.get("usd"))
    for ev in evs:
        # місце в годинній стелі кожного чату — ДО платних запитів і одразу: двадцять транзакцій водночас інакше всі
        # пройшли б перевірку і всі заплатили б (рев'ю 30.09, 01.10). Не надіслане все одно займає місце — це стеля
        subs = []
        for x in app["alerts_wm"].get(wallet) or []:
            if alerts_mod.wants(ev, x["prefs"]):
                b = _wallet_budget(app, x["pk"], wallet)  # спершу цей гаманець за добу, потім доба на акаунт, потім година на чат
                if b is None:
                    b = _day_budget(app, x["pk"])
                    if b is None:
                        b = _hour_budget(app, x["chat"])
                        if b is not None:
                            _day_undo(app, x["pk"])
                    if b is not None:
                        _wallet_undo(app, x["pk"], wallet)
                if b is not False:
                    subs.append((x, b))
        if not subs:
            continue
        # платне — лише поки є і місячний запас Solana Tracker, і добова частка сповіщень; інакше повідомлення йде без назви,
        # капи й частки проданого, але йде (план 0.8, п. 17)
        paid = any(b is None for _, b in subs) and _st_open_now(app) and _alerts_st_left(app) > 0
        # назва й капа токена і частка проданого — паралельно і не довше alerts_enrich_s: повідомлення не чекає повільне
        # джерело (власник, 01.10: «є транзакція — відправляється алерт»); те, що не встигло, допрацює в кеш на наступний
        # раз, а частка проданого, що запізнилась, просто не потрапляє в це повідомлення
        t_tok = asyncio.ensure_future(_token_facts(app, ev["mint"])) if paid else None
        t_share = asyncio.ensure_future(_sold_share(app, wallet, ev)) if paid and ev["side"] == "sell" and not ev.get("all") else None
        waits = [x for x in (t_tok, t_share) if x is not None]
        if waits:
            await asyncio.wait(waits, timeout=float(s.get("alerts_enrich_s", 2.5)))
        ok = lambda x: x is not None and x.done() and not x.cancelled() and x.exception() is None
        token = (t_tok.result() or {}) if ok(t_tok) else ({} if paid else _token_cached(app, ev["mint"]))   # без оплати — те, що вже в пам'яті
        share = t_share.result() if ok(t_share) else None
        if share:
            ev["total"], ev["step"] = share
        ev["late_s"] = max(0, int(time.time()) - int(ev.get("ts") or time.time()))
        async def deliver(sub, b):
            seen_ca = app["alerts_ca"].setdefault(sub["chat"], set())     # адреса токена — лише в першому повідомленні про нього
            first = False
            if b == "first":
                app["events"].add(sub["pk"], "alert_cap", bg=True)
                text = "⏸ More than " + str(s.get("alerts_per_hour", 30)) + " alerts this hour: the rest are skipped until the next hour."
            elif b == "day":
                app["events"].add(sub["pk"], "alert_cap", what="day", bg=True)
                text = "⏸ " + str(s.get("alerts_per_day", 200)) + " alerts today: the rest are skipped until 00:00 UTC."
            elif b == "wallet":                          # одна людина бачить його своїм тегом, як в алертах
                app["events"].add(sub["pk"], "alert_cap", what="wallet", bg=True)
                who = (sub.get("tags") or [None])[0] or (wallet[:4] + "…" + wallet[-4:])
                text = ("⏸ " + str(s.get("alerts_per_wallet_day", 50)) + " alerts from " + who
                        + " today: its trades are skipped until 00:00 UTC. Your other wallets keep coming.")
            else:
                first = ev["mint"] not in seen_ca
                if len(seen_ca) > 2000:
                    seen_ca.clear()
                seen_ca.add(ev["mint"])                  # до відправки: дві угоди водночас не дадуть адресу двічі
                text = alerts_mod.message(ev, wallet, sub, token, _site_url(app), ca=first, sizes=s.get("alerts_size_usd"))
            async with _chat_lock(app, sub["chat"]):     # у кожен чат — по одному і не частіше раза на секунду (ліміт Telegram)
                sent = await _tg_send(app, http, sub["chat"], text, sub["pk"])
                await asyncio.sleep(float(s.get("alerts_chat_gap_s", 1.0)))
            if not sent and first:
                seen_ca.discard(ev["mint"])              # не дійшло: адреса піде в наступному
            if sent and b is None:
                st["sent"] += 1
                app["alerts_day"].add("s:" + sub["pk"] + ":" + wallet, 1)    # скільки цей гаманець надіслав людині сьогодні (картка в Lists)
                st["last_ms"] = int(time.time() * 1000)
                # не дія людини (bg): сповіщення не робить підписника «активним» у дашборді (рев'ю 30.09)
                app["events"].add(sub["pk"], "alert", side=ev["side"], usd=round(ev["usd"]), mint=ev["mint"], bg=True,
                                  lag_ms=max(0, int(time.time() * 1000) - int(ev.get("ts") or 0) * 1000), tagged=bool(sub.get("tags")),
                                  new=ev.get("new"), total=ev.get("total"), via=via)
            return sent or b is not None
        # кожному підписнику — паралельно: затримка Telegram в одному чаті не тримає інших (рев'ю 01.10)
        if not any(await asyncio.gather(*(deliver(sub, b) for sub, b in subs))):
            seen.pop(key, None)                          # не дійшло нікому: страховка спробує знову
            return False
    return True


def _chat_lock(app, chat):
    locks = app["alerts_chat_locks"]
    if len(locks) > 5000:
        for c in [c for c, lk in locks.items() if not lk.locked()]:
            del locks[c]
    return locks.setdefault(chat, asyncio.Lock())


async def _alerts_poll(app, http, wallets):
    """Страховка потоку (схема KOLS-радара, 01.10): для кожного гаманця — підписи новіші за власну закладку опитування.
    Потік швидкий, але губить угоди на розривах і буває «підключеним, але мовчазним»; опитування знаходить їх за хвилину.

    Закладка своя (не та, що з потоку): інакше свіжий підпис з потоку перескочив би пропущений перед ним; вона в
    activity.json і переживає перезапуск. Гортаємо сторінками по 25 до закладки (не більше alerts_poll_pages), від старших
    до новіших. Угоди молодші за alerts_poll_grace_s лишаємо потоку. Старші за alerts_backfill_min не сповіщаємо (запізно),
    лише посуваємо закладку. Не оброблену (нода не віддала) — не перескакуємо: закладка стоїть перед нею. Новий гаманець
    спершу дістає закладку без сповіщень. Угоду, яку вже обробив потік, відсіє alerts_seen."""
    s, act = app["s"], app["activity"]
    grace, pages, limit = float(s.get("alerts_poll_grace_s", 15)), int(s.get("alerts_poll_pages", 4)), int(s.get("alerts_wallet_per_min", 30))
    for w in wallets:
        if w not in app["alerts_wm"]:
            continue
        now = time.time()                             # свій для кожного гаманця: прохід по тисячі триває хвилини (рев'ю 01.10)
        horizon = now - float(s.get("alerts_backfill_min", 10)) * 60
        base = act.last_sig(w)
        try:
            if not base:                              # новий: лише закладка
                sigs = await _alert_rpc(app, http, "getSignaturesForAddress", [w, {"limit": 1, "commitment": "confirmed"}])
                if sigs and sigs[0].get("signature"):
                    act.seen(w, sigs[0]["signature"])
                continue
            sigs, before, reached = [], None, False
            for _ in range(pages):
                q = {"limit": 25, "commitment": "confirmed", "until": base}
                if before:
                    q["before"] = before
                page = await _alert_rpc(app, http, "getSignaturesForAddress", [w, q]) or []
                sigs += page
                if len(page) < 25 or (page[-1].get("blockTime") or now) < horizon:
                    reached = True
                    break
                before = page[-1].get("signature")
        except Exception as e:  # noqa: BLE001
            log.warning("alerts poll %s: %s", w[:6], e)
            continue
        if not reached:
            _alert_fail(app, "system", "poll_gap")    # понад alerts_poll_pages сторінок нового: старіше за них не дочитали
        ready = [x for x in sigs if x.get("signature") and (x.get("blockTime") or now) <= now - grace]
        minute, fl = int(now // 60), app["alerts_flood"]
        for x in reversed(ready):                     # від старших до новіших
            if not x.get("err") and (x.get("blockTime") or 0) >= horizon:
                rec = fl.get(w)
                rec = fl[w] = [minute, 1] if not rec or rec[0] != minute else [minute, rec[1] + 1]
                if rec[1] > limit:                    # бот і для страховки: пропуск, позначений обробленим (рев'ю 01.10)
                    app["alerts_seen"][x["signature"] + ":" + w] = time.time()
                elif not await _alert_tx_safe(app, http, w, x["signature"], via="poll", bt=x.get("blockTime")):
                    break                             # не вийшло: закладка стоїть перед нею, наступне опитування спробує знову
            act.seen(w, x["signature"])


async def _alerts_poll_loop(app):
    """Страховка — окремою задачею, незалежно від потоку: коли нода потоку недоступна, опитування однаково йде (рев'ю
    01.10). Перше — за кілька секунд після старту: пропущене за час перезапуску. Далі раз на alerts_poll_s, але так, щоб
    опитування брало не більше alerts_poll_rps запитів на секунду."""
    s = app["s"]
    async with aiohttp.ClientSession(headers=UA_HEADERS) as http:
        await asyncio.sleep(5)
        while True:
            began = time.monotonic()
            wallets = sorted(app["alerts_wm"])
            if wallets:
                try:
                    await _alerts_poll(app, http, wallets)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.warning("alerts poll: %s", e)
            every = max(float(s.get("alerts_poll_s", 60)), len(wallets) / float(s.get("alerts_poll_rps", 4)))
            wake = app["alerts_poll_wake"]
            try:                                      # або раніше: потік щойно підключився — добрати проміжок без нього
                await asyncio.wait_for(wake.wait(), max(1.0, every - (time.monotonic() - began)))
            except asyncio.TimeoutError:
                pass
            wake.clear()


async def _alerts_watch_once(app, http, url, wm, primary=True):
    """Одне з'єднання з потоком: підписка на кожен гаманець (logsSubscribe mentions), нова транзакція — окремою задачею.

    Списки змінились — підписки додаються й знімаються в тому самому з'єднанні, без перепідключення: воно губило угоди
    тих секунд (рев'ю 01.10). На з'єднання — не більше alerts_subs_per_conn підписок (api.mainnet-beta рве з'єднання на
    101-й, рев'ю 01.10); гаманці понад це покриває лише страховка. Повертається, коли стежити більше нема за ким, або
    через alerts_fallback_min на запасній ноді (спробувати основну знову); кидає, коли з'єднання впало або потік
    пропускає більше, ніж приносить (ловить страховка, а не він)."""
    s = app["s"]
    sub_of, wallet_of, pending, next_id = {}, {}, {}, 0   # гаманець → підписка; підписка → гаманець; запит → (гаманець, дія)
    asked_at = {}                                          # запит → коли надіслали: без відповіді 10 с — надішлемо знову
    every, began, cap = float(s.get("alerts_check_s", 15)), time.monotonic(), int(s.get("alerts_subs_per_conn", 90))
    app["alerts_wm"] = wm
    app["activity"].watch(set(wm))
    ws = await asyncio.wait_for(http.ws_connect(url, heartbeat=20, max_msg_size=0, timeout=aiohttp.ClientWSTimeout(ws_close=10)), 20)
    app["alerts_conn_at"] = time.time()
    delivered, live0 = 0, app["alerts_state"].get("poll_caught_live", 0)   # що приніс потік і що за ним добрала страховка
    try:
        async def subscribe(w):
            nonlocal next_id
            next_id += 1
            pending[next_id] = (w, "sub")
            asked_at[next_id] = time.monotonic()
            await ws.send_json({"jsonrpc": "2.0", "id": next_id, "method": "logsSubscribe",
                                "params": [{"mentions": [w]}, {"commitment": "confirmed"}]})

        async def unsubscribe(w):
            nonlocal next_id
            sid = sub_of.pop(w, None)
            if sid is None:
                return
            wallet_of.pop(sid, None)
            next_id += 1
            pending[next_id] = (w, "unsub")
            await ws.send_json({"jsonrpc": "2.0", "id": next_id, "method": "logsUnsubscribe", "params": [sid]})

        for w in sorted(wm)[:cap]:
            await subscribe(w)
        app["alerts_state"].update(connected=True, url=url.split("//")[-1], wallets=len(wm), streamed=min(cap, len(wm)))
        # страховка — одразу після підключення, щойно мине grace: угоди проміжку без потоку не чекають хвилину (рев'ю 01.10)
        asyncio.get_running_loop().call_later(float(s.get("alerts_poll_grace_s", 15)) + 1, app["alerts_poll_wake"].set)
        next_check, window_at = time.monotonic() + every, time.monotonic()
        while True:
            try:
                msg = await ws.receive(timeout=5)
            except asyncio.TimeoutError:
                msg = None
            if msg is not None:
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                    raise RuntimeError("the stream closed")
                if msg.type == aiohttp.WSMsgType.TEXT:
                    d = json.loads(msg.data)
                    if isinstance(d.get("id"), int) and d["id"] in pending:    # відповідь на підписку чи відписку
                        w, kind = pending.pop(d["id"])
                        asked_at.pop(d["id"], None)
                        if kind == "sub" and isinstance(d.get("result"), int):
                            sub_of[w], wallet_of[d["result"]] = d["result"], w
                            if w not in app["alerts_wm"]:                     # поки чекали відповіді, гаманець прибрали
                                await unsubscribe(w)
                        elif d.get("error"):
                            log.warning("alerts: %s refused: %s", "subscription" if kind == "sub" else "unsubscribe", str(d.get("error"))[:100])
                    elif d.get("method") == "logsNotification":
                        p = d.get("params") or {}
                        w, v = wallet_of.get(p.get("subscription")), (p.get("result") or {}).get("value") or {}
                        if w and v.get("signature") and not v.get("err"):
                            delivered += 1
                            # гаманець-бот (десятки угод на хвилину) не забирає ноду в усіх: понад alerts_wallet_per_min
                            # за хвилину — пропуск з рядком у журналі (KOLS-радар так само тримає потоки лише тихих гаманців).
                            # Пропущене позначаємо обробленим: інакше страховка надіслала б його із запізненням (рев'ю 01.10)
                            minute, fl, limit = int(time.time() // 60), app["alerts_flood"], int(s.get("alerts_wallet_per_min", 30))
                            rec = fl.get(w)
                            rec = fl[w] = [minute, 1] if not rec or rec[0] != minute else [minute, rec[1] + 1]
                            if len(fl) > 5000:
                                fl.clear()
                            if rec[1] <= limit:
                                asyncio.get_running_loop().create_task(_alert_tx_safe(app, http, w, v["signature"]))
                            else:
                                app["alerts_seen"][v["signature"] + ":" + w] = time.time()
                                if rec[1] == limit + 1:
                                    _alert_fail(app, "system", "flood")
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + every
                snap = app["activity"].snapshot()          # лічильники угод і закладки — на диск разом з перевіркою списку
                if snap is not None:
                    try:
                        await asyncio.to_thread(app["activity"].write, snap)
                    except OSError as e:
                        log.warning("activity save: %s", e)
                now_map = await asyncio.to_thread(_watch_now, app)
                for rid in [rid for rid, at in asked_at.items() if time.monotonic() - at > 10]:   # нода не відповіла: знову
                    pending.pop(rid, None)
                    asked_at.pop(rid, None)
                asked = {w for w, k in pending.values() if k == "sub"}
                for w in set(sub_of) - set(now_map):
                    await unsubscribe(w)
                room = cap - len(sub_of) - len(asked)
                for w in sorted(set(now_map) - set(sub_of) - asked)[:max(0, room)]:
                    await subscribe(w)
                app["alerts_wm"] = now_map
                app["activity"].watch(set(now_map))
                app["alerts_state"].update(wallets=len(now_map), streamed=min(cap, len(now_map)))
                if not now_map:
                    return
                if not primary and time.monotonic() - began > float(s.get("alerts_fallback_min", 10)) * 60:
                    return                                # на запасній досить: пробуємо основну
                # лише угоди, що сталися при цьому з'єднанні (те, що страховка добрала за час без нього, — не вина потоку),
                # і за останні 5 хвилин, а не за все життя з'єднання: потік, що замовк після години роботи, теж видно
                if time.monotonic() - window_at > 300:
                    caught = app["alerts_state"].get("poll_caught_live", 0) - live0
                    if caught >= 3 and caught > delivered:
                        raise RuntimeError(f"the stream misses trades: {caught} caught by the poll, {delivered} delivered in 5 minutes")
                    window_at, delivered, live0 = time.monotonic(), 0, app["alerts_state"].get("poll_caught_live", 0)
    finally:
        await ws.close()


async def _alerts_loop(app):
    """Потік транзакцій гаманців зі списків з дзвіночком. Основна нода — перша в alerts_ws_urls (api.mainnet-beta:
    ≈2 с від блоку до повідомлення проти ≈10 с у publicnode, замір 01.10); обрив — наступна з паузою, що зростає, і з
    запасної за alerts_fallback_min повертаємось на основну. Страховка — окремою задачею (_alerts_poll_loop)."""
    urls = list(app["s"].get("alerts_ws_urls") or ["wss://api.mainnet-beta.solana.com"])
    i, delay, began = 0, 5, time.monotonic()
    async with aiohttp.ClientSession(headers=UA_HEADERS) as http:
        while True:
            try:
                began = time.monotonic()
                wm = await asyncio.to_thread(_watch_now, app)
                if not wm:
                    app["alerts_state"].update(connected=False, wallets=0, streamed=0)
                    app["alerts_wm"] = {}
                    app["activity"].watch(set())              # ні за ким не стежимо: рахунок почнеться заново
                    await asyncio.sleep(30)
                    continue
                app["alerts_wm"] = wm                         # страховка бачить, за ким стежити, навіть поки потоку нема
                began = time.monotonic()
                await _alerts_watch_once(app, http, urls[i % len(urls)], wm, primary=i % len(urls) == 0)
                i, delay = 0, 5
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                if time.monotonic() - began > 60:
                    delay = 5                                     # жило хвилину й більше: це обрив, а не нода, що не відповідає
                app["alerts_state"].update(connected=False)
                app["alerts_state"]["errors"] += 1
                log.warning("alerts stream %s: %s", urls[i % len(urls)].split("//")[-1], e)
                i += 1
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)


async def auth_nonce(request):
    """Одноразовий код і поля, з яких браузер збирає текст для підпису. Видача теж під стелею з однієї мережі: сховище
    кодів скінченне, і потік запитів інакше витісняв би коди людей, які саме підтверджують вхід у гаманці."""
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    now, ip = time.time(), _ip_key(_client_ip(request))
    wait = request.app["auth_throttle"].wait_s(ip, now) or request.app["nonce_throttle"].wait_s(ip, now)
    if wait:
        return _jerr(_wait_text(wait), 429)
    request.app["nonce_throttle"].miss(ip, now)
    return web.json_response({"nonce": request.app["nonces"].issue(now), "domain": _expected_domain(request),
                              "issued_at": acct_mod.issued_at(now), "statement": acct_mod.STATEMENT},
                             headers={"Cache-Control": "no-store"})


SIGNIN_EXPIRED = "This sign-in request expired. Try again."


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
        return SIGNIN_EXPIRED
    iat = acct_mod.parse_issued_at(m["issued_at"])
    if iat is None or abs(now - iat) > 600:
        return SIGNIN_EXPIRED
    if not acct_mod.verify_signature(pubkey, message, signature):
        return "The signature does not match the wallet."
    return None


async def auth_verify(request):
    """Підпис справжній → кука акаунта на ACCT_DAYS; перший вхід створює акаунт."""
    app = request.app
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    ip, now, th = _ip_key(_client_ip(request)), time.time(), app["auth_throttle"]
    wait = th.wait_s(ip, now)
    if wait:
        return _jerr(_wait_text(wait), 429)
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    pubkey, sig, msg = str(body.get("pubkey") or ""), str(body.get("signature") or ""), str(body.get("message") or "")
    why = _signin_problem(app, request, pubkey, sig, msg, now)
    if why:
        if why != SIGNIN_EXPIRED:                               # прострочений код — не спроба вгадати: людина просто довго думала
            th.miss(ip, now)
        return _jerr(why, 401)
    th.hit(ip)
    if not app["accounts"].exists(pubkey) and pubkey not in app["admins"]:
        # новий гаманець нічого не коштує, тож без стелі скрипт створював би тисячі акаунтів з однієї адреси
        daily, s = app["auth_daily"], app["s"]
        if not daily.take("new:" + ip, int(s.get("new_accounts_per_ip_per_day", 5))) \
                or not daily.take("new:global", int(s.get("new_accounts_per_day", 300))):
            return _jerr("Too many new wallets from this network today. Sign in with one you already used, or come back tomorrow.", 429)
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
    pk = request.get("acct")
    if pk and request.app["usage_daily"].take("w:" + pk, int(request.app["s"].get("acct_writes_per_day", 500))):
        request.app["events"].add(pk, "signout")      # кука ще тут: хто саме вийшов (повтор тієї самої куки — під стелею змін)
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
    if added:                                                   # нічого нового — нічого в журнал (цикл повторів не роздуває місяць)
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
    """Списки спостереження: створити ({name}), перейменувати ({id, name}), прибрати ({id}) — за адресою; перенести чи
    скопіювати збережені гаманці в інший список ({wallets, to, from?}: з from — перенесення, без — копія)."""
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
        elif action == "move":
            ws = body.get("wallets")
            if not isinstance(ws, list) or not ws:
                return _jerr("Pick at least one wallet.")
            ws = [w for w in ws[: acct_mod.MAX_WALLETS] if acct_mod.valid_pubkey(w)]
            src = str(body["from"]) if body.get("from") else None
            out = {"wallets": acc.place_wallets(pk, ws, str(body.get("to") or ""), src), "moved": bool(src)}
        elif action == "alerts":                                # усі гаманці списку разом (до стелі); з 02.10 дзвіночок — на гаманці
            if not _alerts_allowed(request.app, pk):
                return _jerr("Alerts are in a closed test for now.", 403)
            on = bool(body.get("on"))
            cap = int(request.app["s"].get("alerts_max_wallets", 10))
            out = {"alerts": on, "changed": acc.set_list_alerts(pk, str(body.get("id") or ""), on, cap), "cap": cap}
            out["bells"] = [w for w, m in acc.load(pk)["wallets"].items() if m.get("alert")]   # the page shows every bell as it is now
        else:
            return _jerr("Unknown action.", 404)
    except acct_mod.AccountError as e:
        return _jerr(str(e))
    extra = ({"on": int(bool(out.get("alerts")))} if action == "alerts" else
             {"n": len(out["wallets"]), "how": "move" if out["moved"] else "copy"} if action == "move" else {})
    if action != "move" or out["wallets"]:                    # нічого не змінилось — нічого в журнал
        request.app["events"].add(pk, "list_" + action, **extra)
    return web.json_response(dict(out, ok=True, lists=acc.load(pk)["lists"]))


@_acct_route
async def me_wallet_alert(request, pk):
    """Дзвіночок на одному гаманці (власник, 02.10): {wallet, on} → {on, n, cap}. Понад стелю — 400 з поясненням,
    що спершу треба вимкнути інший."""
    app = request.app
    if not _alerts_allowed(app, pk):
        return _jerr("Alerts are in a closed test for now.", 403)
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    cap = int(app["s"].get("alerts_max_wallets", 10))
    try:
        on, n = app["accounts"].set_wallet_alert(pk, str(body.get("wallet") or ""), bool(body.get("on")), cap)
    except acct_mod.AccountError as e:
        return _jerr(str(e))
    app["events"].add(pk, "wallet_alert", on=int(on))
    return web.json_response({"ok": True, "on": on, "n": n, "cap": cap})


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
    n = _usage_take(app, pk, len(evs), _ip_key(_client_ip(request))) if evs else 0
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


JOB_DAY_RE = re.compile(r"_(\d{8})-(\d{4})_(\d{4})$")


def _pump_of(job_id):
    """«Sep 15, 19:30–19:50» з канонічного id аналізу (98kfF7_20260915-1930_1950): коли був памп, з якого гаманець.
    Час — UTC, як в id; інший вигляд id — нічого."""
    m = JOB_DAY_RE.search(job_id or "")
    if not m:
        return None
    try:
        d = datetime.datetime.strptime(m.group(1), "%Y%m%d")
    except ValueError:
        return None
    a, b = m.group(2), m.group(3)
    return {"day": f"{d:%b} {d.day}", "range": f"{d:%b} {d.day}, {a[:2]}:{a[2:]}–{b[:2]}:{b[2:]} UTC"}


def _account_view(app, pk):
    a = app["accounts"].load(pk)
    wallets = sorted((dict(v, wallet=w, pump=_pump_of(v.get("from_job"))) for w, v in a["wallets"].items()),
                     key=lambda v: v.get("added_ms") or 0, reverse=True)
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
    tg = a.get("telegram") or {}
    # угоди за 7 днів, які бачив потік сповіщень (власник, 01.10) — лише для гаманців, за якими він стежить зараз: інакше
    # «0 угод» означало б «не стежили», а не «не торгував» (рев'ю 01.10)
    # the draft site (dev) runs no bot, since Telegram gives a bot's updates to one listener only: there the alerts show as
    # a preview (owner, 04.10: «why are there no alerts?»), the bells and switches save and nothing is sent
    live = _alerts_live(request.app)
    preview = not live and _private_host(request)
    s, alerts_ok = request.app["s"], _alerts_allowed(request.app, pk) and (live or preview)
    cap = int(s.get("alerts_max_wallets", 10))
    watched = alerts_mod.watch_map([a], request.app["admins"], bool(s.get("alerts_open")), cap,
                                   s.get("alerts_min_usd")) if alerts_ok else {}
    # дзвіночки на гаманцях і скільки алертів уже пішло сьогодні: лічильник угорі і рядок у картці (власник, 02.10)
    alert_n = sum(1 for w in wallets if w.get("alert"))
    day_cap, dc = int(s.get("alerts_per_day", 200)), request.app["alerts_day"]
    act = request.app["activity"].of(watched)
    wmeta = {w["wallet"]: dict({k: w.get(k) for k in ("my_tags", "lists", "added_ms")}, act=act.get(w["wallet"]), alert=bool(w.get("alert")),
                               sent_today=dc.count("s:" + pk + ":" + w["wallet"]) or None) for w in wallets}   # what the card shows, by wallet
    return render("me.html", request, wallets=wallets, analyses=analyses, max_my_tags=acct_mod.MAX_MY_TAGS, wmeta=wmeta, act=act,
                  demo_mint=(demo or {}).get("mint"), lists=lists, max_lists=acct_mod.MAX_LISTS,
                  alerts_ok=alerts_ok, alerts_preview=preview,   # без бота картка не обіцяє того, чого нема
                  after_on=_after_on(request),
                  alert_n=alert_n, watch_cap=cap, day_cap=day_cap, day_used=dc.count("a:" + pk),
                  tg={"linked": bool(tg.get("chat")), "user": tg.get("user") or ""},
                  prefs=alerts_mod.prefs_of(a.get("alerts"), request.app["s"].get("alerts_min_usd")))


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
            daily, who, net = app["browse_daily"], "age:acct:" + pk, "age:net:" + _ip_key(_client_ip(request))
            mine = daily.left(who, s.get("age_card_per_day", 50)) <= 0 or daily.left(net, s.get("age_card_per_day", 50)) <= 0   # і мережа: гаманці безкоштовні
            if mine or daily.left("age:global", s.get("age_card_global_per_day", 500)) <= 0:
                _limit(app, pk, "age-card", "wallet" if mine else "site")
                return known(checked=False, capped=True)
        settle = _browse_budget(request, 1)
        if who:
            daily.add(who, 1)
            daily.add(net, 1)
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
        return None, None, _jerr("Only the owner's wallet can do this.", 403)
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


def _admin_gate(request):
    """Сторінки власника: без ADMIN_WALLETS їх не існує (404), чужому гаманцю — відмова (403). None — можна."""
    app = request.app
    if not app["admins"]:
        raise web.HTTPNotFound(text="Not configured.")
    pk = request.get("acct")
    if not pk or pk not in app["admins"]:
        return render("error.html", request, message="This page is for the owner's wallet. Connect it first.", status=403)
    return None


def _team(app):
    """Хто не рахується в поведінці: гаманці власника і ті, що він позначив тестовими."""
    return set(app["admins"]) | usage_mod.load_exclude(app["usage_dir"] / "exclude.json")


def _beta(app):
    """Бета-тестери, яких власник веде в /admin: без денних лімітів на аналізи (стеля прогону і резерв місяця лишаються).
    Файл, а не .env: список міняється без деплою і не лежить у публічному репозиторії."""
    return usage_mod.load_wallet_set(app["usage_dir"] / "beta.json")


USAGE_TTL = 60
ADMIN_TABS = {"overview": "Overview", "analyses": "Analyses", "agent": "Agent", "wallets": "Wallets", "behavior": "Behavior",
              "costs": "Costs", "api": "API", "feedback": "Feedback", "log": "Log", "method": "Agent method"}


async def _budget(app):
    s, ages = app["s"], app.get("ages")
    left = await _credits_left(app)
    gcap = int(s.get("runs_global_per_day", 10))
    return {"credits_left": left, "credits_at": int(app["credits"]["at"] * 1000) or None,
            "credits_month": int(s.get("credits_month", 0) or 0), "reserve": _credits_reserve(s),
            "renew_day": int(s.get("credits_renew_day") or 0), "ai": await _ai_balance(app),
            "runs_today": gcap - app["runs_daily"].left("global", gcap),
            "rpc": ages.budget.state() if ages is not None and getattr(ages, "budget", None) else None,
            "insightx": app["labels"].budget.state() if app.get("labels") is not None and app["labels"].budget else None}


async def _usage_summary(app, period, include_team, budget):
    """Дашборд з журналу, раз на хвилину: читається і рахується в потоці, не на циклі подій."""
    key = (period, include_team)
    hit = app["usage_cache"].get(key)
    if hit and time.time() - hit[0] < USAGE_TTL:
        return hit[1]
    tz, now = usage_mod.zone(app["s"].get("usage_tz")), int(time.time() * 1000)
    jobs = [j for j in list(app["jobs"].jobs.values()) if not j.replay]   # знімок словника тут: робочі потоки його міняють

    def work():
        return usage_mod.summarize(app["events"].read(usage_mod.load_since(now, period, tz)), accounts=app["accounts"].all(),
                                   jobs=jobs, onchain=usage_mod.load_json(app["usage_dir"] / "onchain.json", {}), now_ms=now,
                                   period=period, tz=tz, team=_team(app), include_team=include_team, budgets=budget)
    out = await asyncio.to_thread(work)
    app["usage_cache"][key] = (time.time(), out)
    return out


async def admin_page(request):
    """Дашборд власника: хто з підключених гаманців що робить і скільки кредитів це коштує; методика агента."""
    app = request.app
    refused = _admin_gate(request)
    if refused:
        return refused
    period = request.query.get("p") if request.query.get("p") in usage_mod.PERIODS else "7d"
    include_team = request.query.get("team") == "1"
    tab = request.query.get("tab") if request.query.get("tab") in ADMIN_TABS else "overview"
    budget = await _budget(app)
    u = await _usage_summary(app, period, include_team, budget)
    events = [dict(e, **usage_mod.label(e)) for e in app["events"].tail(100)] if tab == "log" else []
    feedback = [dict(f, page_ok=bool(SITE_PATH.fullmatch(str(f.get("page") or "")))) for f in app["feedback"].recent(200)]
    store = app["agent_store"]
    meters = usage_mod.credit_meters(budget, now_ms=int(time.time() * 1000))
    api_keys, api_stats = [], {"keys": {}, "recent": []}
    if tab == "api":                                     # ключі партнерів і що кожен робить за цей місяць
        now_ms = int(time.time() * 1000)
        month = await asyncio.to_thread(app["events"].read, usage_mod.month_start_ms(now_ms))
        api_keys, api_stats = app["api_keys"].all(), usage_mod.api_usage(month, now_ms)
    return render("admin.html", request, u=u, budget=budget, meters=meters, beta=sorted(_beta(app)), events=events, period=period,
                  labels=_admin_labels(app) if tab == "wallets" else {},
                  api_keys=api_keys, api_stats=api_stats, api_rules=api_mod.THRESHOLD_RULES,
                  include_team=include_team, tab=tab, tabs=ADMIN_TABS,
                  feedback=feedback, feedback_new=sum(1 for f in feedback if not f.get("read")),
                  usage_tz=app["s"].get("usage_tz") or "UTC", periods=list(usage_mod.PERIODS),
                  st_eur_million=float(app["s"].get("st_eur_per_million") or 0),
                  agent_cfg=store.config(), agent_history=store.history(10), agent_log=store.recent(50),
                  agent_on=app.get("agent") is not None, agent_model=getattr(app.get("assistant"), "model", ""),
                  excludable=agent_mod.EXCLUDABLE, default_method=agent_mod.DEFAULT_METHOD)


async def admin_wallet_page(request):
    """Один гаманець для власника: хто він, що робив день за днем, його аналізи з кредитами, питання агенту."""
    app = request.app
    refused = _admin_gate(request)
    if refused:
        return refused
    pk = request.match_info["pk"]
    if not acct_mod.valid_pubkey(pk):
        raise web.HTTPNotFound(text="That is not a wallet address.")
    tz, now = usage_mod.zone(app["s"].get("usage_tz")), int(time.time() * 1000)
    jobs = [j for j in list(app["jobs"].jobs.values()) if not j.replay and j.owner == pk]
    team = _team(app)

    def work():
        return usage_mod.wallet_detail(app["events"].read(), pk, account=app["accounts"].load(pk), jobs=jobs,
                                       onchain=usage_mod.load_json(app["usage_dir"] / "onchain.json", {}),
                                       agent_log=app["agent_store"].recent(2000), now_ms=now, tz=tz, team=team)
    d = await asyncio.to_thread(work)
    return render("admin_wallet.html", request, d=d, excluded=pk in team and pk not in app["admins"], is_admin=pk in app["admins"], now=now,
                  labels=_admin_labels(app).get(pk, []),
                  beta_on=pk in _beta(app))


async def admin_usage_exclude(request):
    """Позначити гаманець тестовим (або зняти позначку): його дії більше не рахуються як поведінка користувачів."""
    app = request.app
    pk, body, err = await _admin_json(request)
    if err:
        return err
    wallet = str(body.get("wallet") or "")
    if not acct_mod.valid_pubkey(wallet):
        return _jerr("That is not a wallet address.")
    path = app["usage_dir"] / "exclude.json"
    ex = usage_mod.load_exclude(path)
    ex = ex | {wallet} if body.get("on") else ex - {wallet}
    usage_mod.save_exclude(path, ex)
    app["usage_cache"].clear()
    return web.json_response({"ok": True, "excluded": wallet in ex})


async def admin_feedback(request):
    """Лист у скриньці власника: прочитано, знову нове, видалити назовсім."""
    app = request.app
    pk, body, err = await _admin_json(request)
    if err:
        return err
    fid, action, store = str(body.get("id") or ""), body.get("action"), app["feedback"]
    if action in ("read", "unread"):
        ok = await asyncio.to_thread(store.mark, fid, action == "read")
    elif action == "delete":
        ok = await asyncio.to_thread(store.delete, fid)
    else:
        return _jerr("Unknown action.")
    if not ok:
        return _jerr("No such message.", 404)
    return web.json_response({"ok": True})


async def admin_api(request):
    """Ключі партнерського API: створити, перевипустити, увімкнути чи вимкнути, денна межа, пороги, видалити. Сам ключ
    повертається лише при створенні й перевипуску: його одразу передати партнеру, на сервері лишається відбиток."""
    app = request.app
    pk, body, err = await _admin_json(request)
    if err:
        return err
    store, action, kid = app["api_keys"], body.get("action"), str(body.get("id") or "")
    if action == "create":
        kid, key = store.create(body.get("name"))
        return web.json_response({"ok": True, "id": kid, "key": key})
    if action == "rotate":
        key = store.rotate(kid)
        return web.json_response({"ok": True, "key": key}) if key else _jerr("No such key.", 404)
    if action == "enable":
        ok = store.update(kid, enabled=bool(body.get("on")))
    elif action == "limit":
        try:
            cap = int(body.get("daily_cap"))
        except (TypeError, ValueError):
            return _jerr("The limit must be a whole number.")
        if not 1 <= cap <= 100_000:
            return _jerr("The limit must be between 1 and 100,000 checks a day.")
        ok = store.update(kid, daily_cap=cap)
    elif action == "thresholds":
        th = {}
        for rule in api_mod.THRESHOLD_RULES:
            try:
                v = float(body.get(rule))
            except (TypeError, ValueError):
                return _jerr(f"The {rule} threshold must be a number.")
            if not 0 <= v <= 100 or v != v:
                return _jerr("Thresholds are shares of the supply, from 0 to 100.")
            th[rule] = v
        ok = store.update(kid, thresholds=th)
    elif action == "ips":
        ips = api_mod.parse_ips(body.get("ips"))
        if ips is None:
            return _jerr("Addresses must be IPv4 or IPv6, or networks like 10.0.0.0/24, separated by commas.")
        ok = store.update(kid, ips=ips)
    elif action == "delete":
        ok = store.delete(kid)
    else:
        return _jerr("Unknown action.")
    return web.json_response({"ok": True}) if ok else _jerr("No such key.", 404)


API_CACHE_S = 60


def _api_key(request):
    """Ключ партнера із заголовка: `Authorization: Bearer <key>` або `X-API-Key`. У рядку запиту не приймаємо: він
    осідає в журналах проксі й в історії браузера."""
    auth = request.headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return (request.headers.get("X-API-Key") or "").strip()


async def api_check(request):
    """Перевірка токена для партнера: рівні правил і чи пройшла монета пороги ключа — без сирих цифр і без оцінок
    (partner_api). Хвилину відповідь для тієї самої монети береться з пам'яті: швидше і нічого не коштує."""
    app, s = request.app, request.app["s"]
    ip, now = _client_ip(request), time.time()
    bad = app["api_bad"]
    if bad.wait_s(_ip_key(ip), now):                    # перебір ключів з однієї мережі: хвилину нічого не приймаємо
        return _jerr("Too many requests with a wrong key. Try again in a minute.", 429)
    rec = app["api_keys"].find(_api_key(request))
    if not rec:
        bad.miss(_ip_key(ip), now)
        return _jerr("Unknown or missing API key. Send it as: Authorization: Bearer <key>.", 401)
    if not rec.get("enabled"):
        return _jerr("This API key is switched off.", 403)
    if rec.get("ips") and not api_mod.ip_allowed(ip, rec["ips"]):   # ключ прив'язано до серверів партнера
        return _jerr("This key does not work from this address.", 403)
    who = "api:" + rec["id"]
    th = app["api_throttle"]
    if th.wait_s(who, now):
        return _jerr("Too many requests. Keep it under 5 a second.", 429)
    th.miss(who, now)
    mint = (request.query.get("mint") or "").strip()
    if not MINT_RE.match(mint):
        return _jerr("Pass a Solana token address as ?mint=.")
    if not app["usage_daily"].take(who, int(rec.get("daily_cap") or api_mod.DEFAULT_DAILY_CAP)):
        return _jerr("Today's limit for this key is used up. It resets at 00:00 UTC.", 429)
    cache, hit = app["api_cache"], app["api_cache"].get(mint)
    cached = bool(hit and now - hit[0] < int(s.get("api_cache_s", API_CACHE_S)))
    if cached:
        report = hit[1]
    else:
        reserve = _credits_reserve(s)
        left = await _credits_left(app) if reserve else None
        if left is not None and left < reserve:
            return _jerr("Checks are paused on our side. Try again later.", 503)   # про наш бюджет партнеру знати не треба
        st = app["st"]

        def work():
            with st.meter():
                req0 = st.requests_here()
                try:
                    return st.token_report(mint), None
                except urllib.error.HTTPError as e:
                    return None, e.code
                except Exception:  # noqa: BLE001 — будь-яка інша відмова джерела: партнеру 502, не 500
                    return None, 502
                finally:
                    _spend(app, who, "api-check", st=st.requests_here() - req0, mint=mint)
        report, err = await asyncio.to_thread(work)
        if report is None:
            return _jerr("No such token in the data source.", 404) if err in (400, 404) else \
                _jerr("The data source did not answer. Try again in a few seconds.", 502)
        if len(cache) > 5000:
            cache.clear()
        cache[mint] = (now, report)
    out = api_mod.evaluate(report, rec.get("thresholds") or api_mod.DEFAULT_THRESHOLDS, now)
    app["events"].add(who, "api", mint=mint, passes=int(out["passes"]), cached=1 if cached else None,
                      failed=",".join(out["failed"]) or None)
    return web.json_response(dict({"mint": mint, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                                   "cached": cached}, **out))


async def admin_beta(request):
    """Додати бета-тестера чи прибрати: його аналізи не впираються в денні ліміти. Список — файл, діє одразу, без деплою."""
    app = request.app
    pk, body, err = await _admin_json(request)
    if err:
        return err
    wallet = str(body.get("wallet") or "").strip()
    if not acct_mod.valid_pubkey(wallet):
        return _jerr("That is not a wallet address.")
    path = app["usage_dir"] / "beta.json"
    beta = usage_mod.load_wallet_set(path)
    beta = beta | {wallet} if body.get("on") else beta - {wallet}
    usage_mod.save_wallet_set(path, beta)
    return web.json_response({"ok": True, "beta": wallet in beta, "wallets": sorted(beta)})


ADMIN_LABELS_MAX, ADMIN_LABEL_LEN = 6, 24


def _admin_labels(app):
    """Мітки власника на гаманцях користувачів («я», «знайомий», «тестер»…): {гаманець: [мітки]}. Бачить лише адмінка."""
    d = usage_mod.load_json(app["usage_dir"] / "labels.json", {})
    return {w: [str(x) for x in v] for w, v in (d or {}).items() if isinstance(v, list) and acct_mod.valid_pubkey(w)}


async def admin_labels(request):
    """Мітки гаманця в адмінці (власник, 30.09: «хто мій знайомий, де мої акаунти, де тестувальники»). Цілий список за раз:
    до шести слів по 24 знаки, без дублів; порожній — прибрати. Файл, діє одразу."""
    app = request.app
    pk, body, err = await _admin_json(request)
    if err:
        return err
    wallet = str(body.get("wallet") or "").strip()
    if not acct_mod.valid_pubkey(wallet):
        return _jerr("That is not a wallet address.")
    raw = body.get("labels") if isinstance(body.get("labels"), list) else []
    clean = []
    for x in raw:
        v = " ".join(str(x).split())[:ADMIN_LABEL_LEN].lower()
        if v and v not in clean:
            clean.append(v)
    clean = clean[:ADMIN_LABELS_MAX]
    labels = _admin_labels(app)
    if clean:
        labels[wallet] = clean
    else:
        labels.pop(wallet, None)
    usage_mod.save_json(app["usage_dir"] / "labels.json", labels)
    return web.json_response({"ok": True, "wallet": wallet, "labels": clean})


# експорт списків — про сам гаманець (кастдев 01.10): хто це, звідки перші SOL, скільки йому; цифри токена, з аналізу якого
# його зберегли, лишаються в тому аналізі. Де знайшли — останні три колонки
ME_COLUMNS = ["wallet", "name", "x_handle", "funder", "funder_exchange", "wallet_first_tx_utc", "my_tags", "lists", "added_utc",
              "symbol", "mint", "from_job"]


def _x_handle(idn):
    """Як EarlyTags.handle на сторінці: лише літери, цифри й підкреслення."""
    return re.sub(r"[^A-Za-z0-9_]", "", re.sub(r"^@", "", str((idn or {}).get("twitter") or "")))


def _display_name(idn):
    """Як EarlyTags.displayName: відомий трейдер — під іменем, решта — під X-ніком, яким їх кличуть застосунки."""
    if not idn:
        return ""
    h = _x_handle(idn)
    if idn.get("type") == "kol" or "kol" in (idn.get("tags") or []):
        return idn.get("name") or h
    return h or idn.get("name") or ""


def _wallet_who(app, w, from_job):
    """Ім'я, X, спонсор, біржа і перша транзакція гаманця — з уже збереженого результату, жодного запиту назовні."""
    job = app["jobs"].get(from_job or "")
    r = job.result if job is not None and job.status == "done" and job.result else {}
    idn, fnd, age = (r.get("identities") or {}).get(w), (r.get("funders") or {}).get(w), (r.get("ages") or {}).get(w) or {}
    h = _x_handle(idn)
    return {"name": _display_name(idn), "x_handle": h, "funder": fnd or "",   # без @: таблиці читають @ як формулу
            "funder_exchange": exch_mod.name_of(fnd) or "" if fnd else "",
            "wallet_first_tx_utc": chart.fmt_dt(age["ms"], year=True, utc=True) if age.get("exact") and age.get("ms") else ""}


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
        w.writerow({**{k: cell(r.get(k)) for k in ME_COLUMNS}, **{k: cell(v) for k, v in _wallet_who(request.app, r["wallet"], r.get("from_job")).items()},
                    "my_tags": cell("|".join(r.get("my_tags") or [])),
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
    # аналітика вмикається лише там, де задано id, і ніколи на сторінках власника: там показується новий ключ API,
    # а сторонній скрипт на сторінці бачить усе, що на ній є
    admin_page = request is not None and request.path.startswith("/admin")
    ctx.setdefault("umami_id", "" if admin_page else os.getenv("UMAMI_WEBSITE_ID", ""))
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
            raise WebError("No data came back for this token. Check the address or try again later.")
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

def _home_totals(app, now=None):
    """Лічильники головної — за всіма аналізами, а не за 60 останніми, як було (власник, 05.10: «wallets on the
    record» падав з 19 433 до 11 518, коли десятки малих свіжих аналізів витіснили старі великі зі списку). І рахунок
    лише росте: найбільше значення лежить у файлі поруч з аналізами, тож видалений аналіз чи перезапуск його не
    зменшить. Демо-програвання не рахуються: вони повторюють той самий аналіз. Перерахунок — раз на хвилину."""
    now = time.time() if now is None else now
    cache = app["home_totals"]
    if cache.get("at") and now - cache["at"] < 60:
        return cache["totals"]
    done = [j for j in list(app["jobs"].jobs.values()) if j.status == "done" and j.result and not j.replay]
    cur = {"wallets": sum(int((j.result.get("counts") or {}).get("n_early") or 0) for j in done),
           "tokens": len({j.mint for j in done}),
           "trades": sum(int((j.result.get("counts") or {}).get("n_trades") or 0) for j in done)}
    path = Path(app["jobs"].dir) / "home_totals.json"
    try:
        best = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        best = {}
    totals = {k: max(int(best.get(k) or 0), v) for k, v in cur.items()}
    if totals != {k: best.get(k) for k in totals}:
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(totals), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            log.warning("could not keep the home totals in %s", path)
    cache.update(at=now, totals=totals)
    return totals


def _home_data(jobs):
    """The sample job and background lines for the home page — from stored results only."""
    done = [j for j in jobs if j.status == "done" and j.result]
    sample = next((j for j in done if j.result.get("mode") == "trades" and j.result.get("rows")), None) \
        or next((j for j in done if j.result.get("rows")), None)
    lines = []
    if sample:
        for r in (sample.result.get("rows") or [])[:16]:
            if r.get("first_buy_ms") and r.get("invested_in_range_usd"):
                lines.append(f"{r['wallet'][:4]}…{r['wallet'][-4:]}  buy  {_usd(r['invested_in_range_usd'])}  @ "
                             f"{chart.fmt_mcap(r.get('entry_mcap_avg'))}  {chart.fmt_dt(r['first_buy_ms'])}")
    return sample, lines


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
    sample, lines = _home_data(jobs)
    totals = _home_totals(app)
    want = (demo_mod.read_override(str(Path(app["jobs"].dir).parent / "demo")).get("example_job")
            or app["s"].get("example_job") or "")
    example = app["jobs"].get(want) if want else None
    if not example or example.status != "done":
        done = [j for j in jobs if j.status == "done" and j.result and j.result.get("rows")]
        example = min(done, key=lambda j: j.created_ms or 0) if done else None      # найстарший готовий = показовий
    my_n = len(app["accounts"].load(request["acct"])["analyses"]) if request.get("acct") else 0
    _view(request, "home")
    f, s = app["fresh"], app["s"]
    if s.get("fresh_on") and f["live"] and not f["busy"] and time.time() * 1000 - f["at"] > float(s.get("fresh_refresh_min", 10)) * 60_000:
        asyncio.get_running_loop().create_task(_fresh_refresh(app))    # сторінка не чекає: покаже нове наступному
    now_ms = int(time.time() * 1000)
    fresh = []
    if s.get("fresh_on") and f["ok_at"] and now_ms - f["ok_at"] < float(s.get("fresh_stale_hours", 3)) * 3_600_000:
        # вік рахується зараз, а не в момент оновлення; список, старший за кілька годин, не показується зовсім (рев'ю 30.09)
        fresh = [dict(r, age_h=max(0.0, (now_ms - r["created_ms"]) / 3_600_000) if r.get("created_ms") else None) for r in f["rows"]]
    return render("index.html", request, tokens=_by_token(jobs, example.id if example else None),
                  totals=totals, sample=sample, bg_lines=lines, my_n=my_n,
                  fresh=fresh, fresh_min=int((now_ms - f["ok_at"]) / 60_000) if f["ok_at"] else None)


async def docs_page(request):
    """Документація: markdown з docs/ поруч із кодом, той самий деплой, те саме оформлення сайту."""
    slug = request.match_info.get("slug") or "index"
    body, title = docs_mod.page(DOCS_DIR, slug, {"s": request.app["s"], "TAGS": tags.DEFS, "EXCH_N": len(exch_mod.KNOWN), "assistant_on": request.app.get("assistant") is not None,
                                                 "API": api_mod})   # межі правил API — з коду, щоб сторінка не розійшлась із тим, що рахує сервер
    if body is None:
        raise web.HTTPNotFound(text="There is no such page in the documentation.")
    prev, nxt = docs_mod.around(DOCS_DIR, slug)
    _view(request, "docs", slug)
    return render("docs.html", request, body=body, title=title, nav=docs_mod.nav(DOCS_DIR, slug), prev=prev, nxt=nxt, slug=slug)


FORM_MIN_S, FORM_MAX_S = 2, 6 * 3600          # швидше — не людина; довше — сторінку відкрили вчора
SITE_PATH = re.compile(r"/(?![/\\])[^\s\\]*")   # сторінка цього сайту: «//evil.com» і «/\evil.com» браузер відкриває як чужий сайт


def _form_token(now=None):
    """Коли відкрили форму, з підписом сервера: бот, що шле запит без сторінки, такої мітки не має."""
    ts = str(int(time.time() if now is None else now))
    return ts + "." + hmac.new(_acct_secret().encode(), b"feedback:" + ts.encode(), hashlib.sha256).hexdigest()[:20]


def _form_age(token, now=None):
    """Скільки секунд тому відкрили форму; None — мітки нема або підпис не наш."""
    ts, _, sig = str(token or "").partition(".")
    if not (ts.isascii() and ts.isdigit() and len(ts) <= 12 and sig.isascii()) or not sig \
            or not hmac.compare_digest(sig, _form_token(int(ts)).partition(".")[2]):   # «²» чи тисяча цифр — не 500, а чужа мітка
        return None
    return (time.time() if now is None else now) - int(ts)


async def feedback_page(request):
    """«Contact»: помилка, ідея, питання. Відкрито всім; зі сторінки помилки — одразу «Bug»."""
    kind = request.query.get("kind") if request.query.get("kind") in FEEDBACK_KINDS else "idea"
    _view(request, "feedback")
    return render("feedback.html", request, kind=kind, kinds=FEEDBACK_KINDS, max_text=FEEDBACK_TEXT, max_contact=FEEDBACK_CONTACT,
                  form_token=_form_token())


async def feedback_post(request):
    """Лист власнику: у output/early/feedback/feedback.jsonl і на вкладку Feedback дашборда. Від спаму, по черзі:
    поле-пастка, яке людина не бачить; мітка часу форми з підписом (без сторінки чи швидше за 2 с — не людина); не
    більше двох посилань; той самий текст за добу вдруге не пишеться; п'ять спроб на годину з однієї мережі (IPv6 — /64,
    відкинуті теж рахуються); спільна стеля на добу. Ботові на тихих відмовах — «дякуємо», щоб не підбирав обхід."""
    app = request.app
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    ip, now = _ip_key(_client_ip(request)), time.time()
    throttle = app["feedback_throttle"]
    wait = throttle.wait_s(ip, now)
    if wait:
        return _jerr(_wait_text(wait), 429)
    body = await _json_body(request, limit=8192)
    if body is None:
        return _jerr("Bad request body.")
    age = _form_age(body.get("t"), now)
    if body.get("website") or age is None or age < FORM_MIN_S:  # пастка, чужа мітка чи надто швидко: «дякуємо», і нічого не пишемо
        throttle.miss(ip, now)
        return web.json_response({"ok": True})
    if age > FORM_MAX_S:
        return _jerr("This page has been open for hours. Reload it and send again.")
    text = str(body.get("text") or "").strip()
    if len(text) < 3:
        return _jerr("Write a few words first.")
    if len(text) > FEEDBACK_TEXT:
        return _jerr(f"Keep it under {FEEDBACK_TEXT:,} characters.")
    contact = str(body.get("contact") or "").strip()[:FEEDBACK_CONTACT]
    if feedback_links(text) > 2 or feedback_links(contact) > 1:
        throttle.miss(ip, now)
        return _jerr("Keep it to two links at most.")
    if await asyncio.to_thread(app["feedback"].seen, text, int(now * 1000)):
        throttle.miss(ip, now)                                  # той самий текст уже в скриньці: удруге не пишемо
        return web.json_response({"ok": True})
    pk = request.get("acct")
    # guests and connected wallets each have their own day: a flood of guest spam must not close the form for users
    bucket, cap = ("feedback:wallet", "feedback_per_day_wallet") if pk else ("feedback:guest", "feedback_per_day_guest")
    if not app["usage_daily"].take(bucket, int(app["s"].get(cap, 100))):
        return _jerr("Too many messages today. Try again tomorrow or reach us on X.", 429)
    throttle.miss(ip, now)
    page = str(body.get("page") or "")
    kind = body.get("kind") if body.get("kind") in FEEDBACK_KINDS else "other"
    app["feedback"].add({"ts_ms": int(now * 1000), "kind": kind, "text": text, "contact": contact,
                         "page": page[:FEEDBACK_PAGE] if SITE_PATH.fullmatch(page) else "", "pk": pk, "dev": _device(request)})
    if pk:
        app["events"].add(pk, "feedback", kind=kind)
    return web.json_response({"ok": True})


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
    if demo and demo["mint"] == mint:                                   # демо-токен: усе зі знімка, 0 запитів
        info = demo["info"]
        rows = [{"n": i + 1, "label": r.get("label") or f"Demo range {i + 1}", "job": r.get("job"),
                 "from": chart.to_input(r["from"]), "to": chart.to_input(r["to"])}
                for i, r in enumerate(demo["ranges"])]
    else:
        # огляд ≈2 запити, кеш — 0; підказок детектора сторінка більше не показує (30.09), свічки він кладе в кеш графіка
        info, _ = await _overview(app, mint, _browse_budget(request, 2) if not _overview_cached(app, mint) else None, pk)
        rows = []                                                       # голий графік: діапазони ставить людина
    q = request.query
    preset = None
    admin = bool(pk) and pk in app["admins"]
    beta = bool(pk) and not admin and pk in _beta(app)
    runs_left, runs_why = _runs_left(app, pk, _device_id(request), _client_ip(request)) if pk and not admin and not beta else (None, None)
    notice = q.get("notice") if q.get("notice") in ("limit", "netcap", "sitecap", "newwallet") else None   # Analyze bounced off a daily cap
    if notice in ("limit", "netcap", "newwallet") and not runs_left == 0:
        notice = None                                   # стара адреса, чуже посилання чи гість: вікно лише тому, кому справді нема
    # яке вікно показати: людина вичерпала свої, новий гаманець — свій один, мережа — спільні, чи сайт — день
    limit_kind = notice or (({"network": "netcap", "newwallet": "newwallet"}.get(runs_why, "limit")) if runs_left == 0 else None)
    runs_cap = _person_cap(app, pk) if pk else None
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
    src = request.query.get("src")
    src = src if src in ("alert", "fresh") else None               # звідки прийшли: алерт у Telegram чи стрічка пампів
    _view(request, "token", mint, demo=1 if demo and demo["mint"] == mint else None, src=src)
    if src and not request.get("acct"):
        # гість: лише звідки, без адреси. Раз на мережу, токен і джерело за 6 годин і під стелею мережі: інакше цикл
        # запитів накручував би «повернулись з алертів» і з'їдав би спільну гостьову стелю (рев'ю 01.10)
        net, now_ms, last = _ip_key(_client_ip(request)), int(time.time() * 1000), request.app["view_last"]
        gkey = ("guest", net, mint, src)
        if now_ms - last.get(gkey, 0) > 6 * 3600_000 and _usage_take(request.app, "guest", 1, net=net):
            if len(last) > 10_000:
                last.clear()
            last[gkey] = now_ms
            request.app["events"].add("guest", "view", page="token", ref=mint, src=src, dev=_device(request))
    return render("token.html", request, info=info, mint=mint, s=s, is_demo=bool(demo and demo["mint"] == mint), beta=beta,
                  runs_left=runs_left, runs_cap=runs_cap, notice=notice, limit_kind=limit_kind, reset_ms=_next_midnight_ms(), demo_mint=(demo or {}).get("mint"),
                  n_demo=len(demo["ranges"]) if demo and demo["mint"] == mint else 0, bounced=q.get("notice") == "demo", created=info.get("created_time") or 0, now=int(time.time() * 1000),
                  rows_json=json.dumps(rows), jobs_json=json.dumps(jobs_done), preset_json=json.dumps(preset))


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
    busy = jobs.rq.qsize() >= int(app["s"].get("demo_queue_max", 10))  # черга програвань повна: нове чекало б хвилини — одразу результат
    if not _same_origin(request) or th.wait_s(ip, now) or busy:
        if stored and stored.status == "done" and stored.result:
            return f"/job/{stored.id}"
        if not _same_origin(request):
            raise WebError("Requests must come from this site.", 403)
        raise WebError(_wait_text(th.wait_s(ip, now) or 60), 429)
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
    may spend at most `run_cap_requests` — none of that applies to the admin wallets. Beta testers skip only the daily
    counts (their own, their network's, the site's)."""
    app, s = request.app, request.app["s"]
    if _cross_origin(request):                                          # чужа сторінка не витрачає чиїхось аналізів за день
        raise WebError("Requests must come from this site.", 403)
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
    beta = not admin and pk in _beta(app)                               # a beta tester: no daily counts; the run cap and the month's reserve stay
    gcap = int(s.get("runs_global_per_day", 10))
    if not admin and not beta and app["runs_daily"].left("global", gcap) <= 0:
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
    if not admin and not beta:
        await asyncio.to_thread(_wallet_gate, app, pk)                  # новий чи порожній гаманець: менша денна стеля (05.10)
    same_range()                                                        # друге натискання, поки перше чекало огляд чи баланс: не платить удруге
    # one person, one day's runs: the wallet, the browser and the network are counted together, so connecting another
    # wallet in the same browser adds nothing. No awaits from here to submit: the check and the charge are one step.
    dev, new_dev, charged = _device_id(request), None, []
    worst = int(s.get("run_cap_requests", 0) or 0)
    day_rq = int(s.get("run_requests_per_day", 0) or 0)
    if not admin and day_rq:
        # the day in requests, not only in runs: forty runs at the cap would spend a week of the plan in a day. What the
        # day's finished runs spent, plus the worst case of every run in flight and of this one, stays under the budget
        used = day_rq - app["runs_daily"].left("req:global", day_rq)
        in_flight = sum(1 for j in list(app["jobs"].jobs.values()) if j.status in ("queued", "running") and not j.replay
                        and j.owner and j.owner not in app["admins"])
        if used + (in_flight + 1) * worst > day_rq:
            _limit(app, pk, "run", "budget")
            raise WebError("Today's data budget for new analyses is used up. The demo and every saved result stay open; "
                           "more tomorrow.", 503)
    if not admin and not beta:
        if app["runs_daily"].left("global", gcap) <= 0:                # again, with no await since: a burst cannot slip past the day's cap
            _limit(app, pk, "run", "site")
            raise web.HTTPFound(back + "&notice=sitecap")
        left_today, why = _runs_left(app, pk, dev, ip)
        if left_today <= 0 and why == "network":
            _limit(app, pk, "run", "network")
            raise web.HTTPFound(back + "&notice=netcap")                # свої ще є, а мережа свої вичерпала: вікно каже саме це
        if left_today <= 0 and why == "newwallet":
            _limit(app, pk, "run", "newwallet")
            raise web.HTTPFound(back + "&notice=newwallet")             # новий чи порожній гаманець свій один вичерпав
        if left_today <= 0 or not app["accounts"].take_run(pk, _person_cap(app, pk)):
            _limit(app, pk, "run", "wallet")
            raise web.HTTPFound(back + "&notice=limit")
        if not dev:
            dev = new_dev = secrets.token_hex(16)
        charged = ["dev:" + dev, _ip_key(ip)]
        for key in charged:
            app["runs_daily"].add(key, 1)
    runs.miss(ip, time.time())                                          # звідси починаються витрати — рахуємо цей запуск
    if not admin and not beta:
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
    if _heavy(request):                                 # сторінка на тисячі гаманців: скрипт, що їх перебирає, не тримає процесор
        raise WebError("Too many result pages from your network in a minute. Try again shortly.", 429)
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
    jr = job.result if result else {}
    # a result checked before the labels or «dormant» (owner, 04.10): once, in the background; what is checked is
    # skipped. Only when the owner opens it, or on the draft: on the public site guests and crawlers would queue every
    # old result, and a new analysis would wait behind them for its ages and bundles (release check, 04.10)
    if result and not job.replay and (jr.get("enrich") or {}).get("funders_done") and (
            request.get("acct") in app["admins"] or _private_host(request)) and (
            (app.get("labels") is not None and jr.get("funders") and jr.get("labels_at") is None)
            or (app.get("ages") is not None and jr.get("dormant_at") is None)):
        app["jobs"].resume_enrich(job)
    exch, flab = _labels_for_page(job.result if result else None, _ix_names(request))
    return render("job.html", request, job=job, save_id=job.canon or job.id, jstatus=status, result=result, s=app["s"], back=_back_link(job),
                  rows_json=_json_script(_table(result["rows"])) if result else "", bundle_min=tags.BUNDLE_MIN, burst_ms=tags.BURST_MS,
                  max_my_tags=acct_mod.MAX_MY_TAGS, is_admin=bool(request.get("acct")) and request.get("acct") in app["admins"],
                  age_read=wallet_age_mod.MAX_PAGES * wallet_age_mod.LIMIT,   # скільки транзакцій гаманця читає перевірка віку
                  is_demo=is_demo, agent_chips=app["agent_store"].config()["chips"][:3],   # the agent's quick questions, drawn before any call
                  sm=sm, TAGS=tags.DEFS, created=created or (job.t_from - 24 * HOUR), now=int(time.time() * 1000),
                  cov_text=report.coverage_text((result or {}).get("coverage")), exchanges=exch, flabels=flab,
                 
                  assistant_on=app.get("assistant") is not None,
                  scope=sc, scopes=scope.scopes_for(app["s"]), has_scopes=bool((result or {}).get("wallet_trades")),
                  scope_end=(scope.end_for(sc, job.t_to, (result or {}).get("window", {}).get("end", 0)) if result else None))


def _ix_names(request):
    """Чи показувати назви з міток InsightX. Їхні умови (API Usage) дозволяють похідні висновки, але не їхні дані «в
    сирому чи суттєво схожому вигляді»: на відкритому сайті спонсор — «an exchange», «an app», без назви; назви — на
    закритій копії, щоб власник їх оцінив (04.10). insightx_names: draft | on | off."""
    v = str(request.app["s"].get("insightx_names", "draft"))
    return v == "on" or (v == "draft" and _private_host(request))


def _shown_labels(r, names=True):
    """Мітки InsightX такими, якими їх можна показати: [назва, повна мітка, тип] або без назви — [«an exchange», "", тип]."""
    out = {}
    for a, v in ((r or {}).get("labels") or {}).items():
        if len(v) < 2:
            continue
        kind = v[2] if len(v) > 2 else ""
        out[a] = [v[0], v[1] + " · label: InsightX", kind] if names else [labels_mod.SHORT.get(kind, "a known service"), "", kind]
    return out


def _labels_for_page(r, names=True):
    """Назви спонсорів для сторінки: наш список бірж + біржі з міток InsightX і, окремо, інші сервіси (застосунки,
    казино): ті лише в картці, а не у фільтрі «з бірж». Без назв запис біржі має третім елементом 1."""
    exch, flab = dict(exch_mod.KNOWN), {}
    for a, v in _shown_labels(r, names).items():
        if a in exch:
            continue
        if v[2] == "exchange":
            exch[a] = [v[0], v[1]] if v[1] else [v[0], "", 1]
        else:
            flab[a] = [v[0], v[1], labels_mod.kind_text(v[2])]
    return exch, flab


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
        if "no-exits" in r["tag_list"]:                     # тег прибрано 04.10 (власник): у таблиці «—» замість нього
            r["tag_list"] = [t for t in r["tag_list"] if t != "no-exits"]
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


def _heavy(request):
    """Важкі публічні сторінки результату (таблиця на тисячі гаманців, її JSON і CSV): не більше `heavy_per_min` за
    хвилину з однієї мережі. Людині цього вдосталь; скрипт, що перебирає результати, інакше тримав би процесор єдиного
    процесу зайнятим, і стояв би весь сайт. Повертає, скільки секунд чекати (0 — можна). Адміни поза стелею."""
    app, now = request.app, time.time()
    if request.get("acct") in app["admins"]:
        return 0
    th, ip = app["heavy_throttle"], _ip_key(_client_ip(request))
    wait = th.wait_s(ip, now)
    if not wait:
        th.miss(ip, now)
    return wait


async def _rows_async(app, result, sc):
    """_rows без блокування циклу подій: перерахунок усіх гаманців (0.2-1 с на великому результаті) іде в потоці і
    пам'ятається, доки збагачення не додало тегів. Ключ — сам об'єкт результату: програвання демо ділять один."""
    if _as_stored(result, sc):
        return _stored_rows(result)
    memo = app["rows_memo"]
    key = (id(result), sc, len(result.get("fresh_wallets") or []), len(result.get("bundle") or {}),
           len(result.get("funders") or {}), len(result.get("dormant") or {}))
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
    if _heavy(request):
        return _jerr("Too many requests from your network. Try again in a minute.", 429)
    job = request.app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    sc = _scope(request, request.app["s"])
    rows, _ = await _rows_async(request.app, job.result, sc)
    return web.Response(text=await asyncio.to_thread(_csv_text, rows), content_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{job.id}-{sc}.csv"'})


async def job_json(request):
    """The result as data (for client-side selection/export)."""
    if _heavy(request):
        return _jerr("Too many requests from your network. Try again in a minute.", 429)
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


def _agent_take(app, pk, kind, net=None):
    """Добові стелі агента: своя на гаманець для карток і для питань, на мережу (гаманці безкоштовні, тож без неї пачка
    нових гаманців з однієї адреси закривала б агента для всіх), спільна на сайт. Повертає (відмова, повернути)."""
    s, daily = app["s"], app["assistant_daily"]
    who, cap = (f"agent-ask:{pk}", int(s.get("agent_questions_per_day", 10))) if kind == "ask" else \
        (f"agent-cards:{pk}", int(s.get("agent_cards_per_day", 20)))
    net_key, net_cap = (f"agent-{kind}:net:{net}", cap * 3) if net else (None, 0)   # мережа: кілька людей за однією адресою, не ферма
    gcap = int(s.get("agent_global_per_day", 300))
    if pk not in app["admins"]:
        if daily.left("agent-global", gcap) <= 0:
            _limit(app, pk, "agent-" + kind, "site")
            return _jerr("The agent has answered all it can today. Back tomorrow.", 429), None
        if daily.left(who, cap) <= 0:                               # спершу своє: людині, що вичерпала свої, — саме це
            _limit(app, pk, "agent-" + kind, "wallet")
            return _jerr(f"You have used today's {cap} questions to the agent. More tomorrow." if kind == "ask" else
                         "You have opened the agent on too many analyses today. More tomorrow.", 429), None
        if net_key and daily.left(net_key, net_cap) <= 0:
            _limit(app, pk, "agent-" + kind, "network")
            return _jerr("Your network has used today's questions to the agent. More tomorrow.", 429), None
        daily.add(who, 1)                                           # від перевірок сюди — без await: пачка не проскочить
        if net_key:
            daily.add(net_key, 1)
        daily.take("agent-global", gcap)

    def give_back(paid=None):
        """Відмова моделі повертає спробу, якщо за неї ще не заплачено: питання, що завжди ламає відповідь, інакше
        були б безкоштовними й безкінечними."""
        if pk in app["admins"] or (paid or {}).get("completion_tokens"):
            return
        daily.add(who, -1)
        if net_key:
            daily.add(net_key, -1)
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
    refuse, give_back = _agent_take(app, pk, "cards", _ip_key(_client_ip(request)))
    if refuse:
        return refuse
    fut = asyncio.get_running_loop().create_future()
    app["agent_inflight"][ckey] = fut
    try:
        cards, dropped, usage = await asyncio.to_thread(app["agent"].cards, job.result, cfg, lang)
    except assistant_mod.AssistantError as e:
        give_back(e.usage)
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
    # своє питання — його мовою, впізнаною кодом (власник, 04.10: на «чий це гаманець» прийшла англійська)
    lang = agent_mod.lang_name(body.get("lang")) if chip else agent_mod.question_lang(q, agent_mod.lang_name(body.get("lang")))
    # кнопка-підказка — текстом (його написав власник, це не слова людини); інакше лише «своє питання»
    said = (q[:80] if q in cfg["chips"] else 1) if chip else None
    # розмова (три останні питання з відповідями, як їх показує сторінка) і гаманці, вибрані на сторінці: без них
    # «а цей гаманець?» чи «дай відповідь на попереднє питання» агент чує вперше
    history = []
    for h in (body.get("history") if isinstance(body.get("history"), list) else [])[-agent_mod.MAX_TURNS:]:
        if isinstance(h, dict) and str(h.get("q") or "").strip():
            history.append({"q": " ".join(str(h["q"]).split())[:agent_mod.MAX_QUESTION],
                            "a": " ".join(str(h.get("a") or "").split())[:agent_mod.MAX_ANSWER]})
    focus = [w for w in (body.get("focus") if isinstance(body.get("focus"), list) else [])[:5]
             if isinstance(w, str) and acct_mod.valid_pubkey(w)]
    refuse, give_back = _agent_take(app, pk, "ask", _ip_key(_client_ip(request)))
    if refuse:
        return refuse
    # свої списки людини: які з її збережених гаманців купували тут, у яких списках, з якими її тегами (кастдев 01.10)
    acc = app["accounts"].load(pk) if pk else {}
    names = {k: v.get("name") or k for k, v in (acc.get("lists") or {}).items()}
    mine = {w: {"lists": [names.get(x, x) for x in (m.get("lists") or [])], "tags": list(m.get("my_tags") or [])}
            for w, m in (acc.get("wallets") or {}).items()} if pk else None
    # хто той гаманець, про який питають, поза таблицею (власник, 04.10): його 30 днів на всіх токенах — з кешу картки
    # або зараз (1-5 запитів, добу в кеші, платить денний бюджет графіків)
    rows = job.result.get("rows") or []
    inhere = {x["wallet"] for x in rows}
    dossier = {}
    for w in [x for x in dict.fromkeys(agent_mod.mentioned(q, rows) + focus) if x in inhere][:2]:
        prof = app["profile_cache"].get(f"v{profile.VERSION}:{w}")
        if prof is None and pk and hasattr(app["st"], "wallet_swaps"):
            try:
                settle = _browse_budget(request, 3)
            except WebError:
                settle = None                            # день вичерпано: агент скаже, що знає
            if settle:
                def work(w=w, settle=settle):
                    with app["st"].meter():
                        req0 = app["st"].requests_here()
                        try:
                            return _profile_now(app, w)
                        finally:
                            n = app["st"].requests_here() - req0
                            settle(n)
                            _spend(app, pk, "card-profile", st=n, job=jid)
                try:
                    prof = await asyncio.to_thread(work)
                except Exception:  # noqa: BLE001 — без 30 днів відповідь усе одно буде
                    prof = None
        dossier[w] = {"profile": prof}
    try:
        out, dropped, usage = await asyncio.to_thread(app["agent"].ask, job.result, cfg, q, lang, history, focus, mine, dossier)
    except assistant_mod.AssistantError as e:
        give_back(e.usage)
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
    if status == "done":
        extra["found"] = len(job.result.get("rows") or [])  # «765 wallets found» під великим DONE у терміналі
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
           "dormant": r.get("dormant") or {}, "labels": _shown_labels(r, _ix_names(request)),
           "identities_done": bool(r.get("identities_done")) or snapshot or app["jobs"].namer is None}
    if request.query.get("i") != "1":
        out["identities"] = r.get("identities") or {}
    return web.json_response(out, headers={"Cache-Control": "no-store"})


async def wallet_profile_json(request):
    """The wallet's last days on every token, counted by our own ledger from its raw swaps: PnL, win rate, holds.

    1-5 requests, cached for a day. Only wallets that appear in this analysis are looked up (the site does not
    resell Solana Tracker for arbitrary addresses), or, without `job`, a wallet the connected person keeps in a
    list (the card in Lists): it came from an analysis when it was saved. A cached profile is free for anyone; a
    new one needs a connected wallet and is paid from the same daily budget as charts."""
    app = request.app
    job = None
    if request.query.get("job"):
        job = app["jobs"].get(request.query.get("job", ""))
        if not job or job.status != "done" or not job.result:
            raise web.HTTPNotFound(text="No result yet.")
    wallet = request.query.get("wallet", "")
    if not MINT_RE.match(wallet):
        raise WebError("That does not look like a wallet address.")
    if job is not None:
        if wallet not in {r.get("wallet") for r in job.result.get("rows") or []}:
            raise web.HTTPNotFound(text="That wallet is not in this analysis.")
    elif not request.get("acct"):
        raise ConnectRequired(message="Connect a wallet to load this wallet's last 30 days.")
    elif wallet not in (app["accounts"].load(request["acct"]).get("wallets") or {}):
        raise web.HTTPNotFound(text="That wallet is not in your watchlist.")
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
                _spend(app, pk, "card-profile", st=n, job=(job.canon or job.id) if job else None)
    try:
        out = await asyncio.to_thread(work)
    except Exception as e:  # noqa: BLE001
        log.warning("wallet profile %s: %s", wallet[:8], e)
        raise WebError("The data source did not answer for this wallet. Try again in a minute.", 502)
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
    jobs, hc = request.app["jobs"], request.app.setdefault("health_check", {"at": 0.0, "ok": True})
    now = time.time()
    if now - hc["at"] >= 10:                            # запис на диск — раз на 10 с, не на кожен запит (його може слати будь-хто)
        try:
            (Path(jobs.dir) / ".health").write_text(str(int(now)), encoding="utf-8")
            hc["ok"] = True
        except OSError:
            hc["ok"] = False
        hc["at"] = now
    ok = hc["ok"]
    st = [j.status for j in list(jobs.jobs.values()) if not j.replay]   # програвання демо не тримають деплой
    # no credits here: a public balance would tell anyone when the month runs low and when the cached count refreshes
    body = {"ok": ok, "jobs": len(st), "running": st.count("running"), "queued": st.count("queued"),
            "demo": _demo(request.app) is not None,
            "job_errors": len(jobs.load_errors)}              # скільки файлів аналізів не прочиталось (самі назви — в лозі)
    if request.remote not in ("127.0.0.1", "::1"):
        body = {"ok": ok}           # цифри — лише скрипту деплою зсередини контейнера, і на проді теж (рев'ю 01.10)
    return web.json_response(body, status=200 if ok else 503)
