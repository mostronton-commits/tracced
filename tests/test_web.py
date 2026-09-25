"""The web page on a fake client: no network. Needs aiohttp (present in Docker)."""
import asyncio
import json
import os
import re
import tempfile
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # host without aiohttp: page tests are skipped
    AioHTTPTestCase = None

from tracced.early import settings

try:
    from tests.test_early_pipeline import TRADES, FakeST, T0, MIN, H
except ImportError:                       # discover -s tests without -t: modules without package prefix
    from test_early_pipeline import TRADES, FakeST, T0, MIN, H

CYRILLIC = re.compile("[Ѐ-ӿ]")
MINT = "A" * 40


class FakeWebST(FakeST):
    fail_mints, fail_trades = (), False                       # switches for the failure paths

    def chart_cached(self, mint, interval, t_from, t_to):
        return False                                          # the fake has no chart cache: every chunk counts

    def token_info(self, mint):
        if mint in self.fail_mints:
            self.requests += 1
            raise RuntimeError("no such token")
        return super().token_info(mint)

    def trades_page(self, mint, cursor):
        if self.fail_trades:
            self.requests += 1
            raise RuntimeError("feed down")
        return super().trades_page(mint, cursor)

    def wallet_swaps(self, owner, since_ms, max_pages=5):
        """Обміни гаманця по всіх токенах: одна купівля і один продаж з прибутком $50."""
        self.requests += 1
        sol = "So11111111111111111111111111111111111111112"
        t = since_ms + 86_400_000
        return [{"tx": "p1", "wallet": owner, "time": t, "from": {"address": sol, "amount": 1.0},
                 "to": {"address": "TOKA", "amount": 1000, "token": {"symbol": "TOKA"}}, "volume": {"usd": 100.0, "sol": 1.0}},
                {"tx": "p2", "wallet": owner, "time": t + 3_600_000, "from": {"address": "TOKA", "amount": 1000},
                 "to": {"address": sol, "amount": 1.5}, "volume": {"usd": 150.0, "sol": 1.5}}], False

    def chart(self, mint, interval, t_from, t_to):
        self.requests += 1
        # ×10 vs trades: with supply 1e6 the cap goes 1M→6M, above min_peak_mcap, so the detector hints
        closes = [1.0] * 40 + [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0] + [6.0] * 20
        return [{"time": T0 - H + i * MIN, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1}
                for i, c in enumerate(closes)]


if AioHTTPTestCase:
    from tracced.web import chart
    from tracced.web import accounts as acct_mod
    from tracced.web.app import create_app, _acct_secret

    TEST_PK = acct_mod.b58encode(b"\x07" * 32)          # гаманець, від імені якого тести запускають живі аналізи
    GUEST = {"Cookie": ""}                                # той самий запит без гаманця

    def wallet_cookie(pk):
        """Кука акаунта без підпису гаманцем: тести знають секрет сервера, а перевірка та сама, що для людей."""
        return "early_acct=" + acct_mod.sign_acct(_acct_secret(), pk, 4_000_000_000)

    class TestWeb(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            s = settings.load()
            s["replay_s"] = 0.6                                          # демо програється швидко, щоб тести не чекали
            s["ranges_per_token"] = 50                                   # стеля перевіряється окремим тестом
            app = create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}                                    # без добової квоти, як у власника
            return app

        async def setUpAsync(self):
            await super().setUpAsync()
            self.client.session.headers["Cookie"] = wallet_cookie(TEST_PK)   # усі запити — від підключеного гаманця

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)      # let the worker finish writing
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()                             # зупинка пише кеші — поки тека ще є
            self.tmp.cleanup()

        @property
        def same_site(self):
            """Origin цього сайту: нове програвання демо, як і записи акаунта, приймається лише з його сторінок."""
            return {"Origin": f"http://{self.client.host}:{self.client.port}"}

        async def test_demo_token_replays_without_requests(self):
            # a stored analysis + a snapshot make the demo token replay the whole flow with zero ST requests
            import os
            jid = "AAAAAA_20010909-0146_0206"
            stored = {"id": jid, "mint": MINT, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done",
                      "error": None, "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "TST",
                      "progress": {"phase": "done", "done": 1, "total": 1}, "log": ["page 1: 3 trades (+3 new)", "  exits: 1/1", "done (wallet-trades): 1 wallets"],
                      "result": {"info": {"mint": MINT, "symbol": "TST", "supply": 1000000, "created_time": 999996400000},
                                 "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                                 "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1, "dust": 0, "late": 0, "pre_range_only": 0, "lookups": 1, "entry_only": 0},
                                 "coverage": {"exits_known": 1, "total": 1, "mode": "wallet-trades", "cost_full": 5, "lookup_cap": 500, "plan": "free"},
                                 "wallet_trades": {"A": {"trades": [[1000000060000, "buy", 100.0, 100.0, 1.0], [1000001800000, "sell", 50.0, 150.0, 3.0]], "source": "wallet-trades"}},
                                 "price_at_end": 3.0, "fresh_wallets": [], "scope": "all", "rows": [], "summary": {}, "requests": 0, "pages_fetched": 0,
                                 "enrich": {"done": 0, "total": 0, "fresh": 0, "failed": 0, "funders_done": 0}}}
            out = self.tmp.name + "/web"; os.makedirs(self.tmp.name + "/demo", exist_ok=True)
            with open(f"{out}/{jid}.json", "w") as f:
                json.dump(stored, f)
            snap = {"mint": MINT, "info": stored["result"]["info"], "created": 999996400000, "captured_ms": 1000003560000,
                    "candles": {"1m": [{"time": 999999960000 + i * 60000, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 1} for i in range(30)]},
                    "hints": [], "job": jid, "range": {"from": 999999960000, "to": 1000001160000},
                    "log": stored["log"], "result": stored["result"]}          # знімок самодостатній
            with open(f"{self.tmp.name}/demo/{MINT}.json", "w") as f:
                json.dump(snap, f)
            self.app["jobs"]._load(); self.app["s"]["demo_job"] = jid; self.app.pop("demo", None)
            before = self.st.requests
            r = await self.client.get(f"/token?mint={MINT}")
            self.assertEqual(r.status, 200)
            html = await r.text()
            self.assertIn("Demo range", html)
            self.assertIn('class="chip demo"', html)
            # another range on the demo token bounces back with a note instead of a live run
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T02:30", "to": "2001-09-09T02:50"}, allow_redirects=False)
            self.assertEqual(r.status, 302)
            self.assertEqual(r.headers["Location"], f"/token?mint={MINT}&notice=demo")
            r = await self.client.get(r.headers["Location"])
            self.assertIn("Only the range below is recorded.", await r.text())
            self.assertEqual(self.st.requests, before)
            r = await self.client.get(f"/candles.json?mint={MINT}&tf=1m&a=999999900&b=1000002000")
            self.assertEqual(r.status, 200)
            self.assertTrue(len(await r.json()) > 5)
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"},
                                       allow_redirects=False, headers=self.same_site)
            self.assertEqual(r.status, 302)
            loc = r.headers["Location"]
            self.assertTrue(loc.startswith(f"/job/{jid}_r"), loc)                   # справжнє програвання, не збережений результат
            html = ""
            for _ in range(80):
                r = await self.client.get(loc); html = await r.text()
                if "↓ Export" in html: break
                await asyncio.sleep(0.1)
            self.assertIn("↓ Export", html)
            self.assertNotIn("Whole history", html)                      # no scope switch: the numbers are the whole history
            self.assertEqual(self.st.requests, before)                    # not a single request to Solana Tracker
            st = await (await self.client.get(loc + ".state.json?since=0")).json()
            self.assertTrue(any(l.startswith("page 1: 3 trades (+3 new)") for l in st["log"]), st["log"])   # a believable run from the stored numbers
            self.assertTrue(any(l.startswith("done (wallet-trades): 1 wallets") for l in st["log"]))
            with open(f"{out}/{jid}.json") as f:                               # програвання не перезаписує збережений аналіз
                self.assertEqual(json.load(f), stored)

        async def test_demo_can_hold_several_ranges(self):
            # знімок із кількома діапазонами: кожен програється зі свого запису, чужий діапазон не йде в живий прогін
            import os
            def result(a, b):
                return {"info": {"mint": MINT, "symbol": "TST", "supply": 1000000, "created_time": 999996400000},
                        "window": {"from": a, "to": b, "end": b + 3600000}, "mode": "wallet-trades",
                        "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1, "dust": 0, "late": 0, "pre_range_only": 0,
                                   "lookups": 1, "entry_only": 0},
                        "coverage": {"exits_known": 1, "total": 1, "mode": "wallet-trades", "cost_full": 5,
                                     "lookup_cap": 500, "plan": "free"},
                        "wallet_trades": {"A": {"trades": [[a + 1000, "buy", 100.0, 100.0, 1.0]], "source": "wallet-trades"}},
                        "price_at_end": 3.0, "fresh_wallets": [], "scope": "all", "rows": [], "summary": {},
                        "requests": 0, "pages_fetched": 0,
                        "enrich": {"done": 0, "total": 0, "fresh": 0, "failed": 0, "funders_done": 0}}
            one, two = ("AAAAAA_20010909-0146_0206", 999999960000, 1000001160000), ("AAAAAA_20010909-0300_0320", 1000004400000, 1000005600000)
            os.makedirs(self.tmp.name + "/demo", exist_ok=True)
            snap = {"mint": MINT, "info": result(*one[1:])["info"], "created": 999996400000, "captured_ms": 1,
                    "candles": {"1m": []}, "hints": [],
                    "ranges": [{"label": "Pump 1", "from": one[1], "to": one[2], "job": one[0], "log": ["first"], "result": result(one[1], one[2])},
                               {"label": "Pump 2", "from": two[1], "to": two[2], "job": two[0], "log": ["second"], "result": result(two[1], two[2])}]}
            with open(f"{self.tmp.name}/demo/{MINT}.json", "w") as f:
                json.dump(snap, f)
            self.app["s"]["demo_job"] = one[0]; self.app.pop("demo", None)
            before = self.st.requests
            html = await (await self.client.get(f"/token?mint={MINT}")).text()
            self.assertIn("Pump 1", html)
            self.assertIn("Pump 2", html)
            self.assertIn("2 pumps replayed without requests", html)      # текст знає, що діапазонів кілька
            for jid, a, b in (one, two):                                   # обидва програються
                r = await self.client.post("/analyze", allow_redirects=False, headers=self.same_site, data={
                    "mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)})
                self.assertTrue(r.headers["Location"].startswith(f"/job/{jid}_r"), r.headers["Location"])
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T06:00", "to": "2001-09-09T06:20"},
                                       allow_redirects=False)
            self.assertEqual(r.headers["Location"], f"/token?mint={MINT}&notice=demo")
            self.assertEqual(self.st.requests, before)                     # жодного платного запиту

        async def test_demo_survives_a_broken_job_file(self):
            # знімок самодостатній: навіть якщо аналіз на диску обірвався, демо не йде в живий (платний) прогін
            import os
            jid = "BBBBBB_20010909-0146_0206"
            out = self.tmp.name + "/web"; os.makedirs(self.tmp.name + "/demo", exist_ok=True)
            result = {"info": {"mint": MINT, "symbol": "TST", "supply": 1000000, "created_time": 999996400000},
                      "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                      "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1, "dust": 0, "late": 0, "pre_range_only": 0, "lookups": 1, "entry_only": 0},
                      "coverage": {"exits_known": 1, "total": 1, "mode": "wallet-trades", "cost_full": 5, "lookup_cap": 500, "plan": "free"},
                      "wallet_trades": {"A": {"trades": [[1000000060000, "buy", 100.0, 100.0, 1.0]], "source": "wallet-trades"}},
                      "price_at_end": 3.0, "fresh_wallets": [], "scope": "all", "rows": [], "summary": {}, "requests": 0, "pages_fetched": 0,
                      "enrich": {"done": 0, "total": 0, "fresh": 0, "failed": 0, "funders_done": 0}}
            with open(f"{out}/{jid}.json", "w") as f:                          # аналіз обірвано рестартом
                json.dump({"id": jid, "mint": MINT, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None,
                           "status": "running", "error": None, "created_ms": 1, "started_ms": 1, "finished_ms": None,
                           "symbol_hint": "TST", "progress": {"phase": "trades", "done": 0, "total": 1}, "log": [], "result": None}, f)
            with open(f"{self.tmp.name}/demo/{MINT}.json", "w") as f:
                json.dump({"mint": MINT, "info": result["info"], "created": 999996400000, "captured_ms": 1000003560000,
                           "candles": {"1m": []}, "hints": [], "job": jid,
                           "range": {"from": 999999960000, "to": 1000001160000}, "log": ["done"], "result": result}, f)
            self.app["jobs"]._load(); self.app["s"]["demo_job"] = jid; self.app.pop("demo", None)
            self.assertEqual(self.app["jobs"].get(jid).status, "error")        # обірваний аналіз позначено помилкою
            before = self.st.requests
            r = await self.client.get(f"/token?mint={MINT}")
            self.assertIn('class="chip demo"', await r.text())
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T05:00", "to": "2001-09-09T05:20"}, allow_redirects=False)
            self.assertEqual(r.headers["Location"], f"/token?mint={MINT}&notice=demo")
            self.assertEqual(self.st.requests, before)                         # жодного платного запиту

        async def test_throttle_slows_down_guessing(self):
            # публічний сайт: після кількох промахів адреса чекає, і успіх теж не пускає, поки пауза не мине
            from tracced.web.app import Throttle
            t = Throttle(max_fails=3, window_s=300, block_s=60)
            self.assertEqual(t.wait_s("1.2.3.4", 0), 0)
            self.assertEqual((t.miss("1.2.3.4", 0), t.miss("1.2.3.4", 1)), (0, 0))
            self.assertEqual(t.miss("1.2.3.4", 2), 60)                     # третій промах — пауза
            self.assertEqual(t.wait_s("1.2.3.4", 30), 32)                 # блок від моменту промаху (t=2)
            self.assertEqual(t.wait_s("5.6.7.8", 30), 0)                   # інша адреса не страждає
            self.assertEqual(t.wait_s("1.2.3.4", 100), 0)                  # пауза минула
            t.miss("9.9.9.9", 0); t.hit("9.9.9.9")
            self.assertEqual(t.wait_s("9.9.9.9", 0), 0)                    # успіх очищає лічильник
            t2 = Throttle(max_fails=1, window_s=300, block_s=60)
            self.assertGreater(t2.miss("a", 0), 0)
            self.assertGreater(t2.miss("a", 1), 60)                        # кожна наступна спроба довша

        async def test_layout_containers(self):
            # верстка тримається на трьох речах: смуги шапки/підвалу з внутрішнім контейнером і широка сторінка результату
            for path in ("/", "/docs"):
                html = await (await self.client.get(path)).text()
                self.assertIn('<footer class="foot"><div class="foot-in">', html)
                self.assertIn(">v0.4<", html)                                   # product version, not the asset hash
                self.assertIn('href="https://github.com/mostronton-commits/tracced"', html)
                self.assertIn('href="https://x.com/tracced_xyz"', html)
            html = await (await self.client.get("/docs")).text()
            self.assertIn('<header class="top"><div class="top-in">', html)
            self.assertNotIn('<main class="wide"', html)
            await self.client.get(f"/token?mint={MINT}")
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"},
                                       allow_redirects=False)
            html = await (await self.client.get(r.headers["Location"])).text()
            self.assertIn('<main class="wide"', html)                      # таблиці потрібна ширина

        async def test_amounts_are_kept_in_both_dollars_and_sol(self):
            # кожна сума несе обидві одиниці з тієї самої угоди; перемикач у підвалі лише вибирає, яку показати
            await self.client.get(f"/token?mint={MINT}")
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"},
                                       allow_redirects=False)
            loc, html = r.headers["Location"], ""
            for _ in range(80):
                html = await (await self.client.get(loc)).text()
                if "↓ Export" in html: break
                await asyncio.sleep(0.1)
            self.assertIn("↓ Export", html)
            self.assertIn('id="cur"', html)                                # перемикач USD | SOL над таблицею
            self.assertIn('class="button holo" id="askbtn"', html)         # сяйво лишилось тільки на кнопці агента
            for el in ('id="dtags"', 'id="dchips"', 'id="dprof"', 'id="dprofi"', 'id="dstar"', 'id="dcopy"',
                       'id="dfacts"', 'id="dcross"', 'id="dtrades"', 'id="dnote"', 'id="dclose"'):
                self.assertIn(el, html)                                    # картка гаманця: секції, на які спирається скрипт
            self.assertIn('class="button wl" id="watchbtn"', html)
            m = re.search(r'<script type="application/json" id="rowsdata">(.*?)</script>', html, re.S)
            table = json.loads(m.group(1))                                 # рядки йдуть даними, малює їх браузер
            first = dict(zip(table["f"], table["r"][0]))
            self.assertIsNotNone(first["invsol"])                          # рядок таблиці несе суми в SOL
            self.assertEqual(table["f"][-1], "eavg")                       # середній вхід — нове поле в кінці, старі на місці
            self.assertEqual(table["f"][:3], ["w", "inv", "invsol"])
            self.assertGreater(first["eavg"], 0)                           # «Exit vs entry» ділить саме на нього
            self.assertIsNone(re.search(r'<tr data-w="[1-9A-HJ-NP-Za-km-z]{20,}"', html))   # жодного рядка розміткою: 2 500 рядків вішали телефон
            self.assertIn("data-sol=", html)                               # плитка «Spent in range» теж у SOL
            self.assertNotIn('class="muted small solnote"', html)          # свіжий результат не виправдовується

            # угоди гаманця для графіка й картки: SOL іде з тієї самої збереженої угоди, без нових запитів
            jid, mint = "DDDDDD_20010909-0146_0206", "D" * 40
            w = acct_mod.b58encode(b"\x03" * 32)
            stored = {"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done",
                      "error": None, "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "DDD",
                      "progress": {"phase": "done", "done": 1, "total": 1}, "log": [],
                      "result": {"info": {"mint": mint, "symbol": "DDD", "supply": 1000000, "created_time": 999996400000},
                                 "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                                 "counts": {"n_wallets": 1, "n_trades": 1, "n_early": 1},
                                 "coverage": {"exits_known": 1, "total": 1, "mode": "wallet-trades"},
                                 "wallet_trades": {w: {"trades": [[1000000020000, "buy", 100.0, 200.0, 2.0, 1.25]],
                                                       "source": "wallet-trades"}},
                                 "rows": [{"wallet": w}], "scope": "all", "requests": 0}}
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump(stored, f)
            self.app["jobs"]._load()
            before = self.st.requests
            d = await (await self.client.get(f"/wallet_trades.json?job={jid}&wallet={w}")).json()
            self.assertEqual(self.st.requests, before)                     # усе вже в результаті
            self.assertEqual(d["trades"][0]["sol"], 1.25)
            self.assertEqual(d["trades"][0]["usd"], 200.0)

        async def test_a_result_saved_before_sol_says_so_instead_of_showing_dollars_as_sol(self):
            # старий запис не має сум у SOL: сторінка каже це прямо, а не підсовує долари під значком ◎
            from tracced.early import report
            rows = [{"invested_in_range_usd": 10.0, "invested_in_range_sol": None, "proceeds_sol": None,
                     "sold_share_pct": 0.0, "realized_usd": 0.0}]
            sm = report.summary(rows)
            self.assertFalse(sm["has_sol"])
            self.assertIsNone(sm["invested_range_sol"])
            self.assertIsNone(sm["realized_total_sol"])

        async def test_a_rerun_is_not_overwritten_by_the_old_enrichment(self):
            # той самий діапазон запустили вдруге: збагачення першого прогону не має перетерти новий результат
            q = self.app["jobs"]
            old = q.submit(MINT, 999999960000, 1000001160000)
            await asyncio.to_thread(q.q.join)
            old.result = {"marker": "old"}
            new = q.submit(MINT, 999999960000, 1000001160000)          # той самий id → новий об'єкт
            await asyncio.to_thread(q.q.join)
            self.assertIsNot(old, new)
            self.assertIs(q.jobs[new.id], new)
            self.assertFalse(q._current(old))
            self.assertTrue(q._current(new))
            new.result = {"marker": "fresh"}
            q._save(new)
            q._current(old) and q._save(old)                            # застаріле збереження не відбувається
            with open(f"{self.tmp.name}/web/{new.id}.json") as f:
                self.assertEqual(json.load(f)["result"]["marker"], "fresh")

        async def test_home_groups_by_token_and_token_page_lists_its_analyses(self):
            # головна = один рядок на токен; сторінка токена показує його готові діапазони з сервера
            await self.client.get(f"/token?mint={MINT}")
            for a, b in (("2001-09-09T01:46", "2001-09-09T02:06"), ("2001-09-09T02:20", "2001-09-09T02:40")):
                await self.client.post("/analyze", data={"mint": MINT, "from": a, "to": b}, allow_redirects=False)
            await asyncio.to_thread(self.app["jobs"].q.join)
            html = await (await self.client.get("/")).text()
            self.assertIn(f'href="/token?mint={MINT}"', html)              # рядок веде на токен, не на прогін
            self.assertIn("2 ranges", html)
            self.assertEqual(html.count('class="rrow'), 1)                 # один токен — один рядок
            import re as _re, json as _json, html as _html
            page = await (await self.client.get(f"/token?mint={MINT}")).text()
            rows = _json.loads(_html.unescape(_re.search(r"data-rows='([^']*)'", page).group(1)))
            analysed = [r for r in rows if r.get("job")]
            self.assertEqual(len(analysed), 2)                             # обидва аналізи видно без пам'яті браузера
            self.assertEqual({r["from"] for r in analysed}, {"2001-09-09T01:46", "2001-09-09T02:20"})

        def _seed_one_demo(self):
            import os
            jid, a, b = "AAAAAA_20010909-0146_0206", 999999960000, 1000001160000
            result = {"info": {"mint": MINT, "symbol": "TST", "supply": 1000000, "created_time": 999996400000},
                      "window": {"from": a, "to": b, "end": b + 3600000}, "mode": "wallet-trades",
                      "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1, "dust": 0, "late": 0, "pre_range_only": 0,
                                 "lookups": 1, "entry_only": 0},
                      "coverage": {"exits_known": 1, "total": 1, "mode": "wallet-trades", "cost_full": 5,
                                   "lookup_cap": 500, "plan": "free"},
                      "wallet_trades": {"A": {"trades": [[a + 1000, "buy", 100.0, 100.0, 1.0]], "source": "wallet-trades"}},
                      "price_at_end": 3.0, "fresh_wallets": [], "scope": "all", "rows": [], "summary": {},
                      "requests": 0, "pages_fetched": 0,
                      "enrich": {"done": 0, "total": 0, "fresh": 0, "failed": 0, "funders_done": 0}}
            os.makedirs(self.tmp.name + "/demo", exist_ok=True)
            with open(f"{self.tmp.name}/demo/{MINT}.json", "w") as f:
                json.dump({"mint": MINT, "info": result["info"], "created": 999996400000, "captured_ms": 1,
                           "candles": {"1m": []}, "hints": [],
                           "ranges": [{"label": "Pump 1", "from": a, "to": b, "job": jid, "log": ["x"], "result": result}]}, f)
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:                      # сам аналіз теж має бути на диску
                json.dump({"id": jid, "mint": MINT, "t_from": a, "t_to": b, "t_exit": None, "status": "done",
                           "error": None, "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "TST",
                           "progress": {"phase": "done", "done": 1, "total": 1}, "log": ["x"], "result": result}, f)
            self.app["jobs"]._load()
            self.app["s"]["demo_job"] = jid; self.app.pop("demo", None)
            return jid, a, b

        async def test_guests_get_the_demo_wallets_get_live_mode(self):
            # без гаманця відкрите все, що не запускає прогін: сторінки, демо, готові результати, графік будь-якого токена;
            # новий живий прогін просить гаманець на кроці Analyze і не губить межі
            jid, a, b = self._seed_one_demo()
            other = "B" * 40
            before = self.st.requests
            for path in ("/", "/docs", "/docs/project", f"/token?mint={MINT}", f"/job/{jid}", f"/job/{jid}.csv", "/me"):
                r = await self.client.get(path, allow_redirects=False, headers=GUEST)
                self.assertEqual(r.status, 200, path)
            r = await self.client.get("/project", allow_redirects=False, headers=GUEST)
            self.assertEqual((r.status, r.headers["Location"]), (302, "/docs/project"))   # стара адреса сторінки проєкту жива
            self.assertEqual(self.st.requests, before)                  # сторінки й демо — без запитів
            r = await self.client.get(f"/token?mint={other}", headers=GUEST)
            html = await r.text()
            self.assertEqual(r.status, 200)                             # гість бачить голий графік і ставить межі
            self.assertIn("Find the pump", html)
            self.assertIn('id="add"', html)
            self.assertIn('data-acct="0"', html)
            self.assertIn("Analyze needs a connected wallet", html)
            self.assertIn("&#34;label&#34;: &#34;Range 1&#34;, &#34;from&#34;: &#34;&#34;", html)   # жодного готового діапазону
            self.assertIsNone(CYRILLIC.search(html))
            spent = self.st.requests - before
            self.assertGreater(spent, 0)                                # огляд живого токена коштує запитів…
            self.assertEqual(self.app["browse_daily"].left("global", 300), 300 - spent)   # …і вони списані з добового бюджету
            r = await self.client.get(f"/candles.json?mint={other}&tf=1h&a=1&b=9999999999", headers=GUEST)
            self.assertEqual(r.status, 200)
            self.assertIsInstance(await r.json(), list)
            r = await self.client.post("/analyze", allow_redirects=False, headers=dict(GUEST, **self.same_site), data={
                "mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)})
            self.assertTrue(r.headers["Location"].startswith(f"/job/{jid}_r"), r.headers["Location"])      # демо програється без гаманця
            r = await self.client.post("/analyze", allow_redirects=False, headers=GUEST, data={
                "mint": other, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})
            html = await r.text()
            self.assertEqual(r.status, 401)                             # новий живий прогін — лише з гаманцем…
            self.assertIn("Connect a wallet to run this analysis", html)
            self.assertIn('name="from" value="2001-09-09T01:46"', html) # …межі їдуть далі після підключення
            self.assertIn('<form id="again" method="post" action="/analyze" data-wallet-after hidden>', html)
            self.assertIn(f"/token?mint={MINT}", html)                   # і дорога до демо
            self.assertIsNone(CYRILLIC.search(html))
            r = await self.client.get(f"/token?mint={other}")           # той самий запит з гаманцем — без підказки
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn('data-acct="1"', html)
            self.assertNotIn("Analyze needs a connected wallet", html)

        async def test_chart_budget_caps_spending_not_cached_pages_or_admins(self):
            # графік живого токена коштує запитів: гість має добову стелю на адресу, гаманець — свою, сайт — спільну;
            # закешований токен відкривається і при нульовому залишку; адмін поза стелею; готовий результат — гостю без гаманця
            other, third, fourth = "B" * 40, "C" * 40, "D" * 40
            r = await self.client.get(f"/token?mint={other}", headers=GUEST)      # перший огляд — за запити
            self.assertEqual(r.status, 200)
            self.app["s"]["browse_per_day_guest"] = 0
            r = await self.client.get(f"/token?mint={other}", headers=GUEST)      # той самий токен з кешу — безкоштовно
            self.assertEqual(r.status, 200)
            r = await self.client.get(f"/token?mint={third}", headers=GUEST)      # новий токен — стеля
            self.assertEqual(r.status, 429)
            self.assertIn("Connect a wallet", await r.text())
            r = await self.client.get(f"/candles.json?mint={third}&tf=1h&a=1&b=9999999999", headers=GUEST)
            self.assertEqual(r.status, 429)
            self.assertIn("Connect a wallet", (await r.json())["error"])
            w = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x09" * 32))}
            r = await self.client.get(f"/token?mint={third}", headers=w)          # гаманець має свою стелю
            self.assertEqual(r.status, 200)
            self.app["s"]["browse_global_per_day"] = 0
            r = await self.client.get(f"/token?mint={fourth}", headers=w)
            self.assertEqual(r.status, 429)
            self.assertIn("tomorrow", await r.text())
            r = await self.client.get(f"/token?mint={fourth}")                    # адмін (клієнт за замовчуванням) — поза стелею
            self.assertEqual(r.status, 200)
            self.app["s"]["browse_global_per_day"], self.app["s"]["browse_per_day_guest"] = 300, 30
            rng = {"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"}
            r = await self.client.post("/analyze", data=rng, allow_redirects=False)  # адмін запускає живий прогін
            self.assertEqual(r.status, 302, await r.text())
            jid = r.headers["Location"].split("/")[-1]
            await asyncio.to_thread(self.app["jobs"].q.join)
            self.assertEqual(self.app["jobs"].get(jid).status, "done", self.app["jobs"].get(jid).error)
            r = await self.client.post("/analyze", data=rng, allow_redirects=False, headers=GUEST)
            self.assertEqual(r.status, 302)                                        # готовий результат відкривається гостю
            self.assertEqual(r.headers["Location"], f"/job/{jid}")

        async def test_wallet_trades_are_gated_and_charged(self):
            # per-wallet result: only wallets of the analysis can be fetched; a paid lookup needs a wallet and pays from the chart budget
            jid, mint = "CCCCCC_20010909-0146_0206", "C" * 40
            listed, unlisted = acct_mod.b58encode(b"\x01" * 32), acct_mod.b58encode(b"\x02" * 32)
            stored = {"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done", "error": None,
                      "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "CCC", "progress": {"phase": "done", "done": 1, "total": 1}, "log": [],
                      "result": {"info": {"mint": mint, "symbol": "CCC", "supply": 1000000, "created_time": 999996400000},
                                 "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                                 "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1}, "coverage": {"exits_known": 0, "total": 1, "mode": "wallet-trades"},
                                 "wallet_trades": {}, "rows": [{"wallet": listed}], "scope": "all", "requests": 0}}
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump(stored, f)
            self.app["jobs"]._load()
            before = self.st.requests
            r = await self.client.get(f"/wallet_trades.json?job={jid}&wallet={unlisted}")
            self.assertEqual(r.status, 404)                             # чужа адреса — жодного запиту
            self.assertEqual(self.st.requests, before)
            r = await self.client.get(f"/wallet_trades.json?job={jid}&wallet={listed}", headers=GUEST)
            self.assertEqual(r.status, 401)                             # гість не купує угоди
            self.assertIn("load this wallet", (await r.json())["error"])
            self.app["admins"] = set()
            r = await self.client.get(f"/wallet_trades.json?job={jid}&wallet={listed}")
            self.assertEqual(r.status, 200, await r.text())
            spent = self.st.requests - before
            self.assertGreater(spent, 0)
            self.assertEqual(self.app["browse_daily"].left("global", 300), 300 - spent)   # оплачено з бюджету
            self.app["admins"] = {TEST_PK}

        async def test_wallet_profile_is_gated_charged_and_cached(self):
            # картка гаманця: лише гаманці аналізу; новий профіль — з гаманцем і з бюджету; з кешу — будь-кому і безкоштовно
            jid, mint = "EEEEEE_20010909-0146_0206", "E" * 40
            listed, unlisted = acct_mod.b58encode(b"\x05" * 32), acct_mod.b58encode(b"\x06" * 32)
            stored = {"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done", "error": None,
                      "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "EEE", "progress": {"phase": "done", "done": 1, "total": 1}, "log": [],
                      "result": {"info": {"mint": mint, "symbol": "EEE", "supply": 1000000, "created_time": 999996400000},
                                 "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                                 "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1}, "coverage": {"exits_known": 0, "total": 1, "mode": "wallet-trades"},
                                 "wallet_trades": {}, "rows": [{"wallet": listed}], "scope": "all", "requests": 0}}
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump(stored, f)
            self.app["jobs"]._load()
            before = self.st.requests
            r = await self.client.get(f"/wallet_profile.json?job={jid}&wallet={unlisted}")
            self.assertEqual(r.status, 404)                             # чужа адреса — жодного запиту
            r = await self.client.get(f"/wallet_profile.json?job={jid}&wallet={listed}", headers=GUEST)
            self.assertEqual(r.status, 401)                             # гість не купує профіль
            self.assertIn("last 30 days", (await r.json())["error"])
            self.assertEqual(self.st.requests, before)
            self.app["admins"] = set()
            left0 = self.app["browse_daily"].left("global", 300)
            r = await self.client.get(f"/wallet_profile.json?job={jid}&wallet={listed}")
            self.assertEqual(r.status, 200, await r.text())
            d = await r.json()
            self.assertAlmostEqual(d["pnl_usd"], 50.0)
            self.assertEqual((d["closed"], d["wins"], d["tokens"]), (1, 1, 1))
            self.assertEqual(self.st.requests - before, 1)
            self.assertEqual(self.app["browse_daily"].left("global", 300), left0 - 1)   # оплачено з бюджету, резерв повернуто
            r = await self.client.get(f"/wallet_profile.json?job={jid}&wallet={listed}", headers=GUEST)
            self.assertEqual(r.status, 200)                             # з кешу — навіть гостю
            self.assertEqual(self.st.requests - before, 1)              # і без другого запиту
            self.app["admins"] = {TEST_PK}

        async def test_live_runs_wait_when_the_month_is_nearly_spent(self):
            # місяць: запуск можливий, лише поки найгірший прогін лишає резерв; день людини при відмові не згорає
            s = self.app["s"]
            s.update(credits_month=10_000, credits_reserve_pct=5, run_cap_requests=300)      # резерв 500
            self.app["admins"] = set()
            calls = []
            real = self.st.credits
            self.st.credits = lambda: (calls.append(1), real())[1]
            self.st._credits = 700                                   # 700 − 300 < 500 → чекаємо
            rng = {"mint": "G" * 40, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"}
            r = await self.client.post("/analyze", data=rng, allow_redirects=False)
            self.assertEqual(r.status, 503, await r.text())
            self.assertIn("data budget is nearly used up", await r.text())
            r = await self.client.post("/analyze", data=rng, allow_redirects=False)
            self.assertEqual(r.status, 503)
            self.assertEqual(len(calls), 1)                          # залишок питали раз, не на кожен клік
            self.st._credits = 50_000
            self.app["credits"].update(at=0)                         # минуло 10 хвилин
            r = await self.client.post("/analyze", data=rng, allow_redirects=False)
            self.assertEqual(r.status, 302, await r.text())          # запас є — і день не був витрачений відмовою
            await asyncio.to_thread(self.app["jobs"].q.join)         # запущений аналіз робить свої запити: чекаємо його
            before = self.st.requests
            h = await (await self.client.get("/health")).json()
            self.assertEqual(h["credits"], 50_000)
            self.assertEqual(self.st.requests, before)               # /health не питає Solana Tracker
            self.app["admins"] = {TEST_PK}
            s.update(credits_month=0, credits_reserve_pct=0)

        async def test_only_the_owner_makes_a_finished_analysis_the_demo(self):
            rng = {"mint": "H" * 40, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"}
            r = await self.client.post("/analyze", data=rng, allow_redirects=False)
            jid = r.headers["Location"].rsplit("/", 1)[-1]
            await asyncio.to_thread(self.app["jobs"].q.join)
            origin = {"Origin": f"http://{self.client.host}:{self.client.port}"}
            other = acct_mod.b58encode(b"\x0b" * 32)
            r = await self.client.post("/admin/demo", json={"job": jid}, headers=dict(origin, Cookie=wallet_cookie(other)))
            self.assertEqual(r.status, 403)                              # не власник — не вибирає демо
            r = await self.client.post("/admin/demo", json={"job": jid}, headers=origin)
            self.assertEqual(r.status, 200, await r.text())
            self.assertEqual((await r.json())["job"], jid)
            html = await (await self.client.get(f"/token?mint={'H' * 40}")).text()
            self.assertIn('class="chip demo"', html)                     # токен тепер демо і програється зі знімка
            before = self.st.requests
            await self.client.get(f"/candles.json?mint={'H' * 40}&tf=1m&a=999999900&b=1000002000")
            self.assertEqual(self.st.requests, before)                    # свічки демо — зі знімка, без запитів

        async def test_enrich_json_carries_ages_and_identities(self):
            jid, mint = "FFFFFF_20010909-0146_0206", "F" * 40
            w = acct_mod.b58encode(b"\x04" * 32)
            stored = {"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done", "error": None,
                      "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "FFF", "progress": {"phase": "done", "done": 1, "total": 1}, "log": [],
                      "result": {"info": {"mint": mint, "symbol": "FFF", "supply": 1000000, "created_time": 999996400000},
                                 "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                                 "counts": {}, "coverage": {}, "wallet_trades": {}, "rows": [{"wallet": w}], "scope": "all", "requests": 0,
                                 "ages": {w: {"ms": 999000000000, "exact": True}}, "services": ["EXCH"],
                                 "identities": {w: {"name": "Cented", "twitter": "@Cented7", "type": "kol"}}}}
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump(stored, f)
            self.app["jobs"]._load()
            d = await (await self.client.get(f"/job/{jid}.enrich.json")).json()
            self.assertEqual(d["ages"][w]["ms"], 999000000000)
            self.assertEqual(d["identities"][w]["twitter"], "@Cented7")
            self.assertEqual((d["n_ages"], d["services"]), (1, ["EXCH"]))     # біржі йдуть разом зі спонсорами
            # наступне опитування несе лише нове: вік уже є, імена вже є
            d = await (await self.client.get(f"/job/{jid}.enrich.json?f=0&a=1&i=1")).json()
            self.assertEqual(d["ages"], {})
            self.assertNotIn("identities", d)
            d = await (await self.client.get(f"/job/{jid}.enrich.json?a=5")).json()
            self.assertEqual(d["ages"][w]["ms"], 999000000000)            # сторінка знає більше, ніж є: усе заново

        async def test_analyze_charges_the_overview_and_validates_before_asking_for_a_wallet(self):
            # гість з хибними межами дізнається про це до підключення; огляд токена оплачений; кешований огляд безкоштовний
            other = "D" * 40
            before, left0 = self.st.requests, self.app["browse_daily"].left("global", 300)
            r = await self.client.post("/analyze", allow_redirects=False, headers=GUEST,
                                       data={"mint": other, "from": "2001-09-09T02:06", "to": "2001-09-09T01:46"})
            self.assertEqual(r.status, 400, await r.text())             # межі навпаки — помилка, а не «підключіть гаманець»
            spent = self.st.requests - before
            self.assertGreater(spent, 0)
            self.assertEqual(self.app["browse_daily"].left("global", 300), left0 - spent)
            r = await self.client.post("/analyze", allow_redirects=False, headers=GUEST,
                                       data={"mint": other, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})
            self.assertEqual(r.status, 401)                             # чинні межі — тепер просимо гаманець
            self.assertEqual(self.st.requests, before + spent)          # огляд уже в кеші

        async def test_failed_overview_is_charged_and_not_bought_again(self):
            bad = "E" * 40
            self.st.fail_mints = {bad}
            before, left0 = self.st.requests, self.app["browse_daily"].left("global", 300)
            r = await self.client.get(f"/token?mint={bad}", headers=GUEST)
            self.assertEqual(r.status, 400)
            self.assertEqual(self.st.requests - before, 1)              # token_info пішов у мережу і впав…
            self.assertEqual(self.app["browse_daily"].left("global", 300), left0 - 1)   # …і оплачений: резерв 2 виправлено на 1
            r = await self.client.get(f"/token?mint={bad}", headers=GUEST)
            self.assertEqual(r.status, 400)
            self.assertEqual(self.st.requests, before + 1)              # невдача закешована: вдруге безкоштовно
            self.st.fail_mints = ()

        async def test_site_wide_run_cap_and_refund_on_failure(self):
            self.app["admins"] = set()
            self.app["s"]["runs_global_per_day"] = 10
            pk2 = acct_mod.b58encode(b"\x12" * 32)
            w1, w2, w3 = ({"Cookie": wallet_cookie(acct_mod.b58encode(bytes([b]) * 32))} for b in (0x11, 0x12, 0x13))
            rng = lambda h: {"mint": MINT, "from": f"2001-09-09T{h}", "to": "2001-09-09T02:06"}  # noqa: E731
            self.st.fail_trades = True                                  # перший прогін падає до витрат
            r = await self.client.post("/analyze", data=rng("01:50"), allow_redirects=False, headers=w2)
            self.assertEqual(r.status, 302, await r.text())
            await asyncio.to_thread(self.app["jobs"].q.join)
            j = self.app["jobs"].get(r.headers["Location"].split("/")[-1])
            self.assertEqual(j.status, "error", j.error)
            self.assertEqual((self.app["accounts"].load(pk2).get("runs") or {}).get("n"), 0)   # день повернуто
            self.st.fail_trades = False
            r = await self.client.post("/analyze", data=rng("01:50"), allow_redirects=False, headers=w2)
            self.assertEqual(r.status, 302, await r.text())             # той самий гаманець того ж дня — можна
            await asyncio.to_thread(self.app["jobs"].q.join)
            self.assertEqual(self.app["jobs"].get(r.headers["Location"].split("/")[-1]).status, "done")
            self.app["s"]["runs_global_per_day"] = 2
            r = await self.client.post("/analyze", data=rng("01:46"), allow_redirects=False, headers=w1)
            self.assertEqual(r.status, 302, await r.text())
            await asyncio.to_thread(self.app["jobs"].q.join)
            r = await self.client.post("/analyze", data=rng("01:52"), allow_redirects=False, headers=w3)
            self.assertIn("notice=sitecap", r.headers["Location"])      # стеля сайту на добу: назад до діапазону з вікном
            self.assertIn("whole site", await (await self.client.get(r.headers["Location"], headers=w3)).text())
            self.app["s"]["runs_global_per_day"] = 10
            self.app["admins"] = {TEST_PK}

        async def test_one_person_gets_one_days_runs_whichever_wallet(self):
            # правило власника: п'ять на людину; інший гаманець у тому ж браузері нових спроб не дає, новий браузер
            # з тієї ж мережі впирається в стелю мережі, а сторінка каже це вікном, не сторінкою помилки
            from tracced.web.app import _ip_key
            self.app["admins"] = set()
            s = self.app["s"]
            s["runs_per_day"], s["runs_per_ip_per_day"] = 2, 3
            starts = ["01:46", "01:50", "01:52", "01:54"]                  # діапазони, для яких у фейку є угоди
            a, b, c = (acct_mod.b58encode(bytes([x]) * 32) for x in (0x21, 0x22, 0x23))

            async def run(pk, i, dev=None):
                cookie = wallet_cookie(pk) + (f"; early_dev={dev}" if dev else "")
                return await self.client.post("/analyze", allow_redirects=False, headers={"Cookie": cookie},
                                              data={"mint": MINT, "from": f"2001-09-09T{starts[i]}", "to": "2001-09-09T02:06"})
            r = await run(a, 0)
            self.assertTrue(r.headers["Location"].startswith("/job/"), await r.text())
            dev = r.cookies["early_dev"].value                             # браузер отримує своє число з першим аналізом
            self.assertRegex(dev, "^[0-9a-f]{32}$")
            r = await run(a, 1, dev)
            self.assertTrue(r.headers["Location"].startswith("/job/"))
            r = await run(a, 2, dev)
            self.assertIn("notice=limit", r.headers["Location"])           # два гаманця витрачено
            self.assertIn("from=2001-09-09T01:52", r.headers["Location"])   # діапазон повертається разом із вікном
            r = await run(b, 2, dev)
            self.assertIn("notice=limit", r.headers["Location"])           # інший гаманець у тому ж браузері: нічого нового
            r = await run(b, 2)                                             # новий браузер з тієї ж мережі: ще один…
            self.assertTrue(r.headers["Location"].startswith("/job/"), r.headers["Location"])
            r = await run(c, 3)
            self.assertIn("notice=netcap", r.headers["Location"])          # …і три мережі витрачено: c свої ще має, вікно — про мережу
            html = await (await self.client.get(r.headers["Location"], headers={"Cookie": wallet_cookie(c)})).text()
            self.assertIn('id="limitsheet"', html)
            self.assertIn("openLimit('netcap')", html)
            self.assertIn("Your range", html)                               # позначений діапазон на місці
            self.assertIsNone(r.cookies.get("early_dev"))                   # відмова нічого не ставить і не рахує
            self.assertEqual(self.app["runs_daily"].left(_ip_key("127.0.0.1"), 3), 0)
            html = await (await self.client.get(f"/token?mint={MINT}", headers={"Cookie": wallet_cookie(a) + f"; early_dev={dev}"})).text()
            self.assertIn("You've used your 2 free analyses for today", html)   # вікно чекає на Analyze і без повідомлення
            self.assertIn("No free analyses left today", html)
            await asyncio.to_thread(self.app["jobs"].q.join)
            s["runs_per_day"], s["runs_per_ip_per_day"] = 1, 10
            self.app["admins"] = {TEST_PK}

        async def test_analytics_counts_only_on_the_live_domains_and_never_names_the_wallet(self):
            from unittest import mock
            with mock.patch.dict(os.environ, {"UMAMI_WEBSITE_ID": "site-id", "UMAMI_DOMAINS": "tracced.xyz"}):
                html = await (await self.client.get("/")).text()
                guest = await (await self.client.get("/", headers=GUEST)).text()
            self.assertIn('data-website-id="site-id" data-domains="tracced.xyz" data-performance="true" data-tag="wallet"', html)
            self.assertIn('data-tag="guest"', guest)                       # сегмент без адреси: гаманець чи гість
            self.assertNotIn(TEST_PK, html.split("umami.is/script.js")[1].split("</script>")[0])
            with mock.patch.dict(os.environ, {"UMAMI_WEBSITE_ID": ""}):
                self.assertNotIn("umami.is", await (await self.client.get("/")).text())   # без id — жодного скрипта

        async def test_the_network_window_and_export_for_a_signed_in_person(self):
            # Export у підписаного не мовчить: панель експорту шукається за своїм id, а не першим меню на сторінці (меню акаунта)
            await self.client.get(f"/token?mint={MINT}")
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"},
                                       allow_redirects=False)
            loc, html = r.headers["Location"], ""
            for _ in range(80):
                html = await (await self.client.get(loc)).text()
                if "↓ Export" in html: break
                await asyncio.sleep(0.1)
            self.assertIn('id="xpanel"', html)
            self.assertIn("getElementById('xpanel')", html)
            self.assertNotIn("querySelector('.menu-panel')", html)
            # мережа вичерпала свою стелю: вікно каже саме це, а не «ви використали свої п'ять»
            self.app["admins"] = set()
            self.app["s"]["runs_per_ip_per_day"] = 0
            html = await (await self.client.get(f"/token?mint={MINT}&notice=netcap")).text()
            self.assertIn("Your network has used today's 0 free analyses", html)
            self.assertNotIn("Come back tomorrow", html)
            self.app["s"]["runs_per_ip_per_day"] = 10
            html = await (await self.client.get(f"/token?mint={MINT}&notice=limit")).text()
            self.assertNotIn('id="limitsheet"', html)                        # спроби є: старе повідомлення в адресі вікна не відкриває
            self.app["admins"] = {TEST_PK}

        async def test_a_failed_run_gives_the_browser_and_the_network_their_run_back(self):
            from tracced.web.app import _ip_key
            self.app["admins"] = set()
            pk = acct_mod.b58encode(b"\x24" * 32)
            self.st.fail_trades = True
            r = await self.client.post("/analyze", allow_redirects=False, headers={"Cookie": wallet_cookie(pk)},
                                       data={"mint": MINT, "from": "2001-09-09T01:50", "to": "2001-09-09T02:06"})
            dev = r.cookies["early_dev"].value
            await asyncio.to_thread(self.app["jobs"].q.join)
            self.st.fail_trades = False
            self.assertEqual(self.app["jobs"].get(r.headers["Location"].split("/")[-1]).status, "error")
            self.assertEqual(self.app["runs_daily"].left("dev:" + dev, 5), 5)
            self.assertEqual(self.app["runs_daily"].left(_ip_key("127.0.0.1"), 10), 10)
            self.assertEqual(self.app["accounts"].runs_today(pk), 0)
            self.app["admins"] = {TEST_PK}

        async def test_demo_replay_keeps_the_stored_analysis_in_place(self):
            jid, a, b = self._seed_one_demo()
            r = await self.client.post("/analyze", allow_redirects=False, headers=dict(GUEST, **self.same_site),
                                       data={"mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)})
            rid = r.headers["Location"].split("/")[-1]
            self.assertTrue(rid.startswith(jid + "_r") and rid != jid, rid)
            self.assertEqual(self.app["jobs"].get(jid).status, "done")   # збережений аналіз нікуди не дівся…
            r = await self.client.get(f"/job/{jid}.csv", headers=GUEST)
            self.assertEqual(r.status, 200)                              # …і читається, поки демо програється
            await asyncio.to_thread(self.app["jobs"].rq.join)
            d = await (await self.client.get(f"/job/{rid}.state.json", headers=GUEST)).json()
            self.assertEqual((d["status"], d.get("open")), ("done", f"/job/{jid}"))   # термінал відкриє збережений результат
            r = await self.client.get(f"/job/{rid}", headers=GUEST)
            self.assertEqual(r.status, 200)
            self.assertIn(f'id="facts" data-id="{jid}"', await r.text())   # збереження й експорт — під сталим id
            r = await self.client.get(f"/job/{jid}_r0a0b0c", headers=GUEST, allow_redirects=False)   # a replay id from before a restart
            self.assertEqual((r.status, r.headers["Location"]), (302, f"/job/{jid}"))
            self.assertNotIn(rid, [j.id for j in self.app["jobs"].recent(50)])   # у списках лише справжні аналізи

        async def test_404_pages_and_client_ip(self):
            r = await self.client.get("/job/nope", headers=GUEST)
            self.assertEqual(r.status, 404)
            self.assertIn("That didn't work", await r.text())            # брендована сторінка, не голий текст
            r = await self.client.get("/no-such-page", headers=GUEST)
            self.assertEqual(r.status, 404)
            self.assertIn("<footer", await r.text())
            from aiohttp.test_utils import make_mocked_request
            from tracced.web.app import _client_ip
            self.assertEqual(_client_ip(make_mocked_request("GET", "/", headers={"X-Forwarded-For": "2001:db8:abcd:1234:5:6:7:8"})), "2001:db8:abcd:1234::/64")
            self.assertEqual(_client_ip(make_mocked_request("GET", "/", headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})), "10.0.0.1")
            r = await self.client.get("/candles.json?mint=" + "B" * 40 + "&tf=1h&a=inf&b=1", headers=GUEST)
            self.assertEqual(r.status, 400)                              # inf — помилка запиту, не 500
            self.assertIn("Bad time range", (await r.json())["error"])

        async def test_docs_pages(self):
            # документація живе в репозиторії поруч з кодом і їде тим самим деплоєм
            r = await self.client.get("/docs", headers=GUEST)
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn(">Overview</h1>", html)
            self.assertIn('class="docs-nav"', html)
            self.assertIn('class="docs-pager"', html)                         # читається підряд, як книжка
            self.assertIsNone(CYRILLIC.search(html))
            for slug in ("tags", "limits", "account", "roadmap", "how-it-works", "compare"):
                rr = await self.client.get(f"/docs/{slug}", headers=GUEST)
                body = await rr.text()
                self.assertEqual(rr.status, 200, slug)
                self.assertIn(f'/docs/{slug}" class="on"', body)              # свій пункт меню підсвічений
                self.assertIsNone(CYRILLIC.search(body), slug)
                self.assertNotIn("<h1>Tags and what", body)                   # заголовки короткі, не речення
            first = await (await self.client.get("/docs/how-it-works", headers=GUEST)).text()
            self.assertIn('href="/docs/index"', first)                        # кнопка «назад» на попередню сторінку
            self.assertIn('href="/docs/tags"', first)                         # і «далі» на наступну
            self.assertIn("no-exits", await (await self.client.get("/docs/tags", headers=GUEST)).text())
            cmp_ = await (await self.client.get("/docs/compare", headers=GUEST)).text()
            self.assertIn('<div class="dtw"><table class="cmp">', cmp_)      # таблиця з класом теж загорнута і прокручується
            self.assertIn('<td class="us">', cmp_)
            r = await self.client.get("/docs/../config", headers=GUEST, allow_redirects=False)
            self.assertIn(r.status, (301, 404))                               # шлях не виводить за межі списку сторінок
            r = await self.client.get("/docs/journal", headers=GUEST)
            self.assertEqual(r.status, 404)                                   # приватних нотаток у меню нема і бути не може
            self.assertIn('href="/docs"', await (await self.client.get("/", headers=GUEST)).text())

        async def test_crossings_only_count_my_own_saved_analyses(self):
            # ⛓ означає «цей гаманець був раннім ще в стількох аналізах, які зберіг САМЕ ти» — чужі не рахуються
            import os
            from tracced.web.jobs import Job
            base = json.load(open(f"{self.tmp.name}/web/{DEMO_JID}.json")) if os.path.exists(f"{self.tmp.name}/web/{DEMO_JID}.json") else None
            mk = lambda jid, mint, t_from, wallets: {  # noqa: E731
                "id": jid, "mint": mint, "t_from": t_from, "t_to": t_from + 600000, "t_exit": None, "status": "done",
                "error": None, "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "TST",
                "progress": {"phase": "done", "done": 1, "total": 1}, "log": [],
                "result": {"info": {"mint": mint, "symbol": "TST", "supply": 1000000}, "mode": "trades",
                           "window": {"from": t_from, "to": t_from + 600000, "end": t_from + 999999},
                           "counts": {}, "coverage": {}, "wallet_trades": {},
                           "rows": [{"wallet": w, "multiple": 2.0, "realized_usd": 10.0} for w in wallets]}}
            a = mk("AAAAAA_20010909-0100_0110", "A" * 40, 999999900000, ["w1", "w2", "w3"])
            b = mk("BBBBBB_20010909-0200_0210", "B" * 40, 999999900000 + 3600000, ["w2", "w3", "w9"])
            c = mk("CCCCCC_20010909-0300_0310", "C" * 40, 999999900000 + 7200000, ["w3", "w7"])
            for j in (a, b, c):
                self.app["jobs"].jobs[j["id"]] = Job.from_dict(j)
            o = {"Origin": f"http://{self.client.host}:{self.client.port}"}
            r = await self.client.get(f"/job/{a['id']}/crossings.json", headers=GUEST)
            self.assertEqual(r.status, 401)                                  # без гаманця перетинати нічого
            r = await self.client.get(f"/job/{a['id']}/crossings.json")
            d = await r.json()
            self.assertEqual((d["saved"], d["n"]), (0, 0))                   # нічого не збережено — порожньо
            for jid in (b["id"], c["id"]):
                rr = await self.client.post("/me/analyses", json={"job": jid}, headers=o)
                self.assertEqual(rr.status, 200, await rr.text())
            d = await (await self.client.get(f"/job/{a['id']}/crossings.json")).json()
            self.assertEqual(d["saved"], 2)
            self.assertEqual(sorted(d["wallets"]), ["w2", "w3"])             # w1 лише тут, w9 і w7 не в цьому аналізі
            self.assertEqual(len(d["wallets"]["w3"]), 2)                     # w3 є в обох збережених
            self.assertEqual(len(d["wallets"]["w2"]), 1)
            self.assertEqual({x["symbol"] for x in d["wallets"]["w3"]}, {"TST"})
            self.assertEqual({x["job"] for x in d["wallets"]["w3"]}, {b["id"], c["id"]})
            self.assertAlmostEqual(d["wallets"]["w2"][0]["mult"], 2.0)

        async def test_candles_span_is_capped_per_timeframe(self):
            # завеликий відрізок джерело мовчки обрізає і віддає лише свіже, тому звужуємо його самі
            from tracced.web import chart as chart_mod
            from tracced.web.app import MAX_CANDLES
            mint, asked = "F" * 40, []
            await self.client.get(f"/candles.json?mint={mint}&tf=5m&a=1&b=2")    # огляд токена в кеш, щоб не рахувати його свічку
            real = self.st.chart

            def spy(m, interval, t_from, t_to):
                asked.append((interval, (t_to - t_from) // 1000))
                return real(m, interval, t_from, t_to)
            self.st.chart = spy
            try:
                for tf in ("1m", "1h"):
                    r = await self.client.get(f"/candles.json?mint={mint}&tf={tf}&a=1&b=9999999999")
                    self.assertEqual(r.status, 200, await r.text())
            finally:
                self.st.chart = real
            self.assertEqual([t for t, _ in asked], ["1m", "1h"])
            for tf, span in asked:
                self.assertLessEqual(span / chart_mod.TF_SEC[tf], MAX_CANDLES + 1, tf)   # свічок за запит не більше стелі
                self.assertGreater(span, 0, tf)

        async def test_live_mode_quota_cap_and_delete(self):
            # гаманець: 1 прогін на день; той самий діапазон удруге — безкоштовно; 3 діапазони на токен; видалити може автор або адмін
            import time as _time
            from tracced.web.jobs import make_id
            self.app["admins"] = set()
            self.app["s"]["ranges_per_token"] = 3
            other_pk = acct_mod.b58encode(b"\x08" * 32)
            me, other = {"Cookie": wallet_cookie(TEST_PK), "Origin": f"http://{self.client.host}:{self.client.port}"}, \
                        {"Cookie": wallet_cookie(other_pk), "Origin": f"http://{self.client.host}:{self.client.port}"}
            starts = {1: "01:46", 2: "01:50", 3: "01:52", 4: "01:54"}                       # ranges the fake feed has trades for
            rng = lambda h: {"mint": MINT, "from": f"2001-09-09T{starts[h]}", "to": "2001-09-09T02:06"}   # noqa: E731
            r = await self.client.post("/analyze", data=rng(1), allow_redirects=False, headers=me)
            self.assertEqual(r.status, 302, await r.text())
            jid1 = r.headers["Location"].split("/")[-1]
            self.assertEqual(jid1, make_id(MINT, chart.from_input(rng(1)["from"]), chart.from_input(rng(1)["to"])))
            await asyncio.to_thread(self.app["jobs"].q.join)
            self.assertEqual(self.app["jobs"].get(jid1).status, "done", self.app["jobs"].get(jid1).error)
            self.assertEqual(self.app["jobs"].get(jid1).owner, TEST_PK)
            self.assertEqual(self.app["jobs"].get(jid1).s_over, {"budget_guard_pct": 0, "run_cap_requests": 2000})
            r = await self.client.post("/analyze", data=rng(2), allow_redirects=False, headers=me)
            self.assertIn("notice=limit", r.headers["Location"])         # друга за день — ні: назад до діапазону з вікном
            body = await (await self.client.get(r.headers["Location"], headers=me)).text()
            self.assertIn("free analyses for today", body)
            self.assertIn("limits are small", body)                      # і пояснення, що це рання стадія
            r = await self.client.post("/analyze", data=rng(1), allow_redirects=False, headers=me)
            self.assertEqual(r.headers["Location"], f"/job/{jid1}")     # готовий результат відкривається без витрат
            self.app["admins"] = {TEST_PK}                               # адмін: без квоти і без стелі запитів
            for h in (2, 3):
                r = await self.client.post("/analyze", data=rng(h), allow_redirects=False, headers=me)
                self.assertEqual(r.status, 302, await r.text())
                await asyncio.to_thread(self.app["jobs"].q.join)
                j = self.app["jobs"].get(r.headers["Location"].split("/")[-1])
                self.assertEqual(j.status, "done", j.error)
            self.assertEqual(self.app["jobs"].get(r.headers["Location"].split("/")[-1]).s_over, {"budget_guard_pct": 0, "run_cap_requests": 0})
            r = await self.client.post("/analyze", data=rng(4), allow_redirects=False, headers=me)
            self.assertEqual(r.status, 400)
            self.assertIn("already has 3 analyses", await r.text())     # стеля на токен — і для адміна
            r = await self.client.post(f"/job/{jid1}/delete", headers=other)
            self.assertEqual(r.status, 403)                              # чужий аналіз не видалиш
            r = await self.client.post(f"/job/{jid1}/delete", headers={"Cookie": wallet_cookie(other_pk)})
            self.assertEqual(r.status, 403)                              # і без Origin теж
            r = await self.client.post(f"/job/{jid1}/delete", headers=me)
            self.assertTrue((await r.json())["ok"])
            self.assertIsNone(self.app["jobs"].get(jid1))
            self.assertFalse(os.path.exists(f"{self.tmp.name}/web/{jid1}.json"))
            r = await self.client.post("/analyze", data=rng(4), allow_redirects=False, headers=me)
            self.assertEqual(r.status, 302)                              # місце звільнилось
            html = await (await self.client.get(f"/token?mint={MINT}", headers=me)).text()
            self.assertIn("&#34;deletable&#34;: true", html)              # свої аналізи можна прибрати зі сторінки
            html = await (await self.client.get(f"/token?mint={MINT}", headers=other)).text()
            self.assertIn("&#34;deletable&#34;: false", html)
            self.assertNotIn("&#34;deletable&#34;: true", html)
            self.assertEqual(self.app["events"].tail()[0]["event"], "analyze")
            r = await self.client.post("/job/nope/delete", headers=me)
            self.assertEqual(r.status, 404)

        async def test_open_surface_cannot_be_unlocked_by_the_wrong_parameter(self):
            # кожен шлях має перевірятись по тому самому параметру, який читає його обробник
            jid, a, b = self._seed_one_demo()
            other, other_job = "B" * 40, "BBBBBB_20010909-0300_0320"
            before = self.st.requests
            for path in (f"/token?mint={other}&job={jid}", f"/candles.json?mint={other}&job={jid}&tf=1h&a=1&b=9999999999"):
                r = await self.client.get(path, allow_redirects=False, headers=GUEST)
                self.assertEqual(r.status, 200, path)
                self.assertNotIn('class="chip demo"', await r.text())    # job демо не робить чужий mint демо…
            self.assertGreater(self.st.requests, before)                 # …він живий: запити йдуть у мережу…
            self.assertLess(self.app["browse_daily"].left("global", 300), 300)   # …і списуються з бюджету на графіки
            r = await self.client.get(f"/wallet_trades.json?mint={MINT}&job={other_job}&wallet=A", headers=GUEST)
            self.assertEqual(r.status, 404)                              # чужий id — нема такого
            r = await self.client.post(f"/job/{jid}/agent/cards", json={"lang": "en"}, allow_redirects=False,
                                       headers={"Origin": f"http://{self.client.host}:{self.client.port}", "Cookie": ""})
            self.assertIn(r.status, (401, 404, 503))                     # no agent for guests, and none on this server

        async def test_how_redirects_into_the_docs(self):
            # один опис замість двох: /how вів своє життя і неминуче розійшовся б з документацією
            r = await self.client.get("/how", allow_redirects=False)
            self.assertEqual((r.status, r.headers["Location"]), (302, "/docs/how-it-works"))
            html = await (await self.client.get("/docs/tags")).text()
            self.assertIn("bot-like", html)                              # таблиця тегів будується з коду
            self.assertIn("transfer-in", html)
            self.assertIn("seen-before", html)
            self.assertIsNone(CYRILLIC.search(html))
            lim = await (await self.client.get("/docs/limits")).text()
            self.assertIn(f">{self.app['s']['max_window_hours']} hours<", lim)   # числа ті самі, що в налаштуваннях
            self.assertIn(">{:,}<".format(self.app['s']['max_wallet_lookups']), lim)

        async def test_index_english(self):
            r = await self.client.get("/")
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn('<h1 class="brandline">tracced</h1>', html)   # brand line
            self.assertIn("every wallet <em>on the record</em>", html)
            self.assertIn("tracced", html)
            self.assertNotIn('class="top"', html)                       # no top bar on the home page
            self.assertIn('data-count=', html)                          # live counters
            self.assertIn("How it works", html)                         # footer
            self.assertIn("Built on Solana", html)
            self.assertIn("every wallet on the record", html)          # footer
            self.assertNotIn("Where this is going", html)               # roadmap removed for now
            self.assertIn("Paste address", html)
            self.assertIn("Get wallets", html)
            self.assertIn("AI agent", html)
            self.assertNotIn('href="/#recent"', html)                   # no Analyses in the top bar
            self.assertNotIn("Try a sample scan", html)
            self.assertIsNone(CYRILLIC.search(html))

        async def test_bad_mint(self):
            r = await self.client.get("/token?mint=not-a-mint")
            self.assertEqual(r.status, 400)
            self.assertIn("look like a Solana token address", await r.text())   # apostrophe is HTML-escaped

        async def test_token_page_rows_and_chart(self):
            r = await self.client.get(f"/token?mint={MINT}")
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIsNone(CYRILLIC.search(html))
            self.assertIn('id="rows"', html)
            self.assertIn('data-rows=', html)
            self.assertIn('data-hints=', html)
            self.assertIn("Find the pump", html)                         # a rule, not a model
            self.assertNotIn("Let AI choose", html)
            self.assertNotIn("Coming next", html)
            self.assertIn("&#34;label&#34;: &#34;Range 1&#34;, &#34;from&#34;: &#34;&#34;", html)   # a bare chart: hints wait for the button
            self.assertNotIn("&#34;label&#34;: &#34;Pump 1", html)
            self.assertIn('id="chart"', html)
            self.assertIn("lightweight-charts", html)
            self.assertIn("static/chart.js", html)
            self.assertIn("and analyze", html)
            self.assertNotIn("<svg", html.split("<footer")[0])         # the page body draws with the chart library, not inline SVG

        async def test_token_page_preset_from_result(self):
            r = await self.client.get(f"/token?mint={MINT}&from=2001-09-09T01:46&to=2001-09-09T02:06&exit=2001-09-09T02:46")
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn("From the result", html)

        async def test_candles_json(self):
            a, b = (T0 - H) // 1000, (T0 + 2 * H) // 1000
            r = await self.client.get(f"/candles.json?mint={MINT}&tf=1m&a={a}&b={b}")
            self.assertEqual(r.status, 200)
            js = await r.json()
            self.assertGreater(len(js), 50)
            self.assertEqual(sorted(js[0].keys()), ["close", "high", "low", "open", "time", "volume"])
            self.assertEqual(js[0]["time"], (T0 - H) // 1000)
            self.assertAlmostEqual(js[0]["close"], 1_000_000)          # price × supply
            r = await self.client.get(f"/candles.json?mint={MINT}&tf=1m&a={b}&b={a}")
            self.assertEqual(await r.json(), [])                        # empty range → empty list

        async def test_analyze_to_result_and_csv(self):
            await self.client.get(f"/token?mint={MINT}")
            form = {"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"}
            r = await self.client.post("/analyze", data=form, allow_redirects=False)
            self.assertEqual(r.status, 302)
            loc = r.headers["Location"]
            self.assertTrue(loc.startswith("/job/"))
            html = ""
            for _ in range(50):
                r = await self.client.get(loc)
                html = await r.text()
                if "↓ Export" in html:
                    break
                await asyncio.sleep(0.05)
            self.assertIn("↓ Export", html)
            self.assertIn("Bought in range", html)
            self.assertIn("Adjust the range", html)
            self.assertIn('id="chart"', html)
            self.assertIsNone(CYRILLIC.search(html))
            self.assertIn('id="filters"', html)                        # facts filters + selection + export
            self.assertIn("Export", html)
            self.assertNotIn("Copy addresses", html)
            self.assertIn('class="sortable"', html)
            self.assertIn('data-count=', html)                          # count-up tiles
            self.assertIn(">Hide:<", html)
            self.assertIn("Exits known for", html)                       # coverage line
            self.assertNotIn("Only:", html)                              # the "Only" chips are gone (owner, 25.09)
            self.assertIn("Trades up to", html)
            self.assertIn("Select all", html)
            self.assertIn('id="more"', html)                             # rows beyond the first 100 wait behind "Show more"
            self.assertIn("Show 100 more", html)
            r = await self.client.get(loc + ".state.json?since=0")      # live state for the terminal
            self.assertEqual(r.status, 200)
            stt = await r.json()
            self.assertEqual(stt["status"], "done")
            self.assertEqual(stt["progress"]["phase"], "done")
            self.assertTrue(stt["n_lines"] > 0 and stt["log"])
            r = await self.client.get("/job/nope.state.json")
            self.assertEqual(r.status, 404)
            r = await self.client.get(loc + ".json?scope=24h")           # scope recount from the stored trades
            self.assertEqual(r.status, 200)
            sj = await r.json()
            self.assertEqual(sj["scope"], "24h")
            self.assertEqual(sj["rows"][0]["wallet"], "A")
            r = await self.client.get(loc + "?scope=48h")
            self.assertEqual(r.status, 200)
            page48 = await r.text()
            self.assertNotIn("Numbers for", page48)                      # the scope switch is gone; an old ?scope= link still opens
            self.assertIn('id="watchbtn"', page48)                      # the real save to a list, no placeholder
            self.assertIn('id="aform"', page48)                          # the agent: cards, suggested questions and a question line
            self.assertIn("Save analysis", page48)
            self.assertNotIn("Add to watchlist", page48)
            self.assertNotIn("soon-badge", page48)
            self.assertIn("Sold out", page48)                           # tiles renamed, with hints
            self.assertIn("← Adjust the range", page48)                 # in the header now
            r = await self.client.get("/wallet_trades.json?job=" + loc.split("/")[-1] + "&wallet=A")
            self.assertEqual(r.status, 400)                              # not a base58 wallet in tests → readable error
            o = {"Origin": f"http://{self.client.host}:{self.client.port}"}
            r = await self.client.post(loc + "/agent/cards", json={"lang": "en"}, headers=o)   # the agent: off on this server → 503 with a reason
            self.assertEqual(r.status, 503)
            self.assertIn("switched on", (await r.json())["error"])
            a = object()                                                 # the pages only ask whether a model is set
            self.assertIn("AI agent", page48)
            self.assertEqual(page48.count("<b>Coming soon</b>"), 1)          # no key on this server: the button says so
            self.app["assistant"] = None                                 # …and then the home page must not promise it either
            home_off = await (await self.client.get("/")).text()
            self.assertIn("Coming next", home_off)
            self.assertNotIn("Live in beta", home_off)
            self.assertIn("The agent is off on this server", await (await self.client.get("/docs/roadmap")).text())
            self.app["assistant"] = a
            home_on = await (await self.client.get("/")).text()
            self.assertIn("Live in beta", home_on)                       # with a key the promise is true
            r = await self.client.get("/")                               # home with a finished analysis: counters, sample, bg lines
            self.assertEqual(r.status, 200)
            home = await r.text()
            self.assertIn(">Demo<", home)                                # the recorded token is called the same word everywhere
            self.assertNotIn(">Example<", home)
            self.assertIn("TST", home)
            r = await self.client.get(loc + ".csv")
            self.assertEqual(r.status, 200)
            body = await r.text()
            self.assertTrue(body.startswith("wallet,first_buy_utc"))
            self.assertIn("\nA,", body)
            self.assertTrue(",trades," in body or ",wallet-trades," in body)   # source column
            r = await self.client.get(loc + ".json")
            self.assertEqual(r.status, 200)
            js = await r.json()
            self.assertEqual(js["rows"][0]["wallet"], "A")
            self.assertIn("wallet", js["columns"])
            jid = loc.split("/")[-1]                                    # markers: the wallet's trades, exact times
            r = await self.client.get(f"/wallet_trades.json?job={jid}&wallet=" + "A" * 32)
            self.assertEqual(r.status, 404)                             # a wallet outside the analysis is never fetched
            r = await self.client.get(loc + ".enrich.json")
            self.assertEqual(r.status, 200)
            self.assertEqual((await r.json())["total"], 0)               # no RPC in tests

        async def test_two_windows_two_jobs(self):
            base = {"mint": MINT, "to": "2001-09-09T02:06"}
            r1 = await self.client.post("/analyze", data=dict(base, **{"from": "2001-09-09T01:46"}), allow_redirects=False)
            r2 = await self.client.post("/analyze", data=dict(base, **{"from": "2001-09-09T01:50"}), allow_redirects=False)
            self.assertEqual((r1.status, r2.status), (302, 302))
            self.assertNotEqual(r1.headers["Location"], r2.headers["Location"])

        async def test_bad_window_is_400(self):
            form = {"mint": MINT, "from": "2001-09-09T02:46", "to": "2001-09-09T01:46"}
            r = await self.client.post("/analyze", data=form, allow_redirects=False)
            self.assertEqual(r.status, 400)
            self.assertIn("From must be earlier than To", await r.text())
            form = {"mint": MINT, "from": "2001-09-08T00:00", "to": "2001-09-09T02:00"}
            r = await self.client.post("/analyze", data=form, allow_redirects=False)
            self.assertEqual(r.status, 400)
            self.assertIn("longer than 24 hours", await r.text())

        async def test_health(self):
            r = await self.client.get("/health")
            self.assertEqual((await r.json())["ok"], True)

        async def test_wallet_trades_answer_only_for_the_rows(self):
            # чужа адреса — 404 у будь-якому режимі, до будь-якої роботи; старий результат повної історії читає лише рядки
            # цього гаманця з файла угод; демо не купує угод навіть для своїх рядків
            mint, jid, a, b = "K" * 40, "KKKKKK_20010909-0146_0206", 999999960000, 1000001160000
            listed, foreign = acct_mod.b58encode(b"\x31" * 32), acct_mod.b58encode(b"\x32" * 32)
            res = _result(mint, a, b, listed)
            res.update(mode="trades", wallet_trades=None, rows=[{"wallet": listed}])   # результат до збережених угод
            _job_file(self.tmp.name + "/web", jid, mint, a, b, res)
            mine = {"tx": "t1", "wallet": listed, "type": "buy", "time": a + 60000, "qty": 10.0, "usd": 5.0, "price": 0.5, "sol": 0.02}
            lines = [mine, dict(mine, tx="t2", wallet=foreign), mine, dict(mine, tx="t3", time=a - 60000)]   # чужий, дубль, до діапазону
            os.makedirs(self.tmp.name + "/cache", exist_ok=True)
            with open(f"{self.tmp.name}/cache/trades_{mint}.jsonl", "w") as f:
                f.write("".join(json.dumps(x) + "\n" for x in lines) + "{broken\n")
            self.app["jobs"]._load()
            before, left0 = self.st.requests, self.app["browse_daily"].left("global", 300)
            r = await self.client.get(f"/wallet_trades.json?job={jid}&wallet={foreign}", headers=GUEST)
            self.assertEqual(r.status, 404)
            d = await (await self.client.get(f"/wallet_trades.json?job={jid}&wallet={listed}", headers=GUEST)).json()
            self.assertEqual([(t["t"], t["sol"]) for t in d["trades"]], [(a + 60000, 0.02)])
            self.assertEqual((self.st.requests, self.app["browse_daily"].left("global", 300)), (before, left0))
            djid, _, _ = self._seed_one_demo()
            self.app["jobs"].get(djid).result["rows"] = [{"wallet": listed}]     # рядок демо без збережених угод
            for w, code in ((foreign, 404), (listed, 200)):
                r = await self.client.get(f"/wallet_trades.json?job={djid}&wallet={w}", headers=GUEST)
                self.assertEqual(r.status, code, w)
            self.assertEqual((await r.json())["trades"], [])
            self.assertEqual((self.st.requests, self.app["browse_daily"].left("global", 300)), (before, left0))

        async def test_demo_replays_do_not_wait_behind_a_live_run(self):
            # програвання демо має свої потоки: натовп у демо не тримає платний прогін, а прогін — демо
            import threading
            jid, a, b = self._seed_one_demo()
            gate, real = threading.Event(), self.st.trades_page

            def slow(mint, cursor):
                gate.wait(10)
                return real(mint, cursor)
            self.st.trades_page = slow
            try:
                r = await self.client.post("/analyze", allow_redirects=False,
                                           data={"mint": "L" * 40, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})
                live = self.app["jobs"].get(r.headers["Location"].split("/")[-1])
                r = await self.client.post("/analyze", allow_redirects=False, headers=self.same_site,
                                           data={"mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)})
                rid = r.headers["Location"].split("/")[-1]
                await asyncio.to_thread(self.app["jobs"].rq.join)
                self.assertEqual(self.app["jobs"].get(rid).status, "done")        # демо відіграло…
                self.assertIn(live.status, ("queued", "running"))                  # …поки платний прогін ще чекає на угоди
            finally:
                gate.set()
                self.st.trades_page = real
            await asyncio.to_thread(self.app["jobs"].q.join)
            self.assertEqual(live.status, "done", live.error)

        async def test_demo_replays_are_reused_and_throttled(self):
            # та сама адреса з тим самим діапазоном іде до свого програвання; понад стелю чи з чужого сайту — одразу
            # збережений результат, без нового програвання
            jid, a, b = self._seed_one_demo()
            rng = {"mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)}

            async def press(h):
                return (await self.client.post("/analyze", allow_redirects=False, headers=h, data=rng)).headers["Location"]
            first = await press(self.same_site)
            self.assertEqual(await press(self.same_site), first)                  # ще грає: туди ж
            await asyncio.to_thread(self.app["jobs"].rq.join)
            self.app["demo_runs"].max_fails = 2                                    # стеля: друге нове програвання — останнє
            second = await press(self.same_site)
            self.assertTrue(second.startswith(f"/job/{jid}_r") and second != first, second)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            n = sum(1 for j in self.app["jobs"].jobs.values() if j.replay)
            self.assertEqual(await press(self.same_site), f"/job/{jid}")
            self.app["demo_runs"].max_fails = 10
            self.app["demo_runs"].fails.clear()
            self.assertEqual(await press(GUEST), f"/job/{jid}")                    # без Origin: чужа сторінка не заводить програвань
            self.assertEqual(sum(1 for j in self.app["jobs"].jobs.values() if j.replay), n)

        async def test_a_run_that_spent_real_credits_keeps_its_charge(self):
            # невдалий прогін, що вже витратив запити, лишається порахованим: інакше падіння були б безкоштовними
            from tracced.web.app import _ip_key
            self.app["admins"] = set()
            self.app["s"]["refund_below_requests"] = 1                          # у тесті «дорогий» — уже з першого запиту
            pk = acct_mod.b58encode(b"\x25" * 32)
            g0 = self.app["runs_daily"].left("global", 40)
            self.st.fail_trades = True
            try:
                r = await self.client.post("/analyze", allow_redirects=False, headers={"Cookie": wallet_cookie(pk)},
                                           data={"mint": MINT, "from": "2001-09-09T01:50", "to": "2001-09-09T02:06"})
                dev = r.cookies["early_dev"].value
                await asyncio.to_thread(self.app["jobs"].q.join)
            finally:
                self.st.fail_trades = False
                self.app["s"].pop("refund_below_requests")
                self.app["admins"] = {TEST_PK}
            j = self.app["jobs"].get(r.headers["Location"].split("/")[-1])
            self.assertEqual(j.status, "error")
            self.assertGreaterEqual(j.spent, 1)
            self.assertEqual(self.app["accounts"].runs_today(pk), 1)
            self.assertEqual(self.app["runs_daily"].left("dev:" + dev, 5), 4)
            self.assertEqual(self.app["runs_daily"].left(_ip_key("127.0.0.1"), 10), 9)
            self.assertEqual(self.app["runs_daily"].left("global", 40), g0 - 1)
            self.assertTrue(any("counts toward today's analyses" in line for line in j.log), j.log)

        async def test_a_restart_gives_back_every_count_of_the_cut_run(self):
            # прогін, перерваний рестартом, повертає і день людини, і браузер, і мережу: вони тепер лежать у файлі
            from tracced.web.app import _ip_key
            pk, jid = acct_mod.b58encode(b"\x26" * 32), "MMMMMM_20010909-0146_0206"
            charged = ["dev:" + "ab" * 16, _ip_key("10.0.0.9")]
            self.app["accounts"].take_run(pk, 5)
            for key in charged + ["global"]:
                self.app["runs_daily"].add(key, 1)
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump({"id": jid, "mint": "M" * 40, "t_from": 999999960000, "t_to": 1000001160000, "status": "running",
                           "created_ms": 1, "owner": pk, "charged": charged, "log": [], "result": None}, f)
            g0 = self.app["runs_daily"].left("global", 40)
            self.app["jobs"]._load()
            self.assertEqual(self.app["jobs"].get(jid).status, "error")
            self.assertEqual(self.app["accounts"].runs_today(pk), 0)
            self.assertEqual([self.app["runs_daily"].left(k, 5) for k in charged], [5, 5])
            self.assertEqual(self.app["runs_daily"].left("global", 40), g0 + 1)

        async def test_result_views_reuse_rows_instead_of_recounting(self):
            # «уся історія» свіжого результату — це збережені рядки; масштаб рахується раз, доки збагачення не додало тегів
            from unittest import mock
            from tracced.early import scope as scope_mod
            r = await self.client.post("/analyze", allow_redirects=False,
                                       data={"mint": "N" * 40, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})
            loc = r.headers["Location"]
            await asyncio.to_thread(self.app["jobs"].q.join)
            job = self.app["jobs"].get(loc.split("/")[-1])
            self.assertTrue(job.result.get("rows_rev"))
            with mock.patch.object(scope_mod, "rows_for", wraps=scope_mod.rows_for) as rf:
                for path in (loc, loc + ".json", loc + ".csv"):
                    self.assertEqual((await self.client.get(path)).status, 200, path)
                self.assertEqual(rf.call_count, 0)
                for _ in range(2):
                    self.assertEqual((await (await self.client.get(loc + ".json?scope=24h")).json())["rows"][0]["wallet"], "A")
                self.assertEqual(rf.call_count, 1)
                job.result.setdefault("fresh_wallets", []).append("A")
                await self.client.get(loc + ".json?scope=24h")
                self.assertEqual(rf.call_count, 2)
                job.result.pop("rows_rev")                                         # результат іншої версії коду: перераховуємо, раз
                for path in (loc + ".json", loc):
                    self.assertEqual((await self.client.get(path)).status, 200, path)
                self.assertEqual(rf.call_count, 3)

        async def test_a_second_press_is_not_charged_and_the_month_counts_runs_in_flight(self):
            from tracced.web.jobs import Job, make_id
            s, real = self.app["s"], self.st.credits
            self.app["admins"] = set()
            s.update(credits_month=10_000, credits_reserve_pct=5, run_cap_requests=300)      # резерв 500
            pk = acct_mod.b58encode(b"\x27" * 32)
            rng = lambda m: {"mint": m, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"}  # noqa: E731
            jid = make_id("P" * 40, chart.from_input(rng("")["from"]), chart.from_input(rng("")["to"]))

            def first_press_lands():                    # поки друге натискання чекало баланс, перше вже поставило прогін
                j = Job(jid, "P" * 40, chart.from_input(rng("")["from"]), chart.from_input(rng("")["to"]))
                j.status = "running"
                self.app["jobs"].jobs[jid] = j
                return 50_000
            self.st.credits = first_press_lands
            try:
                r = await self.client.post("/analyze", allow_redirects=False, headers={"Cookie": wallet_cookie(pk)}, data=rng("P" * 40))
                self.assertEqual(r.headers["Location"], f"/job/{jid}")
                self.assertEqual(self.app["accounts"].runs_today(pk), 0)                 # друге натискання нічого не списало
                self.app["jobs"].jobs[jid].owner = acct_mod.b58encode(b"\x28" * 32)       # чужий прогін ще йде…
                self.st.credits, self.app["credits"]["at"] = (lambda: 1_000), 0
                r = await self.client.post("/analyze", allow_redirects=False, headers={"Cookie": wallet_cookie(pk)}, data=rng("Q" * 40))
                self.assertEqual(r.status, 503, await r.text())                          # …і його найгірше ще попереду: 1000 − 2×300 < 500
                self.app["jobs"].jobs.pop(jid)
                self.app["credits"]["at"] = 0
                r = await self.client.post("/analyze", allow_redirects=False, headers={"Cookie": wallet_cookie(pk)}, data=rng("Q" * 40))
                self.assertEqual(r.status, 302, await r.text())                          # сам по собі вміщається: 1000 − 300 ≥ 500
                await asyncio.to_thread(self.app["jobs"].q.join)
            finally:
                self.st.credits = real
                s.update(credits_month=0, credits_reserve_pct=0)
                self.app["admins"] = {TEST_PK}

        async def test_a_limit_notice_shows_only_to_someone_who_is_out_of_runs(self):
            # стара адреса з notice=limit, посилання від друга чи гість: вікна «ви використали свої» нема
            self.app["admins"] = set()
            try:
                fresh = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x29" * 32))}
                for h in (GUEST, fresh):
                    for kind in ("limit", "netcap"):
                        html = await (await self.client.get(f"/token?mint={MINT}&notice={kind}", headers=h)).text()
                        self.assertNotIn('id="limitsheet"', html, (h, kind))
                        self.assertNotIn("openLimit('", html)
            finally:
                self.app["admins"] = {TEST_PK}

        async def test_marks_ask_dexscreener_only_about_known_tokens(self):
            from unittest import mock
            paid = [{"ms": 1, "kind": "profile"}]
            with mock.patch("tracced.web.app.dexscreener.orders", return_value=paid) as orders:
                d = await (await self.client.get("/marks.json?mint=" + "R" * 40, headers=GUEST)).json()
                self.assertNotIn("paid", d)
                self.assertEqual(orders.call_count, 0)                             # чужа адреса — жодного виклику
                await self.client.get("/token?mint=" + "R" * 40)                   # токен відкрили: огляд у кеші
                d = await (await self.client.get("/marks.json?mint=" + "R" * 40, headers=GUEST)).json()
            self.assertEqual((d["paid"], orders.call_count), (paid, 1))

        async def test_every_response_carries_the_security_headers(self):
            for path, kw in (("/", {}), ("/job/nope.json", {}), ("/how", {"allow_redirects": False}), ("/static/style.css", {})):
                r = await self.client.get(path, headers=GUEST, **kw)
                self.assertEqual(r.headers.get("Server"), "tracced", path)          # версію aiohttp не називаємо
                self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff", path)
                self.assertEqual(r.headers.get("Strict-Transport-Security"), "max-age=31536000", path)
                self.assertEqual(r.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin", path)
                csp = r.headers.get("Content-Security-Policy", "")
                self.assertIn("frame-ancestors 'none'", csp, path)
                self.assertNotIn("script-src", csp)                                 # вбудовані скрипти сторінок працюють

        async def test_a_question_is_given_back_only_when_the_model_did_not_answer(self):
            from tracced.early.assistant import AssistantError
            r = await self.client.post("/analyze", allow_redirects=False,
                                       data={"mint": "S" * 40, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})
            loc = r.headers["Location"]
            await asyncio.to_thread(self.app["jobs"].q.join)

            class Flaky:
                model = "fake"

                def ask(self, result, cfg, q, lang):
                    if q == "down":
                        raise AssistantError("The agent's model is busy right now. Try again in a minute.")
                    return {"on_topic": False, "answer": ["I only answer questions about this analysis."], "wallets": [], "model": "fake"}, [], {}
            self.app["agent"], self.app["admins"] = Flaky(), set()
            try:
                who = f"agent-ask:{TEST_PK}"
                n0 = self.app["assistant_daily"].left(who, 10)
                r = await self.client.post(loc + "/agent/ask", json={"q": "down"}, headers=self.same_site)
                self.assertEqual(r.status, 502)
                self.assertEqual(self.app["assistant_daily"].left(who, 10), n0)          # модель мовчала — питання не рахується
                r = await self.client.post(loc + "/agent/ask", json={"q": "write me a poem"}, headers=self.same_site)
                self.assertEqual((r.status, (await r.json())["on_topic"]), (200, False))
                self.assertEqual(self.app["assistant_daily"].left(who, 10), n0 - 1)      # стороннє питання — рахується
                r = await self.client.post(loc + "/agent/ask", json={"q": "x" * 501}, headers=self.same_site)
                self.assertEqual(r.status, 400)
                log = self.app["agent_store"].recent()
                self.assertEqual([(e["kind"], e.get("on_topic"), bool(e.get("error"))) for e in log[:2]],
                                 [("ask", False, False), ("ask", None, True)])
            finally:
                self.app["agent"], self.app["admins"] = None, {TEST_PK}


if AioHTTPTestCase:
    class FakeAgesWeb:
        """Вік і спонсор без мережі: рахує виклики, як нода рахувала б кредити."""
        def __init__(self):
            self.calls, self.cache, self.pending = 0, {}, set()

        def cached(self, w):
            return self.cache.get(w)

        def paused(self):
            return False

        def oldest_tx(self, w, refresh=False, full=True, before=None):
            if w not in self.cache or refresh:
                self.calls += 1
                self.cache[w] = {"oldest_ms": 999_990_000_000, "exact": True, "n": 3, "oldest_sig": "sig-" + w[:4]}
            return self.cache[w]

        def funder(self, w, sig, scan=True):
            self.calls += 1
            if w in self.pending and scan:                    # дешева перевірка лишила пошук серед перших ста
                self.pending.discard(w)
                return "A" * 44
            return "F" * 44

        def funder_pending(self, w):
            return w in self.pending

        def oldest_tx_deep(self, w):
            """Зайнятий гаманець: глибше гортання доходить до першої транзакції."""
            self.calls += 1
            self.cache[w] = {"oldest_ms": 980_000_000_000, "exact": True, "n": 13_000, "oldest_sig": "first-" + w[:4], "deep": True}
            return self.cache[w]

        def flush(self):
            pass

    class TestLazyWalletAge(AioHTTPTestCase):
        """Вік і спонсор гаманця поза першими за PnL перевіряються, коли відкрили його картку, і лишаються в результаті."""

        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.ages = FakeAgesWeb()
            s = settings.load()
            s["age_lookups_max"] = 0                                      # аналіз сам нікого не перевіряє
            s["replay_s"] = 0.6                                           # демо програється швидко
            self.st = FakeWebST(TRADES)
            return create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache", ages=self.ages)

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        async def test_age_on_card_open(self):
            jid, mint, w = "JJJJJJ_20010909-0146_0206", "J" * 40, acct_mod.b58encode(b"\x0c" * 32)
            stored = {"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done", "error": None,
                      "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "JJJ", "progress": {"phase": "done", "done": 1, "total": 1}, "log": [],
                      "result": {"info": {"mint": mint, "symbol": "JJJ", "supply": 1000000, "created_time": 999996400000},
                                 "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "trades",
                                 "counts": {}, "coverage": {}, "wallet_trades": {}, "rows": [{"wallet": w, "first_buy_ms": 1000000060000, "tag_list": []}],
                                 "scope": "all", "requests": 0}}
            os.makedirs(self.tmp.name + "/web", exist_ok=True)
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump(stored, f)
            self.app["jobs"]._load()
            r = await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}")
            self.assertEqual(r.status, 401)                               # гість не витрачає кредити ноди
            self.assertEqual(self.ages.calls, 0)
            me = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x0d" * 32))}
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}", headers=me)).json()
            self.assertEqual(d["age"]["ms"], 999_990_000_000)
            self.assertEqual(d["funder"], "F" * 44)
            self.assertEqual(self.ages.calls, 2)
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}")).json()   # тепер і гостю, з результату
            self.assertEqual(d["funder"], "F" * 44)
            self.assertEqual(self.ages.calls, 2)

        async def test_a_card_finishes_the_funder_search_the_cheap_check_skipped(self):
            # гаманець поза першими за PnL: перша транзакція не дала спонсора, пошук серед перших ста — з картки
            jid, mint, w = "APPWAL_20010909-0146_0206", "P" * 40, acct_mod.b58encode(b"\x61" * 32)
            rows = [{"wallet": w, "first_buy_ms": 1000000060000, "tag_list": []}]
            result = {"info": {"mint": mint, "symbol": "APP", "supply": 1000000, "created_time": 999996400000},
                      "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "trades",
                      "counts": {}, "coverage": {}, "wallet_trades": {}, "rows": rows, "funder_checked": [w],
                      "ages": {w: {"ms": 999_990_000_000, "exact": True, "n": 12}}, "scope": "all", "requests": 0}
            os.makedirs(self.tmp.name + "/web", exist_ok=True)
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump({"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "status": "done",
                           "created_ms": 1, "log": [], "result": result}, f)
            self.app["jobs"]._load()
            self.ages.cache[w] = {"oldest_ms": 999_990_000_000, "exact": True, "n": 12, "oldest_sig": "s12"}
            self.ages.pending.add(w)
            r = await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}")
            self.assertEqual(r.status, 401)                               # пошук платний: гість його не запускає
            me = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x62" * 32))}
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}", headers=me)).json()
            self.assertEqual((d["funder"], self.ages.calls), ("A" * 44, 1))   # лише пошук: вік уже був
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}")).json()
            self.assertEqual((d["funder"], self.ages.calls), ("A" * 44, 1))   # далі — з результату, для всіх

        async def test_a_card_reads_again_an_age_after_the_wallets_own_buy(self):
            # кеш каже, що гаманець народився через п'ять днів після покупки: такого не буває, картка перечитує
            jid, mint, w = "LATEAG_20010909-0146_0206", "L" * 40, acct_mod.b58encode(b"\x71" * 32)
            rows = [{"wallet": w, "first_buy_ms": 1000000060000, "tag_list": []}]
            result = {"info": {"mint": mint, "symbol": "LTE", "supply": 1000000, "created_time": 999996400000},
                      "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "trades",
                      "counts": {}, "coverage": {}, "wallet_trades": {}, "rows": rows, "scope": "all", "requests": 0}
            os.makedirs(self.tmp.name + "/web", exist_ok=True)
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump({"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "status": "done",
                           "created_ms": 1, "log": [], "result": result}, f)
            self.app["jobs"]._load()
            self.ages.cache[w] = {"oldest_ms": 1000000060000 + 5 * 86_400_000, "exact": True, "n": 8, "oldest_sig": "spam"}
            r = await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}")
            self.assertEqual(r.status, 401)                               # хибного віку гість не бачить: лише «підключи гаманець»
            self.assertNotIn("age", await r.json())
            me = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x72" * 32))}
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}", headers=me)).json()
            self.assertEqual(d["age"]["ms"], 999_990_000_000)             # перечитано
            self.assertEqual(self.ages.calls, 2)                          # вік і спонсор

        async def test_a_busy_wallet_gets_its_real_age_and_funder_when_its_card_opens(self):
            # 6 000 останніх транзакцій не дійшли до першої: картка гортає глибше, раз, як одна з карток дня
            jid, mint, w = "BUSYYY_20010909-0146_0206", "B" * 40, acct_mod.b58encode(b"\x51" * 32)
            rows = [{"wallet": w, "first_buy_ms": 1000000060000, "tag_list": []}]
            result = {"info": {"mint": mint, "symbol": "BSY", "supply": 1000000, "created_time": 999996400000},
                      "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "trades",
                      "counts": {}, "coverage": {}, "wallet_trades": {}, "rows": rows, "funder_checked": [w],
                      "ages": {w: {"ms": 999_900_000_000, "exact": False, "n": 6000}}, "scope": "all", "requests": 0}
            os.makedirs(self.tmp.name + "/web", exist_ok=True)
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump({"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "status": "done",
                           "created_ms": 1, "log": [], "result": result}, f)
            self.app["jobs"]._load()
            self.ages.cache[w] = {"oldest_ms": 999_900_000_000, "exact": False, "n": 6000, "oldest_sig": "s6000"}
            r = await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}")
            self.assertEqual(r.status, 401)                                          # гість: глибше лише з гаманцем
            self.assertEqual(self.ages.calls, 0)
            me = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x52" * 32))}
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}", headers=me)).json()
            self.assertEqual((d["age"]["ms"], d["age"]["exact"], d["age"]["n"]), (980_000_000_000, True, 13_000))
            self.assertEqual(d["funder"], "F" * 44)                                  # спонсор знайшовся разом з віком
            self.assertEqual(self.ages.calls, 2)
            self.assertEqual(self.app["browse_daily"].left("age:acct:" + acct_mod.b58encode(b"\x52" * 32), 50), 49)   # одна картка з 50
            res = self.app["jobs"].get(jid).result
            self.assertEqual((res["ages"][w]["exact"], res["funders"][w]), (True, "F" * 44))   # у результаті — для всіх
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w}")).json()
            self.assertEqual((d["age"]["exact"], d["funder"]), (True, "F" * 44))     # тепер і гостю, без нових викликів
            self.assertEqual(self.ages.calls, 2)

        async def test_demo_cards_are_read_only_and_say_when_nothing_was_checked(self):
            from tracced.web.app import _demo
            seed_demo(self.tmp.name, self.app)
            row = {"wallet": W1, "first_buy_ms": DEMO_A + 1000, "tag_list": []}
            self.app["jobs"].get(DEMO_JID).result["rows"] = [dict(row)]
            _demo(self.app)["ranges"][0]["result"]["rows"] = [dict(row)]          # те, що покаже програвання
            me = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x0d" * 32))}
            d = await (await self.client.get(f"/wallet_age.json?job={DEMO_JID}&wallet={W1}", headers=me)).json()
            self.assertEqual((d["age"], d["checked"]), (None, False))              # не перевіряли — так і кажемо, а не «історії нема»
            self.ages.cache[W1] = {"oldest_ms": 999_990_000_000, "exact": True, "n": 3, "oldest_sig": "s"}
            d = await (await self.client.get(f"/wallet_age.json?job={DEMO_JID}&wallet={W1}")).json()
            self.assertEqual((d["age"]["ms"], d["checked"]), (999_990_000_000, True))   # з кешу — будь-кому і безкоштовно
            o = {"Origin": f"http://{self.client.host}:{self.client.port}"}
            r = await self.client.post("/analyze", allow_redirects=False, headers=o,
                                       data={"mint": MINT, "from": chart.to_input(DEMO_A), "to": chart.to_input(DEMO_B)})
            rid = r.headers["Location"].split("/")[-1]
            await asyncio.to_thread(self.app["jobs"].rq.join)
            for cached in (True, False):
                if not cached:
                    del self.ages.cache[W1]
                d = await (await self.client.get(f"/wallet_age.json?job={rid}&wallet={W1}", headers=me)).json()
                self.assertEqual(d["checked"], cached)
            self.assertEqual(self.ages.calls, 0)                                   # демо і програвання не платять ноді
            self.assertFalse(os.path.exists(f"{self.tmp.name}/web/{rid}.json"))    # і не лягають на диск
            self.assertNotIn("ages", _demo(self.app)["ranges"][0]["result"])        # спільний знімок не змінився

        async def test_card_lookups_have_their_own_cap_and_keep_fresh(self):
            jid, mint = "VVVVVV_20010909-0146_0206", "V" * 40
            w1, w2, w3 = (acct_mod.b58encode(bytes([x]) * 32) for x in (0x41, 0x42, 0x43))
            rows = [{"wallet": w, "first_buy_ms": 999_990_000_000 + 3_600_000, "tag_list": []} for w in (w1, w2, w3)]
            result = {"info": {"mint": mint, "symbol": "VVV", "supply": 1000000, "created_time": 999996400000},
                      "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "trades",
                      "counts": {}, "coverage": {}, "wallet_trades": {}, "rows": rows, "funder_checked": [w3],
                      "scope": "all", "requests": 0}
            os.makedirs(self.tmp.name + "/web", exist_ok=True)
            path = f"{self.tmp.name}/web/{jid}.json"
            with open(path, "w") as f:
                json.dump({"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "status": "done",
                           "created_ms": 1, "log": [], "result": result}, f)
            self.app["jobs"]._load()
            self.ages.cache[w3] = {"oldest_ms": 999_000_000_000, "exact": True, "n": 5, "oldest_sig": "s3"}
            d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w3}")).json()
            self.assertEqual((d["age"]["ms"], d["checked"]), (999_000_000_000, True))   # спонсор перевірений, вік — з кешу
            self.app["s"]["age_card_per_day"] = 1
            me = {"Cookie": wallet_cookie(acct_mod.b58encode(b"\x0e" * 32))}
            try:
                d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w1}", headers=me)).json()
                self.assertEqual((d["checked"], d["fresh"]), (True, True))
                self.assertEqual(self.app["jobs"].get(jid).result["fresh_wallets"], [w1])   # тег бачать експорт і списки
                d = await (await self.client.get(f"/wallet_age.json?job={jid}&wallet={w2}", headers=me)).json()
                self.assertEqual((d["checked"], d.get("capped")), (False, True))           # своя денна стеля карток
                self.assertEqual(self.ages.calls, 2)                                         # друга картка ноду не питала
            finally:
                self.app["s"].pop("age_card_per_day")
            for _ in range(40):                                                   # запис результату — трохи згодом, одним разом
                with open(path) as f:
                    if w1 in (json.load(f)["result"].get("fresh_wallets") or []):
                        break
                await asyncio.sleep(0.05)
            with open(path) as f:
                self.assertIn(w1, json.load(f)["result"]["fresh_wallets"])

        async def test_enrich_state_tells_what_is_really_pending(self):
            seed_demo(self.tmp.name, self.app)
            q = self.app["jobs"]
            job = q.get(OTHER_JID)
            job.result["enrich"] = {"done": 1, "total": 3, "fresh": 0, "paused": "rpc-budget"}
            q.namer = lambda j, save: None                                        # сервер, що питає імена
            try:
                d = await (await self.client.get(f"/job/{OTHER_JID}.enrich.json")).json()
                self.assertIsNone(d["paused"])                                    # бюджет уже не на паузі (новий місяць)…
                self.assertFalse(d["identities_done"])
                await asyncio.to_thread(q.eq.join)
                self.assertNotIn("paused", job.result["enrich"])                  # …і збагачення пішло далі без рестарту
                d = await (await self.client.get(f"/job/{DEMO_JID}.enrich.json")).json()
                self.assertTrue(d["identities_done"])                             # демо — знімок: імен ніхто не чекає
            finally:
                q.namer = None
            d = await (await self.client.get(f"/job/{OTHER_JID}.enrich.json")).json()
            self.assertTrue(d["identities_done"])                                 # сервер без імен: чекати нема на що


class TestSharedClient(unittest.TestCase):
    """Один клієнт на аналіз і на сторінки: кілька запитів одночасно, і кожен рахує лише свої."""

    def make(self):
        import threading
        import time as _t

        class Real:
            def __init__(self):
                self.requests, self.in_flight, self.max_in_flight = 0, 0, 0
                self.lock = threading.Lock()

            def _get(self, path):
                with self.lock:
                    self.requests += 1
                    self.in_flight += 1
                    self.max_in_flight = max(self.max_in_flight, self.in_flight)
                _t.sleep(0.02)
                with self.lock:
                    self.in_flight -= 1
                return {}
        return Real()

    def test_each_caller_counts_its_own_calls_while_they_run_together(self):
        import contextvars
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from tracced.web.app import _share_st
        st = self.make()
        _share_st(st, threading.BoundedSemaphore(4))
        seen = {}

        def run():
            with st.meter():
                with ThreadPoolExecutor(8) as pool:
                    fs = [pool.submit(contextvars.copy_context().run, st._get, f"/w/{i}") for i in range(40)]
                    for f in fs:
                        f.result()
                seen["run"] = st.requests_here()

        def page():
            with st.meter():
                for i in range(3):
                    st._get(f"/chart/{i}")
                seen["page"] = st.requests_here()
        a, b = threading.Thread(target=run), threading.Thread(target=page)
        a.start(); b.start(); a.join(); b.join()
        self.assertEqual(seen, {"run": 40, "page": 3})
        self.assertEqual(st.requests, 43)
        self.assertGreaterEqual(st.max_in_flight, 2)
        self.assertLessEqual(st.max_in_flight, 4)             # слоти тримають стелю одночасних запитів

    def test_a_fake_client_without_http_counts_globally(self):
        import threading
        from tracced.web.app import _share_st
        st = FakeST(TRADES)
        _share_st(st, threading.BoundedSemaphore(2))
        with st.meter():
            st.token_info("x")
        self.assertEqual(st.requests_here(), 1)


class TestThreadSafeStores(unittest.TestCase):
    def test_json_cache_survives_writers_and_flushes_together(self):
        import threading
        from tracced.cache import JsonCache
        with tempfile.TemporaryDirectory() as d:
            c = JsonCache(os.path.join(d, "c.json"), ttl_hours=1, flush_every=3)

            def put(k):
                for i in range(200):
                    c.put(f"{k}:{i}", list(range(20)))
            ts = [threading.Thread(target=put, args=(k,)) for k in range(6)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            c.flush()
            self.assertEqual(len(json.load(open(os.path.join(d, "c.json")))), 1200)

    def test_daily_count_adds_from_many_threads(self):
        import threading
        from tracced.web.app import DailyCount
        with tempfile.TemporaryDirectory() as d:
            dc = DailyCount(os.path.join(d, "n.json"))

            def add():
                for _ in range(100):
                    dc.add("global", 1)
            ts = [threading.Thread(target=add) for _ in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            self.assertEqual(dc.left("global", 10_000), 10_000 - 800)


class TestJobQueue(unittest.TestCase):
    """Черга без сервера: що лягає на диск, що переживає рестарт і що після нього доганяється."""

    @staticmethod
    def _file(d, jid, **kw):
        job = dict({"id": jid, "mint": "M" * 40, "t_from": 1, "t_to": 2, "status": "done", "created_ms": 1, "log": [],
                    "result": {"rows": [{"wallet": "w"}]}}, **kw)
        with open(os.path.join(d, jid + ".json"), "w") as f:
            json.dump(job, f)

    def test_every_finished_live_run_is_reported_once(self):
        from tracced.web.jobs import JobQueue
        with tempfile.TemporaryDirectory() as d:
            self._file(d, "cut", status="running", result=None)            # обірваний рестартом
            seen = []

            def runner(job):
                if job.mint.startswith("F"):
                    raise RuntimeError("feed down")
                return {"rows": []}
            q = JobQueue(runner, d, on_finish=lambda j: seen.append((j.id, j.status)))
            self.assertEqual(seen, [("cut", "error")])
            q.submit("M" * 40, 1_000_000, 2_000_000)
            q.submit("F" * 40, 1_000_000, 2_000_000)
            q.submit("M" * 40, 3_000_000, 4_000_000, replay={"log": [], "result": {"rows": []}})
            q.q.join()
            q.rq.join()
            self.assertEqual(sorted(st for _, st in seen[1:]), ["done", "error"])   # програвання демо — не прогін
            JobQueue(runner, d, on_finish=lambda j: seen.append(j.id))
            self.assertEqual(len(seen), 3)                                     # рестарт не повторює вже закінчені

    def test_results_without_names_are_named_once_newest_first(self):
        from tracced.web.jobs import JobQueue
        with tempfile.TemporaryDirectory() as d:
            self._file(d, "old", created_ms=1)
            self._file(d, "new", created_ms=5)
            self._file(d, "named", created_ms=9, result={"rows": [], "identities_done": True})
            order = []

            def namer(job, save):
                order.append(job.id)
                job.result["identities_done"] = True
                save(job)
            rows = [{"wallet": f"W{i}"} for i in range(25)]
            self._file(d, "refused", created_ms=7, result={"rows": rows, "identities_done": True})   # «названий» з нулем імен
            self._file(d, "few", created_ms=8, result={"rows": rows[:3], "identities_done": True})    # три невідомих — так буває
            q = JobQueue(lambda j: None, d, namer=namer)
            q.nq.join()
            self.assertEqual(order, ["refused", "new", "old"])              # найсвіжіший — перший; названий — ні
            with open(os.path.join(d, "old.json")) as f:
                self.assertTrue(json.load(f)["result"]["identities_done"])

    def test_enrichment_resumes_after_a_restart_newest_first(self):
        from tracced.web.jobs import JobQueue
        with tempfile.TemporaryDirectory() as d:
            full = {"done": 1, "total": 1, "funders_done": 1}
            self._file(d, "a", created_ms=1, result={"rows": [], "enrich": dict(full, funders_failed=2)})   # спонсори не відповіли
            self._file(d, "b", created_ms=3, result={"rows": [], "enrich": dict(full)})                     # усе готове
            self._file(d, "c", created_ms=5, result={"rows": [], "enrich": {"done": 0, "total": 1}})
            seen = []
            q = JobQueue(lambda j: None, d, enricher=lambda job, save: seen.append(job.id))
            q.eq.join()
            self.assertEqual(seen, ["c", "a"])

    def test_a_raised_limit_brings_older_results_back_for_the_rest_of_their_wallets(self):
        from tracced.web.jobs import JobQueue
        with tempfile.TemporaryDirectory() as d:
            rows = [{"wallet": w} for w in ("A", "B", "C")]
            full = {"done": 1, "total": 1, "funders_done": 1}                     # перевірено лише першого з трьох
            self._file(d, "old", created_ms=1, result={"rows": rows, "enrich": dict(full)})
            seen = []
            q = JobQueue(lambda j: None, d, enricher=lambda job, save: seen.append(job.id), enrich_upto=1)
            q.eq.join()
            self.assertEqual(seen, [])                                           # стеля та сама: нічого не робимо
            q = JobQueue(lambda j: None, d, enricher=lambda job, save: seen.append(job.id), enrich_upto=2000)
            q.eq.join()
            self.assertEqual(seen, ["old"])                                      # стелю підняли: решта гаманців у фоні

    def test_each_result_is_brought_back_to_its_own_target(self):
        """Скільки рядків перевіряти, вирішує сам результат: з підписами покупок — усі, старший — лише перші за PnL."""
        from tracced.web.app import enrich_target
        from tracced.web.jobs import JobQueue
        s = {"age_lookups_max": 2000, "age_full_top": 2}
        old_rows = [{"wallet": w} for w in "ABCDE"]
        new_rows = [{"wallet": w, "entry_tx": "tx" + w} for w in "ABCDE"]
        self.assertEqual(enrich_target({"rows": old_rows}, s), 2)
        self.assertEqual(enrich_target({"rows": new_rows}, s), 5)
        self.assertEqual(enrich_target({"rows": old_rows, "age_full_top": 5}, s), 5)      # демо: повна перевірка всім
        with tempfile.TemporaryDirectory() as d:
            two = {"done": 2, "total": 2, "funders_done": 2}
            self._file(d, "old", created_ms=1, result={"rows": old_rows, "enrich": dict(two)})
            self._file(d, "new", created_ms=5, result={"rows": new_rows, "enrich": dict(two)})
            seen = []
            q = JobQueue(lambda j: None, d, enricher=lambda job, save: seen.append(job.id),
                         enrich_upto=lambda r: enrich_target(r, s))
            q.eq.join()
            self.assertEqual(seen, ["new"])                                      # старий уже має свої перші два

    def test_an_exchange_makes_no_bundle(self):
        """Троє гаманців зі спонсором-біржею — не бандл; троє від однієї людини — бандл. Тег, поставлений раніше,
        знімається, коли спонсор виявився біржею; результат, де бандли ще не перевіряли на біржі, стає в чергу."""
        from types import SimpleNamespace
        from tracced.web.app import make_enricher, _bundles
        from tracced.web.jobs import JobQueue
        funder_of = {"A1": "EXCH", "A2": "EXCH", "A3": "EXCH", "B1": "PERSON", "B2": "PERSON", "B3": "PERSON"}

        class Ages:
            checked = []

            def cached(self, w):
                return None

            def paused(self):
                return False

            def oldest_tx(self, w, refresh=False, full=True, before=None):
                born = {"A1": 1, "A2": 40, "A3": 90}.get(w, 3) * 86_400_000             # біржа поповнювала їх у різні дні
                return {"oldest_ms": born, "exact": True, "n": 2, "oldest_sig": "s-" + w}

            def funder(self, w, sig, scan=True):
                return funder_of[w]

            def is_service(self, a):
                self.checked.append(a)
                return a == "EXCH"

            def flush(self):
                pass
        rows = [{"wallet": w, "first_buy_ms": 100 * 86_400_000, "tag_list": []} for w in funder_of]
        job = SimpleNamespace(result={"rows": rows}, log=[])
        ages = Ages()
        make_enricher(ages, {"age_lookups_max": 10})(job, lambda j: True)
        r = job.result
        self.assertEqual((r["services"], sorted(r["bundle"]), r["bundle_rev"]), (["EXCH"], ["B1", "B2", "B3"], 3))
        self.assertEqual(sorted(ages.checked), ["EXCH", "PERSON"])                 # по разу на спонсора бандла
        self.assertEqual([row["wallet"] for row in rows if "bundle" in row["tag_list"]], ["B1", "B2", "B3"])
        old = {"funders": dict(funder_of), "rows": [dict(row, tag_list=["bundle"], tags="bundle") for row in rows]}
        old["services"] = ["EXCH"]
        _bundles(old, old["rows"])
        self.assertEqual([row["wallet"] for row in old["rows"] if "bundle" in row["tag_list"]], ["B1", "B2", "B3"])
        # той, хто створив гаманці пачкою під запуск, лишається бандлом, хоч і робить тисячі транзакцій на добу
        launch = {f"L{i}": "BUNDLER" for i in range(5)}
        launch.update({"C1": "BUNDLER", "C2": "BUNDLER"})
        t0 = 1_790_000_000_000
        ages = {f"L{i}": {"ms": t0 + i * 5 * 60_000, "exact": True} for i in range(5)}        # п'ять за 20 хвилин
        ages.update({"C1": {"ms": t0 - 30 * 86_400_000, "exact": True}, "C2": {"ms": t0 - 60 * 86_400_000, "exact": True}})
        res = {"funders": launch, "services": ["BUNDLER"], "ages": ages}
        _bundles(res, [])
        self.assertEqual(sorted(res["bundle"]), sorted([f"L{i}" for i in range(5)] + ["C1", "C2"]))   # 5 з 7 пачкою: бандлер, усі
        self.assertEqual(res["bundle"]["C1"]["n"], 7)
        exch = {f"E{i}": "EXCH" for i in range(10)}                                 # біржа: 3 з 10 випадково разом
        ages = {f"E{i}": {"ms": t0 - i * 86_400_000, "exact": True} for i in range(10)}
        ages.update({"E0": {"ms": t0, "exact": True}, "E1": {"ms": t0 + 60_000, "exact": True}, "E2": {"ms": t0 + 120_000, "exact": True}})
        res = {"funders": exch, "services": ["EXCH"], "ages": ages}
        _bundles(res, [])
        self.assertEqual(sorted(res["bundle"]), ["E0", "E1", "E2"])
        with tempfile.TemporaryDirectory() as d:
            done = {"done": 1, "total": 1, "funders_done": 1}
            self._file(d, "unchecked", created_ms=1, result={"rows": [{"wallet": "w"}], "enrich": dict(done), "funders": {"w": "F"}})
            self._file(d, "checked", created_ms=2, result={"rows": [{"wallet": "w"}], "enrich": dict(done), "funders": {"w": "F"},
                                                         "services": [], "bundle_rev": 3})
            seen = []
            q = JobQueue(lambda j: None, d, enricher=lambda job, save: seen.append(job.id), enrich_upto=1)
            q.eq.join()
            self.assertEqual(seen, ["unchecked"])

    def test_a_replay_never_reaches_the_disk_and_charges_survive_a_restart(self):
        from tracced.web.jobs import JobQueue
        with tempfile.TemporaryDirectory() as d:
            q = JobQueue(lambda j: {"rows": []}, d)
            rep = q.submit("M" * 40, 1000, 2000, replay={"log": [], "result": {"rows": []}})
            q.rq.join()
            self.assertEqual(rep.status, "done")
            self.assertFalse(q._save(rep))
            live = q.submit("M" * 40, 1000, 2000, owner="pk", charged=["dev:x", "ip:y"])
            q.q.join()
            self.assertEqual(sorted(os.listdir(d)), [live.id + ".json"])       # лише справжній аналіз
            self.assertEqual(JobQueue(lambda j: None, d).get(live.id).charged, ["dev:x", "ip:y"])

    def test_delete_waits_for_a_save_in_flight(self):
        # збереження, що вже пройшло перевірку, не має повернути видалений файл: видалення чекає на той самий замок
        import threading
        import time as _t
        from tracced.web.jobs import JobQueue
        with tempfile.TemporaryDirectory() as d:
            q = JobQueue(lambda j: {"rows": []}, d)
            job = q.submit("M" * 40, 1000, 2000)
            q.q.join()
            path = os.path.join(d, job.id + ".json")
            with q._save_lock:
                t = threading.Thread(target=q.remove, args=(job.id,))
                t.start()
                _t.sleep(0.1)
                self.assertTrue(t.is_alive() and os.path.exists(path))
            t.join(2)
            self.assertFalse(os.path.exists(path))
            self.assertIsNone(q.get(job.id))

    def test_a_failed_funder_lookup_is_retried_not_marked_checked(self):
        from types import SimpleNamespace
        from tracced.web.app import make_enricher

        class Ages:
            fail = True

            def cached(self, w):
                return None

            def paused(self):
                return False

            def oldest_tx(self, w, refresh=False, full=True, before=None):
                return {"oldest_ms": 1000, "exact": True, "n": 2, "oldest_sig": "s-" + w}

            def funder(self, w, sig, scan=True):
                if self.fail and w == "W2":
                    raise RuntimeError("HTTP Error 429: Too Many Requests")
                return "F" + w

            def flush(self):
                pass
        ages = Ages()
        job = SimpleNamespace(result={"rows": [{"wallet": w, "first_buy_ms": 5000, "tag_list": []} for w in ("W1", "W2")]}, log=[])
        enrich = make_enricher(ages, {"age_lookups_max": 10})
        enrich(job, lambda j: True)
        r = job.result
        self.assertEqual((r["funder_checked"], r["enrich"]["funders_failed"]), (["W1"], 1))   # не «перевірено без спонсора»
        ages.fail = False
        enrich(job, lambda j: True)                                          # наступний прохід (після рестарту) доганяє
        self.assertEqual((r["funder_checked"], r["funders"]["W2"]), (["W1", "W2"], "FW2"))
        self.assertNotIn("funders_failed", r["enrich"])


if __name__ == "__main__":
    unittest.main()


# ───────────────────────── wallet sign-in and the account ─────────────────────────

if AioHTTPTestCase:
    import base64
    import os
    from tracced.web import accounts as acct_mod
    from tracced.web.app import Throttle

    try:
        from nacl.signing import SigningKey
    except ImportError:
        SigningKey = None

    DEMO_JID, DEMO_A, DEMO_B = "AAAAAA_20010909-0146_0206", 999999960000, 1000001160000
    W1 = acct_mod.b58encode(b"\x01" * 32)                       # гаманець у демо-результаті
    OTHER_MINT, OTHER_JID = "B" * 40, "BBBBBB_20010909-0146_0206"

    def _result(mint, a, b, wallet):
        return {"info": {"mint": mint, "symbol": "TST", "supply": 1000000, "created_time": 999996400000},
                "window": {"from": a, "to": b, "end": b + 3600000}, "mode": "wallet-trades",
                "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1, "dust": 0, "late": 0, "pre_range_only": 0,
                           "lookups": 1, "entry_only": 0},
                "coverage": {"exits_known": 1, "total": 1, "mode": "wallet-trades", "cost_full": 5, "lookup_cap": 500, "plan": "free"},
                "wallet_trades": {wallet: {"trades": [[a + 1000, "buy", 100.0, 100.0, 1.0], [b + 60000, "sell", 50.0, 150.0, 3.0]],
                                           "source": "wallet-trades"}},
                "price_at_end": 3.0, "fresh_wallets": [], "scope": "all", "rows": [], "summary": {},
                "requests": 0, "pages_fetched": 0, "enrich": {"done": 0, "total": 0, "fresh": 0, "failed": 0, "funders_done": 0}}

    def _job_file(out, jid, mint, a, b, result):
        with open(f"{out}/{jid}.json", "w") as f:
            json.dump({"id": jid, "mint": mint, "t_from": a, "t_to": b, "t_exit": None, "status": "done", "error": None,
                       "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "TST",
                       "progress": {"phase": "done", "done": 1, "total": 1}, "log": ["x"], "result": result}, f)

    def seed_demo(tmp, app):
        """Демо-токен зі знімка + його аналіз на диску, плюс один не-демо аналіз іншого токена."""
        result = _result(MINT, DEMO_A, DEMO_B, W1)
        os.makedirs(tmp + "/demo", exist_ok=True)
        with open(f"{tmp}/demo/{MINT}.json", "w") as f:
            json.dump({"mint": MINT, "info": result["info"], "created": 999996400000, "captured_ms": 1, "candles": {"1m": []},
                       "hints": [], "ranges": [{"label": "Pump 1", "from": DEMO_A, "to": DEMO_B, "job": DEMO_JID, "log": ["x"], "result": result}]}, f)
        _job_file(tmp + "/web", DEMO_JID, MINT, DEMO_A, DEMO_B, result)
        _job_file(tmp + "/web", OTHER_JID, OTHER_MINT, DEMO_A, DEMO_B, _result(OTHER_MINT, DEMO_A, DEMO_B, W1))
        app["jobs"]._load()
        app["s"]["demo_job"] = DEMO_JID
        app.pop("demo", None)

    @unittest.skipIf(SigningKey is None, "PyNaCl not installed")
    class TestAccount(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            s = settings.load()
            s["replay_s"] = 0.6
            return create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        @property
        def origin(self):
            return f"http://{self.client.host}:{self.client.port}"

        async def _sign_in(self, sk=None, domain=None):
            """nonce → підпис справжнім ключем → verify; повертає (відповідь, адреса, повідомлення, підпис)."""
            sk = sk or SigningKey.generate()
            pk = acct_mod.b58encode(bytes(sk.verify_key))
            r = await self.client.post("/auth/nonce", headers={"Origin": self.origin})
            self.assertEqual(r.status, 200)
            d = await r.json()
            msg = acct_mod.build_message(domain or d["domain"], pk, d["nonce"], d["issued_at"])
            sig = base64.b64encode(sk.sign(msg.encode()).signature).decode()
            r = await self.client.post("/auth/verify", json={"pubkey": pk, "signature": sig, "message": msg, "wallet": "Phantom"},
                                       headers={"Origin": self.origin})
            return r, pk, msg, sig

        def _hdr(self, r):
            """Куки явно в заголовку: тестовий клієнт не шле Secure-куки по http."""
            return {"Cookie": f"early_acct={r.cookies['early_acct'].value}", "Origin": self.origin}

        async def test_sign_in_sets_the_account(self):
            r, pk, _, _ = await self._sign_in()
            self.assertEqual(r.status, 200, await r.text())
            self.assertEqual((await r.json())["pubkey"], pk)
            c = r.cookies["early_acct"]
            self.assertTrue(c["httponly"] and c["secure"])
            self.assertTrue(os.path.exists(f"{self.tmp.name}/accounts/{pk}.json"))   # перший вхід = акаунт
            h = self._hdr(r)
            r = await self.client.get("/me.json", headers=h)
            self.assertEqual(r.status, 200)
            self.assertEqual((await r.json())["pubkey"], pk)
            r = await self.client.get("/me.json")
            self.assertEqual(r.status, 401)                                          # без куки — ні
            r = await self.client.get("/me", headers=h)
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn("Watchlist", html)
            self.assertIn("My analyses", html)
            self.assertIn(pk[:4] + "…" + pk[-4:], html)                              # пігулка в панелі
            self.assertIn("Sign out", html)
            self.assertIsNone(CYRILLIC.search(html))
            r = await self.client.get("/me")
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn("Connect a wallet", html)                                  # не увійшов — картка входу
            self.assertNotIn("Sign out", html)
            self.assertIsNone(CYRILLIC.search(html))
            r = await self.client.post("/auth/logout", headers=h)
            self.assertEqual(r.status, 200)
            self.assertEqual(r.cookies["early_acct"].value, "")

        async def test_bad_sign_ins_are_refused(self):
            r, pk, msg, sig = await self._sign_in()
            self.assertEqual(r.status, 200)
            r = await self.client.post("/auth/verify", json={"pubkey": pk, "signature": sig, "message": msg}, headers={"Origin": self.origin})
            self.assertEqual(r.status, 401)                                          # той самий nonce вдруге
            self.assertIn("expired", (await r.json())["error"])
            r, _, _, _ = await self._sign_in(domain="evil.example")
            self.assertEqual(r.status, 401)                                          # текст для іншого сайту
            self.assertIn("another site", (await r.json())["error"])
            r = await self.client.post("/auth/verify", json={"pubkey": pk, "signature": sig, "message": msg})
            self.assertEqual(r.status, 403)                                          # без Origin
            r = await self.client.post("/auth/nonce", headers={"Origin": "https://evil.example"})
            self.assertEqual(r.status, 403)
            sk = SigningKey.generate()
            r = await self.client.post("/auth/nonce", headers={"Origin": self.origin})
            d = await r.json()
            pk2 = acct_mod.b58encode(bytes(sk.verify_key))
            msg2 = acct_mod.build_message(d["domain"], pk2, d["nonce"], d["issued_at"])
            r = await self.client.post("/auth/verify", json={"pubkey": pk2, "signature": sig, "message": msg2}, headers={"Origin": self.origin})
            self.assertEqual(r.status, 401)                                          # чужий підпис
            self.assertIn("signature", (await r.json())["error"])
            r = await self.client.post("/auth/verify", data=b"not json", headers={"Origin": self.origin, "Content-Type": "application/json"})
            self.assertEqual(r.status, 400)
            self.assertFalse(os.path.exists(f"{self.tmp.name}/accounts/{pk2}.json"))

        async def test_sign_in_is_throttled(self):
            self.app["auth_throttle"] = Throttle(max_fails=2, window_s=300, block_s=900)
            for _ in range(2):
                r = await self.client.post("/auth/verify", json={"pubkey": "x", "signature": "y", "message": "z"}, headers={"Origin": self.origin})
                self.assertEqual(r.status, 401)
            r = await self.client.post("/auth/verify", json={"pubkey": "x", "signature": "y", "message": "z"}, headers={"Origin": self.origin})
            self.assertEqual(r.status, 429)
            r = await self.client.post("/auth/nonce", headers={"Origin": self.origin})
            self.assertEqual(r.status, 429)

        async def test_saving_from_results(self):
            seed_demo(self.tmp.name, self.app)
            if True:
                r = await self.client.get("/me", allow_redirects=False)
                self.assertEqual(r.status, 200)
                r, pk, _, _ = await self._sign_in()
                self.assertEqual(r.status, 200)
                h = self._hdr(r)
                r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1, "not-a-wallet"]}, headers=h)
                self.assertEqual(r.status, 200, await r.text())
                d = await r.json()
                self.assertEqual((d["added"], d["total"], d["skipped"]), (1, 1, 1))
                r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=h)
                self.assertEqual((await r.json())["added"], 0)                       # уже в списку
                r = await self.client.post("/me/analyses", json={"job": DEMO_JID}, headers=h)
                self.assertEqual(r.status, 200, await r.text())
                self.assertTrue((await r.json())["added"])
                r = await self.client.get("/me.json", headers=h)
                d = await r.json()
                self.assertEqual(d["wallets"][W1]["symbol"], "TST")
                self.assertEqual(d["wallets"][W1]["from_job"], DEMO_JID)
                self.assertEqual(d["analyses"][DEMO_JID]["n"], 1)
                r = await self.client.get("/me", headers=h)
                html = await r.text()
                self.assertIn(W1[:6] + "…" + W1[-4:], html)
                self.assertIn(f'href="/job/{DEMO_JID}"', html)
                self.assertIsNone(CYRILLIC.search(html))
                r = await self.client.get("/me/wallets.csv", headers=h)
                self.assertEqual(r.status, 200)
                self.assertIn(W1, await r.text())
                # будь-який готовий результат публічний — зберігати можна і з нього
                r = await self.client.post("/me/analyses", json={"job": OTHER_JID}, headers=h)
                self.assertEqual(r.status, 200, await r.text())
                r = await self.client.post("/me/wallets", json={"job": "nope", "wallets": [W1]}, headers=h)
                self.assertEqual(r.status, 404)
                # записи без куки або з чужого сайту — ні
                r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers={"Origin": self.origin})
                self.assertEqual(r.status, 401)
                r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=dict(h, Origin="https://evil.example"))
                self.assertEqual(r.status, 403)
                # видалення, власні теги, стеля
                r = await self.client.post("/me/wallets/tags", json={"wallet": W1, "tags": [" Insider ", "insider", "Bundle Op"]}, headers=h)
                self.assertEqual(r.status, 200)
                self.assertEqual((await r.json())["tags"], ["insider", "bundle op"])        # нижній регістр, без дублів
                self.assertEqual((await (await self.client.get("/me.json", headers=h)).json())["wallets"][W1]["my_tags"], ["insider", "bundle op"])
                r = await self.client.post("/me/wallets/tags", json={"wallet": W1, "tags": ["<script>", "ok"]}, headers=h)
                self.assertEqual((await r.json())["tags"], ["ok"])                           # розмітка тегом не стає
                r = await self.client.post("/me/wallets/tags", json={"wallet": W1, "tags": "nope"}, headers=h)
                self.assertEqual(r.status, 400)
                r = await self.client.post("/me/wallets/tags", json={"wallet": "B" * 43, "tags": ["x"]}, headers=h)
                self.assertEqual(r.status, 404)                                              # чужий гаманець не позначиш
                csv_body = await (await self.client.get("/me/wallets.csv", headers=h)).text()
                self.assertIn("my_tags", csv_body.splitlines()[0])
                self.assertIn("ok", csv_body)
                r = await self.client.post("/me/wallets/remove", json={"wallet": W1}, headers=h)
                self.assertTrue((await r.json())["ok"])
                r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=h)
                r = await self.client.post("/me/wallets/remove", json={"wallets": [W1, "nope"]}, headers=h)   # several at once
                self.assertEqual((await r.json())["removed"], 1)
                r = await self.client.get("/me/wallets.csv", headers=h)
                self.assertIn("watchlist.csv", r.headers["Content-Disposition"])
                r = await self.client.post("/me/analyses/remove", json={"job": DEMO_JID}, headers=h)
                self.assertTrue((await r.json())["ok"])
                old = acct_mod.MAX_ANALYSES
                acct_mod.MAX_ANALYSES = 0
                try:
                    r = await self.client.post("/me/analyses", json={"job": DEMO_JID}, headers=h)
                    self.assertEqual(r.status, 400)
                    self.assertIn("full", (await r.json())["error"])
                finally:
                    acct_mod.MAX_ANALYSES = old
                self.assertEqual(self.st.requests, 0)                                # усе це — без платних запитів

        async def test_pages_show_the_account_control(self):
            r = await self.client.get("/")
            html = await r.text()
            self.assertIn(">Connect</button>", html)                                 # герой головної
            self.assertNotIn('class="top"', html)
            r = await self.client.get(f"/token?mint={OTHER_MINT}")                  # живий токен без гаманця: графік є, Connect у шапці
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn(">Connect</button>", html)
            self.assertIn('data-acct="0"', html)
            self.assertIn("Analyze needs a connected wallet", html)
            self.assertIsNone(CYRILLIC.search(html))
            r, pk, _, _ = await self._sign_in()
            r = await self.client.get("/", headers=self._hdr(r))
            html = await r.text()
            self.assertIn(pk[:4] + "…" + pk[-4:], html)                              # the pill in the hero
            self.assertIn("Sign out", html)
            self.assertNotIn("My analyses (", html)                                  # no recent analyses → no link to count

        async def test_demo_ranges_are_fixed(self):
            seed_demo(self.tmp.name, self.app)
            html = await (await self.client.get(f"/token?mint={MINT}")).text()
            self.assertIn("Recorded ranges are fixed here", html)
            self.assertIn("data-wallet-signin", html)                          # the nudge points to Connect, not a password
            self.assertNotIn('id="add"', html)                                 # no new ranges on the demo
            self.assertNotIn('id="reset"', html)
            self.assertIsNone(CYRILLIC.search(html))
            r_in, pk, _, _ = await self._sign_in()
            html = await (await self.client.get(f"/token?mint={OTHER_MINT}", headers=self._hdr(r_in))).text()
            self.assertIn('id="add"', html)                                    # a live token keeps the full editor
            self.assertIn('data-max-rows="3"', html)

        async def test_the_agent_needs_a_wallet_and_keeps_its_limits(self):
            seed_demo(self.tmp.name, self.app)
            self.app["admins"] = set()
            calls = []

            class FakeAgent:
                model = "fake"

                def cards(self, result, cfg, lang):
                    calls.append(("cards", lang, cfg["v"]))
                    return {"story": ["1 wallet bought."], "risks": [], "watch": [], "method": "m", "model": "fake"}, [], {"cost": 0.001}

                def ask(self, result, cfg, q, lang):
                    calls.append(("ask", q, lang))
                    return {"on_topic": True, "answer": ["1 wallet bought."], "wallets": [], "model": "fake"}, [], {"cost": 0.001}
            self.app["agent"] = FakeAgent()
            try:
                o = {"Origin": self.origin}
                r = await self.client.post(f"/job/{DEMO_JID}/agent/cards", json={"lang": "uk-UA"}, headers=o)
                self.assertEqual(r.status, 401)                                # гостям агент закритий
                r_in, pk, _, _ = await self._sign_in()
                h = self._hdr(r_in)
                r = await self.client.post(f"/job/{DEMO_JID}/agent/cards", json={"lang": "uk-UA"}, headers=h)
                d = await r.json()
                self.assertEqual((r.status, d["cached"], d["left"]), (200, False, 10))
                self.assertIn("Was this a bundled launch?", d["chips"])
                r = await self.client.post(f"/job/{DEMO_JID}/agent/cards", json={"lang": "uk"}, headers=h)
                self.assertTrue((await r.json())["cached"])                    # ті самі картки — безкоштовно
                self.assertEqual(calls, [("cards", "Ukrainian", 0)])
                r = await self.client.post(f"/job/{DEMO_JID}/agent/ask", json={"q": "Who took 3x?", "chip": True, "lang": "en"}, headers=h)
                self.assertEqual(((await r.json())["left"], calls[-1]), (9, ("ask", "Who took 3x?", "English")))
                r = await self.client.post(f"/job/{DEMO_JID}/agent/ask", json={"q": "Хто тримає?"}, headers=h)
                self.assertEqual(calls[-1][2], "the language of the user's question")   # своє питання — його мовою
                self.app["s"]["agent_questions_per_day"] = 2
                r = await self.client.post(f"/job/{DEMO_JID}/agent/ask", json={"q": "more"}, headers=h)
                self.assertEqual(r.status, 429)
                self.assertIn("today's 2 questions", (await r.json())["error"])
                self.app["s"]["agent_questions_per_day"], self.app["s"]["agent_global_per_day"] = 10, 0
                r = await self.client.post(f"/job/{DEMO_JID}/agent/ask", json={"q": "more"}, headers=h)
                self.assertEqual(r.status, 429)
                self.app["s"]["agent_global_per_day"] = 300
                r = await self.client.post(f"/job/{DEMO_JID}/agent/ask", json={"q": "more"})
                self.assertEqual(r.status, 403)                                # чужий сайт не питає від імені людини
                self.assertEqual([e["event"] for e in self.app["events"].tail()][:1], ["agent"])
            finally:
                self.app["agent"] = None

        async def test_the_owner_writes_the_agents_method(self):
            seed_demo(self.tmp.name, self.app)
            r_user, _, _, _ = await self._sign_in()
            r_admin, pk_admin, _, _ = await self._sign_in()
            self.app["admins"] = {pk_admin}
            hu, ha = self._hdr(r_user), self._hdr(r_admin)
            try:
                r = await self.client.post("/admin/agent", json={"method": "Read bundles first."}, headers=hu)
                self.assertEqual(r.status, 403)
                r = await self.client.post("/admin/agent", json={"method": "Read bundles first.", "watch": {"n": 3}}, headers=ha)
                d = await r.json()
                self.assertEqual((d["config"]["v"], d["config"]["watch"]["n"]), (1, 3))
                r = await self.client.post("/admin/agent", json={"method": "Read exits first."}, headers=ha)
                self.assertEqual((await r.json())["config"]["v"], 2)
                self.assertEqual([h["v"] for h in self.app["agent_store"].history()], [2, 1])   # попередня версія лишилась
                seen = []

                class FakeAgent:
                    model = "fake"

                    def cards(self, result, cfg, lang):
                        seen.append((cfg["method"], cfg["v"], lang, result["info"]["mint"]))
                        return {"story": ["x"], "risks": [], "watch": [], "method": "m", "model": "fake"}, [], {"cost": 0.0007}
                self.app["agent"] = FakeAgent()
                r = await self.client.post("/admin/agent/preview", json={"config": {"method": "Try this."}, "lang": "uk"}, headers=ha)
                self.assertEqual(r.status, 200, await r.text())
                self.assertEqual(seen, [("Try this.", "preview", "Ukrainian", MINT)])   # спроба на демо, не збережена
                self.assertEqual(self.app["agent_store"].config()["method"], "Read exits first.")
                html = await (await self.client.get("/admin?tab=method", headers=ha)).text()
                self.assertIn("method v2", html)
                self.assertIn("Read exits first.", html)
                self.assertIsNone(CYRILLIC.search(html))
            finally:
                self.app["agent"], self.app["admins"] = None, set()

        async def test_admin_sees_accounts_and_actions(self):
            seed_demo(self.tmp.name, self.app)
            self.app["admins"] = set()                                           # a local .env may set ADMIN_WALLETS
            r_user, pk_user, _, _ = await self._sign_in()
            hu = self._hdr(r_user)
            await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=hu)
            await self.client.post("/me/analyses", json={"job": DEMO_JID}, headers=hu)
            acct = self.app["accounts"].load(pk_user)
            self.assertEqual((acct["signins"], acct["wallet_app"]), (1, "Phantom"))
            events = self.app["events"].tail()
            self.assertEqual([e["event"] for e in events], ["save_analysis", "save_wallets", "signin"])   # newest first
            self.assertEqual(events[1]["n"], 1)
            r = await self.client.get("/admin", headers=hu)
            self.assertEqual(r.status, 404)                                          # not configured → no such page
            r_admin, pk_admin, _, _ = await self._sign_in()
            self.app["admins"] = {pk_admin}
            r = await self.client.get("/admin", headers=hu)
            self.assertEqual(r.status, 403)                                          # another wallet
            r = await self.client.get("/admin")
            self.assertEqual(r.status, 403)                                          # nobody
            r = await self.client.get("/admin", headers=self._hdr(r_admin))
            html = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn('data-count="2"', html)                                    # two accounts
            html = await (await self.client.get("/admin?tab=log", headers=self._hdr(r_admin))).text()
            self.assertIn(pk_user[:6] + "…" + pk_user[-4:], html)
            self.assertIn("saved 1 wallet from", html)
            self.assertIn("saved the analysis", html)
            html = await (await self.client.get("/admin?tab=wallets", headers=self._hdr(r_admin))).text()
            self.assertIn("Phantom", html)
            for tab in ("overview", "analyses", "agent", "wallets", "behavior", "costs", "log", "method"):
                html = await (await self.client.get(f"/admin?tab={tab}", headers=self._hdr(r_admin))).text()
                self.assertIsNone(CYRILLIC.search(html), tab)
            self.app["admins"] = set()
