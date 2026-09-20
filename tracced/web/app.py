"""Pages: / (paste a token) → /token (chart + pump windows) → /job/<id> (progress, table) → CSV.

Blocking Solana Tracker calls run in threads (asyncio.to_thread); the client itself is wrapped in a
lock so the worker thread and page requests share the 3 req/s budget. No tracebacks in the browser:
one plain sentence for the user, details in the container log.
"""
import asyncio
import csv
import hashlib
import os
import secrets
import hmac
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

from ..config import DEFAULTS as CFG_DEFAULTS
from ..early import assistant as assistant_mod, pipeline, report, scope, tags, window
from ..early.store import TradeStore
from . import accounts as acct_mod
from . import chart
from . import replay
from . import waitlist as waitlist_mod
from .jobs import JobQueue

log = logging.getLogger("early.web")
HERE = Path(__file__).resolve().parent
HOUR = 3_600_000
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
COOKIE = "early_web"
ACCT_COOKIE = "early_acct"          # вхід гаманцем: окрема кука, незалежна від пароля бети
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


env.globals["v"] = _asset_version()
from .. import __version__                                   # noqa: E402 — product version for the footer
env.globals["version"] = ".".join(__version__.split(".")[:2])
env.filters["dt"] = chart.fmt_dt
env.filters["dtu"] = lambda ms: chart.fmt_dt(ms, year=True, utc=True)
env.filters["dtl"] = chart.to_input
env.filters["mcap"] = chart.fmt_mcap
env.filters["usd"] = _usd
env.filters["num"] = _num
env.filters["log10"] = lambda v: math.log10(v) if (v and float(v) > 0) else 0.0


class WebError(Exception):
    """A message we show to the user as plain text (400)."""


def make_enricher(ages, s):
    """Після аналізу: вік кожного гаманця з RPC (з паузами) → тег `fresh`; прогрес у result["enrich"]."""
    def enrich(job, save):
        r = job.result
        rows = r.get("rows") or []
        n = min(len(rows), int(s.get("age_lookups_max", 0)))
        e = r.setdefault("enrich", {"done": 0, "total": n, "fresh": 0, "failed": 0})
        e["total"] = n
        if e.get("failed"):
            e.update(done=0, failed=0, fresh=0)            # був збій ноди — перевіряємо заново (кеш лишається)
        for i, row in enumerate(rows[:n], 1):
            if i <= e.get("done", 0):
                continue                                   # продовження після перезапуску
            try:
                age = ages.oldest_tx(row["wallet"])
            except Exception as ex:  # noqa: BLE001 — одна нода/гаманець не має зупиняти решту
                e["failed"] = e.get("failed", 0) + 1
                if e["failed"] <= 3:
                    job.log.append(f"age lookup failed for {row['wallet'][:8]}…: {str(ex)[:60]}")
                age = None
            if age and tags.is_fresh(row.get("first_buy_ms"), age) and "fresh" not in (row.get("tag_list") or []):
                row["tag_list"] = tags.with_tag(row.get("tag_list"), "fresh")
                row["tags"] = "|".join(row["tag_list"])
                fw = r.setdefault("fresh_wallets", [])
                if row["wallet"] not in fw:
                    fw.append(row["wallet"])
                e["fresh"] += 1
            e["done"] = i
            if i % 25 == 0:
                save(job)
                ages.flush()
        # другий прохід: хто дав перший SOL (вік уже в кеші → 1 запит getTransaction на гаманець)
        funders, checked = r.setdefault("funders", {}), set(r.get("funder_checked") or [])
        for i, row in enumerate(rows[:n], 1):
            w = row["wallet"]
            if w in funders or w in checked:
                continue
            try:
                age = ages.oldest_tx(w)
                if age.get("exact") and age.get("n") and not age.get("oldest_sig"):
                    age = ages.oldest_tx(w, refresh=True)          # кеш віку з часів без підпису → 1 запит
                fund = ages.funder(w, age["oldest_sig"]) if age.get("exact") and age.get("oldest_sig") else None
            except Exception as ex:  # noqa: BLE001
                fund = None
                if e.get("failed", 0) <= 3:
                    job.log.append(f"funder lookup failed for {w[:8]}…: {str(ex)[:60]}")
            if fund:
                funders[w] = fund
            checked.add(w)
            e["funders_done"] = i
            if i % 25 == 0:
                r["funder_checked"] = sorted(checked)
                _bundles(r, rows)
                save(job)
                ages.flush()
        r["funder_checked"] = sorted(checked)
        e["funders_done"] = n
        _bundles(r, rows)
        save(job)
        ages.flush()
    return enrich


def _bundles(r, rows):
    """Гаманці зі спільним спонсором (≥ BUNDLE_MIN у цьому списку) → тег bundle."""
    from collections import Counter
    funders = r.get("funders") or {}
    cnt = Counter(funders.values())
    r["bundle"] = {w: {"funder": f, "n": cnt[f]} for w, f in funders.items() if cnt[f] >= tags.BUNDLE_MIN}
    for row in rows:                                    # старі результати без угод: теги прямо в рядках
        if row["wallet"] in r["bundle"] and "bundle" not in (row.get("tag_list") or []):
            row["tag_list"] = tags.with_tag(row.get("tag_list"), "bundle")
            row["tags"] = "|".join(row["tag_list"])


def create_app(st, s, cfg=None, out_dir="output/early/web", store_dir="cache/early", password="", ages=None, assistant=None):
    app = web.Application(middlewares=[errors_mw, auth_mw])
    app["assistant"], app["assistant_cache"] = assistant, {}
    app["st"], app["s"], app["cfg"] = st, s, cfg or {}
    app["store_dir"], app["password"] = store_dir, password or ""
    app["throttle"] = Throttle()
    app["runs"] = Throttle(max_fails=int(s.get("runs_per_hour", 20)), window_s=3600, block_s=3600)
    app["st_lock"] = threading.Lock()
    app["overview_cache"] = {}
    app["accounts"] = acct_mod.AccountStore(Path(out_dir).parent / "accounts")   # поруч з web/ і demo/ у output/early
    app["nonces"] = acct_mod.NonceStore()
    app["events"] = acct_mod.EventLog(Path(out_dir).parent / "accounts" / "_events.jsonl")
    app["admins"] = {w.strip() for w in os.getenv("ADMIN_WALLETS", "").split(",") if w.strip()}   # чиї гаманці бачать /admin
    app["auth_throttle"] = Throttle(max_fails=10, window_s=300, block_s=600)
    app["waitlist"] = waitlist_mod.Waitlist(Path(out_dir).parent / "waitlist.jsonl")
    app["waitlist_throttle"] = Throttle(max_fails=5, window_s=86400, block_s=86400)    # 5 записів на добу з однієї адреси
    _lock_st(st, app["st_lock"])

    def runner(job):
        if job.replay:
            return _replay(job, page_size=int(s.get("page_size", 250)), budget_s=float(s.get("replay_s", 12)))
        return pipeline.run(st, job.mint, job.t_from, job.t_to, s,
                            log=job.log.append, progress=job.set_progress, store_dir=store_dir)

    app["jobs"] = JobQueue(runner, out_dir, enricher=make_enricher(ages, s) if ages else None)
    app.router.add_get("/", index)
    app.router.add_get("/how", how)
    app.router.add_get("/project", project)
    app.router.add_get("/token", token_page)
    app.router.add_get("/candles.json", candles_json)
    app.router.add_post("/analyze", analyze)
    app.router.add_get("/wallet_trades.json", wallet_trades_json)
    app.router.add_get("/job/{id}.state.json", job_state_json)     # before .json: {id} would swallow ".state"
    app.router.add_get("/job/{id}.enrich.json", job_enrich_json)   # before .json: {id} would swallow ".enrich"
    app.router.add_get("/job/{id}.csv", job_csv)     # before /job/{id}: {id} would swallow the dot
    app.router.add_get("/job/{id}.json", job_json)
    app.router.add_post("/job/{id}/assistant", job_assistant)
    app.router.add_get("/job/{id}", job_page)
    app.router.add_get("/health", health)
    app.router.add_get("/login", login)
    app.router.add_post("/login", login)
    app.router.add_post("/auth/nonce", auth_nonce)
    app.router.add_post("/auth/verify", auth_verify)
    app.router.add_post("/auth/logout", auth_logout)
    app.router.add_get("/me", me_page)
    app.router.add_get("/me.json", me_json)
    app.router.add_get("/me/wallets.csv", me_wallets_csv)
    app.router.add_post("/me/wallets", me_add_wallets)
    app.router.add_post("/me/wallets/remove", me_remove_wallet)
    app.router.add_post("/me/wallets/note", me_note)
    app.router.add_post("/me/analyses", me_add_analysis)
    app.router.add_post("/me/analyses/remove", me_remove_analysis)
    app.router.add_get("/admin", admin_page)
    app.router.add_post("/waitlist", waitlist_add)
    app.router.add_static("/static", str(HERE / "static"))
    return app


def _lock_st(st, lock):
    """Every client request under one lock: the 3 req/s pace is shared across threads."""
    orig = getattr(st, "_get", None)
    if orig is None:                      # fake client in tests
        return

    def locked(path):
        with lock:
            return orig(path)
    st._get = locked


# ───────────────────────── middleware ─────────────────────────

@web.middleware
async def errors_mw(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except WebError as e:
        return render("error.html", request, message=str(e), status=400)
    except Exception:
        log.exception("page %s failed", request.path)
        return render("error.html", request,
                      message="Something broke on our side. The log has the details.", status=500)


_RUNTIME_SECRET = secrets.token_hex(32)   # якщо WEB_SECRET не задано: куки живуть до перезапуску


def _secret(pw):
    """Ключ підпису куки. Окремий від пароля: інакше одна перехоплена кука дозволяє підбирати пароль
    офлайн, скільки завгодно швидко і повз будь-який захист від перебору."""
    key = os.getenv("WEB_SECRET") or _RUNTIME_SECRET
    return hashlib.sha256(b"early-web:" + key.encode() + b":" + pw.encode()).digest()


def _sign(pw, exp):
    return f"{exp}." + hmac.new(_secret(pw), str(exp).encode(), hashlib.sha256).hexdigest()[:32]


def _valid(pw, token):
    if not token or "." not in str(token):
        return False
    exp, _, _ = str(token).partition(".")
    try:
        if int(exp) < time.time():
            return False
    except ValueError:
        return False
    return hmac.compare_digest(_sign(pw, int(exp)), str(token))


class Throttle:
    """Makes password guessing slow: a few misses from one address and that address waits.

    The site is public and the password guards an API key with a paid quota, so an unlimited guess rate
    would hand a short password away in minutes. Pure bookkeeping, no I/O — easy to test.
    """

    def __init__(self, max_fails=5, window_s=300, block_s=900):
        self.max_fails, self.window_s, self.block_s = max_fails, window_s, block_s
        self.fails = {}                       # address -> [misses, first miss (s), blocked until (s)]

    def wait_s(self, key, now):
        """Seconds this address still has to wait; 0 means it may try."""
        f = self.fails.get(key)
        return max(0, int(f[2] - now)) if f else 0

    def miss(self, key, now):
        """Count a wrong password; returns the seconds to wait (0 while under the limit)."""
        f = self.fails.get(key)
        if not f or now - f[1] > self.window_s:
            f = [0, now, 0]
        f[0] += 1
        if f[0] >= self.max_fails:
            f[2] = now + self.block_s * (1 + (f[0] - self.max_fails))   # кожна наступна спроба — довша пауза
        self.fails[key] = f
        return max(0, int(f[2] - now))

    def hit(self, key):
        """A correct password clears the record."""
        self.fails.pop(key, None)


def _client_ip(request):
    """The address the request really came from. Behind our proxy that is the last hop it added."""
    xff = request.headers.get("X-Forwarded-For", "")
    return (xff.split(",")[-1].strip() if xff else None) or request.remote or "?"


def _wait_text(s):
    return f"Too many attempts. Try again in {max(1, round(s / 60))} min." if s >= 60 else f"Too many attempts. Try again in {s} s."


ALWAYS_OPEN = ("/login", "/health", "/static", "/project", "/auth/", "/me", "/waitlist")   # /me*, /waitlist — акаунт і лист, грошей не витрачають


async def _is_open(request):
    """Чи цей запит можна пустити без пароля.

    Відкрито рівно те, що не може витратити грошей: сторінка проєкту і демо-токен цілком. Демо
    програється зі знімка, тож жоден із цих шляхів не звертається до платного API. Усе інше — по
    паролю, і саме там лишається аналіз будь-якого іншого токена.
    """
    if request.path.startswith(ALWAYS_OPEN):
        return True
    demo = _demo(request.app)
    if not demo:
        return False
    mint, jobs = demo["mint"], {r["job"] for r in demo["ranges"]}
    # Кожен шлях перевіряємо по ТОМУ САМОМУ параметру, який читає його обробник. Інакше запит
    # відмикається одним полем, а працює по іншому: ?job=<демо>&mint=<будь-який> пройшов би перевірку
    # і витратив платні запити на чужий токен.
    if request.path in ("/token", "/candles.json"):
        return request.query.get("mint") == mint              # обробник дивиться на mint
    if request.path == "/wallet_trades.json":
        return request.query.get("job") in jobs                # обробник дивиться на job
    if request.path == "/analyze" and request.method == "POST":
        return (await request.post()).get("mint") == mint     # тіло кешується, обробник прочитає його ще раз
    if request.path.startswith("/job/"):
        rest = request.path[len("/job/"):]
        if "/" in rest:
            return False                                       # /job/<id>/assistant і будь-що глибше — по паролю
        for suffix in (".state.json", ".enrich.json", ".csv", ".json"):
            if rest.endswith(suffix):
                rest = rest[: -len(suffix)]
                break
        return rest in jobs
    return False


@web.middleware
async def auth_mw(request, handler):
    request["acct"] = _acct(request)                    # хто увійшов гаманцем (або None) — до перевірки пароля
    pw = request.app["password"]
    if not pw or await _is_open(request):
        return await handler(request)
    if not _valid(pw, request.cookies.get(COOKIE)):
        raise web.HTTPFound("/login")
    return await handler(request)


async def login(request):
    throttle, ip, now = request.app["throttle"], _client_ip(request), time.time()
    if request.method == "POST":
        wait = throttle.wait_s(ip, now)
        if wait:
            return render("login.html", request, error=_wait_text(wait), status=429)
        form = await request.post()
        if hmac.compare_digest(str(form.get("password", "")), request.app["password"]):
            throttle.hit(ip)
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, _sign(request.app["password"], int(time.time()) + 14 * 86400),
                            httponly=True, samesite="Lax", secure=True, max_age=14 * 86400)
            raise resp
        wait = throttle.miss(ip, now)
        await asyncio.sleep(1)                                     # повільно навіть до ліміту
        return render("login.html", request, error=_wait_text(wait) if wait else "Wrong password.", status=401)
    wait = throttle.wait_s(ip, now)
    return render("login.html", request, error=_wait_text(wait) if wait else None)


# ───────────────────────── wallet sign-in and the account ─────────────────────────

def _acct_secret():
    return os.getenv("WEB_SECRET") or _RUNTIME_SECRET


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
    resp = web.json_response({"ok": True})
    resp.del_cookie(ACCT_COOKIE)
    return resp


def _demo_job_ids(app):
    demo = _demo(app)
    return {r["job"] for r in demo["ranges"]} if demo else set()


def _job_visible(request, job):
    """Чи має цей запит право на результат: демо — усім, решта — за паролем бети (якщо він заданий)."""
    if not job or job.status != "done" or not job.result:
        return False
    pw = request.app["password"]
    return job.id in _demo_job_ids(request.app) or not pw or _valid(pw, request.cookies.get(COOKIE))


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
    if not _job_visible(request, job):
        return None, _jerr("This analysis is in private beta.", 403)
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
    rows, _ = _rows(job.result, "all", app["s"])
    by = {r["wallet"]: r for r in rows}
    items = [_wallet_snapshot(job, by[w]) for w in dict.fromkeys(str(w) for w in want) if w in by]
    if not items:
        return _jerr("Nothing to save from this analysis.")
    try:
        added, total = app["accounts"].add_wallets(pk, items)
    except acct_mod.AccountError as e:
        return _jerr(str(e))
    app["events"].add(pk, "save_wallets", n=added, job=job.id, symbol=job.symbol)
    return web.json_response({"ok": True, "added": added, "total": total, "skipped": len(want) - len(items),
                              "wallets": [i["wallet"] for i in items]})


@_acct_route
async def me_remove_wallet(request, pk):
    """One wallet ({wallet}) or several ({wallets: [...]})."""
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    want = body.get("wallets") if isinstance(body.get("wallets"), list) else [body.get("wallet")]
    want = [str(w) for w in want if w][: acct_mod.MAX_WALLETS]
    removed = sum(1 for w in want if request.app["accounts"].remove_wallet(pk, w))
    if removed:
        request.app["events"].add(pk, "remove_wallet", n=removed)
    return web.json_response({"ok": bool(removed), "removed": removed})


@_acct_route
async def me_note(request, pk):
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    ok = request.app["accounts"].set_note(pk, str(body.get("wallet") or ""), body.get("note"))
    return web.json_response({"ok": ok}) if ok else _jerr("That wallet is not in your list.", 404)


@_acct_route
async def me_add_analysis(request, pk):
    app = request.app
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    job, err = await _visible_job(request, body)
    if err:
        return err
    rows, sm = _rows(job.result, "all", app["s"])
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
    return web.json_response({"pubkey": pk, "short": _short(pk), "wallets": a["wallets"], "analyses": a["analyses"]},
                             headers={"Cache-Control": "no-store"})


async def me_page(request):
    pk, demo = request.get("acct"), _demo(request.app)
    if not pk:
        return render("me.html", request, wallets=[], analyses=[])
    _, wallets, analyses = _account_view(request.app, pk)
    return render("me.html", request, wallets=wallets, analyses=analyses, demo_mint=(demo or {}).get("mint"))


async def waitlist_add(request):
    """E-mail у лист очікування: лише з цього сайту, з добовим лімітом на адресу."""
    app = request.app
    if not _same_origin(request):
        return _jerr("Requests must come from this site.", 403)
    ip, now, th = _client_ip(request), time.time(), app["waitlist_throttle"]
    if th.wait_s(ip, now):
        return _jerr("Too many sign-ups from this address today.", 429)
    body = await _json_body(request)
    if body is None:
        return _jerr("Bad request body.")
    email = str(body.get("email") or "").strip()
    if not waitlist_mod.EMAIL_RE.match(email.lower()):
        return _jerr("That does not look like an e-mail.")
    pk = request.get("acct") or ""
    added = app["waitlist"].add(email, body.get("note"), pk)
    th.miss(ip, now)
    app["events"].add(pk or "guest", "waitlist", added=added)
    return web.json_response({"ok": True, "added": added})


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
    return render("admin.html", request, accounts=accounts, totals=totals, events=app["events"].tail(100), now=now,
                  waitlist=app["waitlist"].tail(50), waitlist_n=app["waitlist"].count())


ME_COLUMNS = ["wallet", "symbol", "mint", "from_job", "entry_mcap", "invested_usd", "multiple", "tags", "note", "added_utc"]


@_acct_route
async def me_wallets_csv(request, pk):
    _, wallets, _ = _account_view(request.app, pk)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=ME_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in wallets:
        w.writerow({**{k: ("" if r.get(k) is None else r.get(k)) for k in ME_COLUMNS},
                    "tags": "|".join(r.get("tags") or []), "added_utc": chart.fmt_dt(r.get("added_ms") or 0, year=True, utc=True)})
    return web.Response(text=buf.getvalue(), content_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="watchlist.csv"'})


# ───────────────────────── helpers ─────────────────────────

def render(name, request, status=200, **ctx):
    ctx.setdefault("request", request)
    acct = request.get("acct") if request is not None else None
    ctx.setdefault("acct", acct)
    ctx.setdefault("acct_short", _short(acct) if acct else "")
    ctx.setdefault("umami_id", os.getenv("UMAMI_WEBSITE_ID", ""))   # аналітика вмикається лише там, де задано id
    html = env.get_template(name).render(**ctx)
    return web.Response(text=html, content_type="text/html", status=status)


def _mint(v):
    v = (v or "").strip()
    if not MINT_RE.match(v):
        raise WebError("This doesn't look like a Solana token address (32–44 base58 characters).")
    return v


async def _overview(app, mint):
    """token_info + lifetime candles + detector hints; cached in memory for 10 minutes."""
    cache = app["overview_cache"]
    hit = cache.get(mint)
    if hit and time.time() - hit[0] < 600:
        return hit[1], hit[2]
    st, s = app["st"], app["s"]

    def load():
        info = pipeline.token(st, mint)
        ov = pipeline.overview(st, mint, info, s, app["cfg"])
        st.flush()
        return info, ov
    try:
        info, ov = await asyncio.to_thread(load)
    except pipeline.EarlyError as e:
        raise WebError(str(e))
    except Exception as e:  # noqa: BLE001
        log.warning("overview %s: %s", mint[:8], e)
        raise WebError("Solana Tracker returned no data for this token. Check the address or try again later.")
    cache[mint] = (time.time(), info, ov)
    return info, ov


def _rows_from_hints(hints):
    rows = []
    for i, h in enumerate(hints, 1):
        rows.append({
            "n": i,
            "label": f"Pump {i} · {chart.fmt_mcap(h['base_mcap'])} → {chart.fmt_mcap(h['peak_mcap'])} ×{h['magnitude']}",
            "from": chart.to_input(h["acc_start"]),
            "to": chart.to_input(h["pump_start"]),
        })
    return rows or [{"n": 1, "label": "Range 1", "from": "", "to": ""}]


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
    """Demo: play a believable run built from the stored result's own numbers, then return that result (0 requests)."""
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
    jid = app["s"].get("demo_job")
    d = Path(app["jobs"].dir).parent / "demo"
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
    want = (app["s"].get("example_job") or "")
    example = app["jobs"].get(want) if want else None
    if not example or example.status != "done":
        done = [j for j in jobs if j.status == "done" and j.result and j.result.get("rows")]
        example = min(done, key=lambda j: j.created_ms or 0) if done else None      # найстарший готовий = показовий
    my_n = len(app["accounts"].load(request["acct"])["analyses"]) if request.get("acct") else 0
    return render("index.html", request, tokens=_by_token(jobs, example.id if example else None),
                  totals=totals, sample=sample, bg_lines=lines, my_n=my_n)


async def how(request):
    return render("how.html", request, s=request.app["s"], TAGS=tags.DEFS)


async def project(request):
    """Статична сторінка проєкту: те, що подається на хакатон. Нічого не рахує і не ходить у мережу."""
    return render("project.html", request)


async def token_page(request):
    app = request.app
    mint = _mint(request.query.get("mint"))
    s = app["s"]
    demo = _demo(app)
    hints = []                                                          # для «Find the pump»: підказки детектора (демо — записані діапазони)
    if demo and demo["mint"] == mint:                                   # демо-токен: усе зі знімка, 0 запитів
        info = demo["info"]
        rows = [{"n": i + 1, "label": r.get("label") or f"Demo range {i + 1}", "job": r.get("job"),
                 "from": chart.to_input(r["from"]), "to": chart.to_input(r["to"])}
                for i, r in enumerate(demo["ranges"])]
    else:
        info, ov = await _overview(app, mint)
        rows = _rows_from_hints(ov["hints"])
        hints = [{"from": h["acc_start"], "to": h["pump_start"], "base": h["base_mcap"], "peak": h["peak_mcap"], "mag": h["magnitude"]}
                 for h in ov["hints"]]
    detect_cfg = dict(CFG_DEFAULTS.get("detect") or {}, **((app["cfg"] or {}).get("detect") or {}))
    q = request.query
    preset = None
    if chart.from_input(q.get("from")) and chart.from_input(q.get("to")):
        preset = {"n": None, "label": "From the result", "from": q.get("from"), "to": q.get("to")}
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
                     "job": j.id, "from": key[0], "to": key[1]})
    return render("token.html", request, info=info, mint=mint, s=s, is_demo=bool(demo and demo["mint"] == mint),
                  n_demo=len(demo["ranges"]) if demo and demo["mint"] == mint else 0, bounced=q.get("notice") == "demo", created=info.get("created_time") or 0, now=int(time.time() * 1000),
                  rows_json=json.dumps(rows), jobs_json=json.dumps(jobs_done), preset_json=json.dumps(preset),
                  hints_json=json.dumps(hints), min_peak=int(detect_cfg.get("min_peak_mcap") or 1_000_000))


async def candles_json(request):
    """Market-cap candles for the browser chart: ?mint&tf&a&b (a, b in unix seconds)."""
    app = request.app
    q = request.query
    mint = _mint(q.get("mint"))
    tf = q.get("tf") if q.get("tf") in chart.TFS else "1h"
    try:
        a, b = int(float(q.get("a", 0))), int(float(q.get("b", 0)))
    except ValueError:
        raise WebError("Bad time range.")
    if b <= a:
        return web.json_response([])
    demo = _demo(app)
    if demo and demo["mint"] == mint:
        cs = [c for c in (demo.get("candles") or {}).get(tf) or [] if a * 1000 <= c["time"] <= b * 1000]
        return web.json_response(chart.candles_mcap(cs, demo["info"]["supply"]))
    info, _ = await _overview(app, mint)
    now = int(time.time())
    created = int((info.get("created_time") or 0) // 1000)
    a, b = chart.snap_range(max(a, created - 3600), min(b, now + 3600), tf)
    if b <= a:
        return web.json_response([])
    st = app["st"]

    def load():
        c = st.chart(mint, tf, a * 1000, b * 1000)
        st.flush()
        return c
    candles = await asyncio.to_thread(load)
    return web.json_response(chart.candles_mcap(candles, info["supply"]))


async def analyze(request):
    app = request.app
    ip = _client_ip(request)
    runs = app["runs"]                                   # платний шлях: обмежуємо навіть тих, хто зайшов
    wait = runs.wait_s(ip, time.time())
    if wait:
        raise WebError(f"Too many analyses from this address. Try again in {max(1, round(wait / 60))} min.")
    form = await request.post()
    mint = _mint(form.get("mint"))
    s = app["s"]
    t_from, t_to = chart.from_input(form.get("from")), chart.from_input(form.get("to"))
    demo = _demo(app)
    if demo and demo["mint"] == mint:
        for r in demo["ranges"]:                                        # демо: програємо збережений аналіз зі знімка
            if t_from and t_to and abs(t_from - r["from"]) <= 60_000 and abs(t_to - r["to"]) <= 60_000:
                job = app["jobs"].submit(mint, r["from"], r["to"], symbol=demo["info"].get("symbol"),
                                         replay={"log": list(r.get("log") or []), "result": r["result"]})
                raise web.HTTPFound(f"/job/{job.id}")
        raise web.HTTPFound(f"/token?mint={mint}&notice=demo")           # інший діапазон — без живого (платного) прогону
    runs.miss(ip, time.time())                           # звідси починаються витрати — рахуємо цей запуск
    info, _ = await _overview(app, mint)
    errs = window.validate(t_from, t_to, info.get("created_time"), int(time.time() * 1000),
                           max_window_ms=int(s.get("max_window_hours", 0) * HOUR) or None)
    if errs:
        raise WebError(" ".join(errs))
    job = app["jobs"].submit(mint, t_from, t_to, symbol=info.get("symbol"))
    raise web.HTTPFound(f"/job/{job.id}")


def _hours_text(ms):
    h = ms / HOUR
    return f"{h:.1f}" if h < 1 else f"{h:.0f}"


def _back_link(job):
    return f"/token?mint={job.mint}&from={chart.to_input(job.t_from)}&to={chart.to_input(job.t_to)}"


async def job_page(request):
    app = request.app
    job = app["jobs"].get(request.match_info["id"])
    if not job:
        raise web.HTTPNotFound(text="No such analysis.")
    created = ((job.result or {}).get("info") or {}).get("created_time") or 0
    if not created and job.status == "done":
        try:
            info, _ = await _overview(app, job.mint)
            created = info.get("created_time") or 0
        except WebError:
            created = 0
    status, result = job.status, job.result             # знімок: статус міняється з робочого потоку
    sm, sc = None, _scope(request, app["s"])
    if status == "done" and result:
        rows, sm = _rows(result, sc, app["s"])
        result = dict(result, rows=rows)
    else:
        result = None
    return render("job.html", request, job=job, jstatus=status, result=result, s=app["s"], back=_back_link(job),
                  sm=sm, TAGS=tags.DEFS, created=created or (job.t_from - 24 * HOUR), now=int(time.time() * 1000),
                  cov_text=report.coverage_text((result or {}).get("coverage")), default_method=assistant_mod.DEFAULT_METHOD,
                  assistant_on=app.get("assistant") is not None,
                  scope=sc, scopes=scope.scopes_for(app["s"]), has_scopes=bool((result or {}).get("wallet_trades")),
                  scope_end=(scope.end_for(sc, job.t_to, (result or {}).get("window", {}).get("end", 0)) if result else None))


def _scope(request, s):
    sc = request.query.get("scope", "all")
    return sc if sc in scope.scopes_for(s) else "all"


def _rows(result, sc, s):
    """Рядки за масштабом з угод у результаті; старі результати без угод — як збережено."""
    out = scope.rows_for(result, sc, s) if sc != "all" or result.get("wallet_trades") else None
    if out:
        return out
    rows = result.get("rows") or []
    for r in rows:                                          # результати до появи тегів
        r.setdefault("tag_list", (r.get("tags") or "").split("|") if r.get("tags") else [])
    return rows, {**report.summary(rows), **(result.get("summary") or {})}


async def job_csv(request):
    job = request.app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    sc = _scope(request, request.app["s"])
    rows, _ = _rows(job.result, sc, request.app["s"])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=report.COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in report.COLUMNS})
    return web.Response(text=buf.getvalue(), content_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{job.id}-{sc}.csv"'})


async def job_json(request):
    """The result as data (for client-side selection/export)."""
    job = request.app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    r = job.result
    sc = _scope(request, request.app["s"])
    rows, _ = _rows(r, sc, request.app["s"])
    return web.json_response({"id": job.id, "mint": job.mint, "window": r["window"], "mode": r.get("mode"),
                              "scope": sc, "coverage": r.get("coverage"), "columns": report.COLUMNS, "rows": rows})


async def job_assistant(request):
    """The assistant picks wallets to watch from the facts in the table + the user's method (JSON in/out)."""
    app = request.app
    job = app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        return web.json_response({"error": "No result yet."}, status=404)
    a = app.get("assistant")
    if a is None:
        return web.json_response({"error": "The assistant is not configured on this server: set ASSISTANT_KEY "
                                           "(and optionally ASSISTANT_URL, ASSISTANT_MODEL) in .env."}, status=503)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    method = str(body.get("method") or "")[:2000]
    want = body.get("wallets")
    sc = body.get("scope") if body.get("scope") in scope.scopes_for(app["s"]) else "all"
    rows, _ = _rows(job.result, sc, app["s"])
    if isinstance(want, list) and want:
        keep = set(str(w) for w in want)
        rows = [r for r in rows if r["wallet"] in keep]
    rows = rows[:assistant_mod.MAX_ROWS]
    if not rows:
        return web.json_response({"error": "No wallets to look at — clear the filters."}, status=400)
    key = hashlib.sha1((job.id + sc + method + ",".join(r["wallet"] for r in rows)).encode()).hexdigest()
    cached = app["assistant_cache"].get(key)
    if cached:
        return web.json_response(dict(cached, cached=True))
    try:
        out = await asyncio.get_running_loop().run_in_executor(None, a.ask, rows, method)
    except assistant_mod.AssistantError as e:
        return web.json_response({"error": str(e)}, status=502)
    out["n_rows"] = len(rows)
    app["assistant_cache"][key] = out
    return web.json_response(out)


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
    if status == "done" and not job.result:
        status, error = "error", "The analysis finished without a result. Details are in the container log."
    n = len(job.log)
    return web.json_response(
        {"id": job.id, "mint": job.mint, "symbol": job.symbol, "status": status, "error": error,
         "started_ms": job.started_ms or job.created_ms, "finished_ms": job.finished_ms,
         "now_ms": int(time.time() * 1000), "since": min(since, n), "n_lines": n,
         "log": job.log[since:n] if since < n else [], "progress": job.progress},
        headers={"Cache-Control": "no-store"})


async def job_enrich_json(request):
    """Progress of the background wallet-age check and the wallets tagged `fresh` so far."""
    job = request.app["jobs"].get(request.match_info["id"])
    if not job or job.status != "done" or not job.result:
        raise web.HTTPNotFound(text="No result yet.")
    e = job.result.get("enrich") or {"done": 0, "total": 0, "fresh": 0}
    fresh = [r["wallet"] for r in job.result.get("rows") or [] if "fresh" in (r.get("tag_list") or [])]
    return web.json_response({"done": e.get("done", 0), "total": e.get("total", 0), "fresh": fresh,
                              "funders": job.result.get("funders") or {}, "bundle": job.result.get("bundle") or {}})


async def wallet_trades_json(request):
    """One wallet's buys and sells on the analysed token, for the chart markers.

    Full-trades mode: from the cached token feed (no requests). Per-wallet mode: the wallet's own
    trades from Solana Tracker (1 request, cached). Exact trade times; market cap = price × supply."""
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

    def work():
        if stored is not None:                                        # уся історія гаманця вже в результаті
            return scope.unpack(wallet, stored.get("trades") or [])
        if job.result.get("mode") == "trades":
            trs = TradeStore(app["store_dir"], mint).between(a, b)
            return [t for t in trs if t.get("wallet") == wallet]
        return [t for t in st.wallet_token_trades(wallet, mint, s.get("max_wallet_trade_pages", 4))
                if t["time"] is not None and a <= t["time"] <= b]
    trs = await asyncio.get_running_loop().run_in_executor(None, work)
    trs.sort(key=lambda t: t["time"] or 0)
    cap = int(s.get("markers_max", 200))
    out = [{"t": t["time"], "side": t["type"], "usd": t.get("usd"), "qty": t.get("qty"),
            "mcap": (t.get("price") or 0) * supply} for t in trs[:cap] if t["type"] in ("buy", "sell")]
    return web.json_response({"wallet": wallet, "n": len(trs), "truncated": len(trs) > cap, "trades": out,
                              "complete": (stored or {}).get("source") != "entry-only" if stored is not None else True})


async def health(request):
    return web.json_response({"ok": True, "jobs": len(request.app["jobs"].jobs)})
