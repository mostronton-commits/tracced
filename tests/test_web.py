"""The web page on a fake client: no network. Needs aiohttp (present in Docker)."""
import asyncio
import json
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
    def chart(self, mint, interval, t_from, t_to):
        self.requests += 1
        # ×10 vs trades: with supply 1e6 the cap goes 1M→6M, above min_peak_mcap, so the detector hints
        closes = [1.0] * 40 + [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0] + [6.0] * 20
        return [{"time": T0 - H + i * MIN, "open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1}
                for i, c in enumerate(closes)]


if AioHTTPTestCase:
    from tracced.web import chart
    from tracced.web.app import create_app

    class TestWeb(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            return create_app(self.st, settings.load(), {}, out_dir=self.tmp.name + "/web",
                              store_dir=self.tmp.name + "/cache")

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)      # let the worker finish writing
            self.tmp.cleanup()

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
            self.assertIn("Demo token.", html)
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
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"}, allow_redirects=False)
            self.assertEqual(r.status, 302)
            loc = r.headers["Location"]
            html = ""
            for _ in range(80):
                r = await self.client.get(loc); html = await r.text()
                if "↓ Export" in html: break
                await asyncio.sleep(0.1)
            self.assertIn("↓ Export", html)
            self.assertIn("Whole history", html)
            self.assertEqual(self.st.requests, before)                    # not a single request to Solana Tracker
            st = await (await self.client.get(loc + ".state.json?since=0")).json()
            self.assertIn("page 1: 3 trades (+3 new)", st["log"])
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
            self.assertIn("These ranges are", html)                        # текст знає, що діапазонів кілька
            for jid, a, b in (one, two):                                   # обидва програються
                r = await self.client.post("/analyze", allow_redirects=False, data={
                    "mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)})
                self.assertEqual(r.headers["Location"], f"/job/{jid}")
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
            self.assertIn("Demo token.", await r.text())
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T05:00", "to": "2001-09-09T05:20"}, allow_redirects=False)
            self.assertEqual(r.headers["Location"], f"/token?mint={MINT}&notice=demo")
            self.assertEqual(self.st.requests, before)                         # жодного платного запиту

        async def test_login_slows_down_guessing(self):
            # публічний сайт + короткий пароль: після кількох промахів адреса чекає, і правильний пароль теж не пускає
            from tracced.web.app import Throttle
            t = Throttle(max_fails=3, window_s=300, block_s=60)
            self.assertEqual(t.wait_s("1.2.3.4", 0), 0)
            self.assertEqual((t.miss("1.2.3.4", 0), t.miss("1.2.3.4", 1)), (0, 0))
            self.assertEqual(t.miss("1.2.3.4", 2), 60)                     # третій промах — пауза
            self.assertEqual(t.wait_s("1.2.3.4", 30), 32)                 # блок від моменту промаху (t=2)
            self.assertEqual(t.wait_s("5.6.7.8", 30), 0)                   # інша адреса не страждає
            self.assertEqual(t.wait_s("1.2.3.4", 100), 0)                  # пауза минула
            t.miss("9.9.9.9", 0); t.hit("9.9.9.9")
            self.assertEqual(t.wait_s("9.9.9.9", 0), 0)                    # правильний пароль очищає лічильник
            t2 = Throttle(max_fails=1, window_s=300, block_s=60)
            self.assertGreater(t2.miss("a", 0), 0)
            self.assertGreater(t2.miss("a", 1), 60)                        # кожна наступна спроба довша

        async def test_login_blocks_after_wrong_passwords(self):
            from tracced.web.app import Throttle
            self.app["password"], self.app["throttle"] = "test-only-not-a-real-password", Throttle(max_fails=2, window_s=300, block_s=900)
            try:
                r = await self.client.get("/")                             # без куки — на сторінку входу
                self.assertIn("Sign in", await r.text())
                for _ in range(2):
                    r = await self.client.post("/login", data={"password": "0000"}, allow_redirects=False)
                    self.assertEqual(r.status, 401)
                r = await self.client.post("/login", data={"password": "test-only-not-a-real-password"}, allow_redirects=False)
                self.assertEqual(r.status, 429)                            # навіть правильний пароль чекає
                self.assertIn("Too many attempts", await r.text())
            finally:
                self.app["password"], self.app["throttle"] = "", Throttle()

        async def test_layout_containers(self):
            # верстка тримається на трьох речах: смуги шапки/підвалу з внутрішнім контейнером і широка сторінка результату
            for path in ("/", "/how"):
                html = await (await self.client.get(path)).text()
                self.assertIn('<footer class="foot"><div class="foot-in">', html)
            html = await (await self.client.get("/how")).text()
            self.assertIn('<header class="top"><div class="top-in">', html)
            self.assertNotIn('<main class="wide"', html)
            await self.client.get(f"/token?mint={MINT}")
            r = await self.client.post("/analyze", data={"mint": MINT, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"},
                                       allow_redirects=False)
            html = await (await self.client.get(r.headers["Location"])).text()
            self.assertIn('<main class="wide"', html)                      # таблиці потрібна ширина

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

        async def test_public_surface_is_exactly_the_demo(self):
            # без пароля відкриті лише сторінка проєкту і демо-токен; усе, що витрачає гроші, закрите
            import os
            from tracced.web.app import Throttle
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
            out = self.tmp.name + "/web"
            with open(f"{out}/{jid}.json", "w") as f:                      # сам аналіз теж має бути на диску
                json.dump({"id": jid, "mint": MINT, "t_from": a, "t_to": b, "t_exit": None, "status": "done",
                           "error": None, "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "TST",
                           "progress": {"phase": "done", "done": 1, "total": 1}, "log": ["x"], "result": result}, f)
            self.app["jobs"]._load()
            self.app["s"]["demo_job"] = jid; self.app.pop("demo", None)
            self.app["password"], self.app["throttle"] = "test-only-not-a-real-password", Throttle()
            other = "B" * 40
            try:
                before = self.st.requests
                for path in ("/project", f"/token?mint={MINT}", f"/job/{jid}", f"/job/{jid}.csv"):
                    r = await self.client.get(path, allow_redirects=False)
                    self.assertEqual(r.status, 200, path)                  # відкрито
                for path in ("/", "/how", f"/token?mint={other}", "/job/whatever"):
                    r = await self.client.get(path, allow_redirects=False)
                    self.assertEqual(r.headers.get("Location"), "/login", path)   # закрито
                r = await self.client.post("/analyze", allow_redirects=False, data={
                    "mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)})
                self.assertEqual(r.headers["Location"], f"/job/{jid}")      # демо програється без пароля
                r = await self.client.post("/analyze", allow_redirects=False, data={
                    "mint": other, "from": "2001-09-09T01:46", "to": "2001-09-09T02:06"})
                self.assertEqual(r.headers["Location"], "/login")           # чужий токен — ні
                self.assertEqual(self.st.requests, before)                  # жодного платного запиту
            finally:
                self.app["password"], self.app["throttle"] = "", Throttle()

        async def test_open_surface_cannot_be_unlocked_by_the_wrong_parameter(self):
            # кожен шлях має перевірятись по тому самому параметру, який читає його обробник
            import os
            from tracced.web.app import Throttle
            jid, a, b = "AAAAAA_20010909-0146_0206", 999999960000, 1000001160000
            other, other_job = "B" * 40, "BBBBBB_20010909-0300_0320"
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
            self.app["s"]["demo_job"] = jid; self.app.pop("demo", None)
            self.app["password"], self.app["throttle"] = "pw", Throttle()
            try:
                before = self.st.requests
                # відмикання чужим параметром: job демо + чужий mint, і навпаки
                for path in (f"/token?mint={other}&job={jid}",
                             f"/candles.json?mint={other}&job={jid}&tf=1h&a=1&b=9999999999",
                             f"/wallet_trades.json?mint={MINT}&job={other_job}&wallet=A",
                             f"/job/{jid}/assistant"):
                    r = await self.client.get(path, allow_redirects=False)
                    self.assertEqual(r.headers.get("Location"), "/login", path)
                r = await self.client.post(f"/job/{jid}/assistant", json={"method": "x"}, allow_redirects=False)
                self.assertEqual(r.headers.get("Location"), "/login")
                self.assertEqual(self.st.requests, before)              # жодного платного запиту
            finally:
                self.app["password"], self.app["throttle"] = "", Throttle()

        async def test_how_page(self):
            r = await self.client.get("/how")
            self.assertEqual(r.status, 200)
            html = await r.text()
            self.assertIn("How it works", html)
            self.assertIn("bot-like", html)                              # tag definitions listed
            self.assertIn("Where the data comes from", html)
            self.assertIsNone(CYRILLIC.search(html))

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
            self.assertIn("Paste contract", html)
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
            self.assertIn("Pump 1", html)                              # a detector hint became a row
            self.assertIn('id="chart"', html)
            self.assertIn("lightweight-charts", html)
            self.assertIn("static/chart.js", html)
            self.assertIn("and analyze", html)
            self.assertNotIn("<svg", html)

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
            self.assertIn("Hide tags:", html)
            self.assertIn("Exits known for", html)                       # coverage line
            self.assertIn("Whole history", html)                         # scope switch
            self.assertIn("Trades up to", html)
            self.assertIn("Select all", html)
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
            self.assertIn("48 h after range", page48)
            self.assertIn('class="on" href="?scope=48h"', page48)
            self.assertIn("Save to my list", page48)                    # the real save, no placeholder
            self.assertIn("Save analysis", page48)
            self.assertNotIn("Add to watchlist", page48)
            self.assertNotIn("soon-badge", page48)
            self.assertIn("Sold out", page48)                           # tiles renamed, with hints
            self.assertIn("← Adjust the range", page48)                 # in the header now
            r = await self.client.get("/wallet_trades.json?job=" + loc.split("/")[-1] + "&wallet=A")
            self.assertEqual(r.status, 400)                              # not a base58 wallet in tests → readable error
            r = await self.client.post(loc + "/assistant", json={"method": "x"})   # assistant: not configured → 503 with a readable reason
            self.assertEqual(r.status, 503)
            self.assertIn("ASSISTANT_KEY", (await r.json())["error"])

            class FakeAssistant:
                model = "fake"
                def ask(self, rows, method):
                    assert rows and method == "only profitable"
                    return {"picks": [{"wallet": rows[0]["wallet"], "reason": "realized profit"}], "note": "", "model": "fake"}
            self.app["assistant"] = FakeAssistant()
            r = await self.client.post(loc + "/assistant", json={"method": "only profitable", "wallets": ["A"]})
            self.assertEqual(r.status, 200)
            aj = await r.json()
            self.assertEqual(aj["picks"][0]["wallet"], "A")
            r = await self.client.post(loc + "/assistant", json={"method": "only profitable", "wallets": ["A"]})
            self.assertTrue((await r.json()).get("cached"))
            self.assertIn("AI agent", page48)
            self.assertEqual(page48.count("<b>Coming next</b>"), 1)         # only the AI agent is still announced
            r = await self.client.get("/")                               # home with a finished analysis: counters, sample, bg lines
            self.assertEqual(r.status, 200)
            home = await r.text()
            self.assertIn(">Example<", home)                             # the finished analysis is pinned as the example
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
            self.assertEqual(r.status, 200)
            self.assertEqual((await r.json())["trades"], [])
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


if __name__ == "__main__":
    unittest.main()


# ───────────────────────── wallet sign-in and the account ─────────────────────────

if AioHTTPTestCase:
    import base64
    import os
    from tracced.web import accounts as acct_mod
    from tracced.web.app import Throttle, _sign

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
            return create_app(self.st, settings.load(), {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
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

        def _hdr(self, r, password=None):
            """Куки явно в заголовку: тестовий клієнт не шле Secure-куки по http."""
            cookie = f"early_acct={r.cookies['early_acct'].value}"
            if password:
                cookie += f"; early_web={_sign(password, 4_000_000_000)}"
            return {"Cookie": cookie, "Origin": self.origin}

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
            self.assertIn("My list", html)
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

        async def test_saving_from_the_demo_needs_no_password(self):
            seed_demo(self.tmp.name, self.app)
            self.app["password"], self.app["throttle"] = "test-only-not-a-real-password", Throttle()
            try:
                r = await self.client.get("/me", allow_redirects=False)
                self.assertEqual(r.status, 200)                                      # акаунт відкритий і за паролем
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
                # чужий (платний) аналіз без пароля бети — ні; з паролем — так
                r = await self.client.post("/me/wallets", json={"job": OTHER_JID, "wallets": [W1]}, headers=h)
                self.assertEqual(r.status, 403)
                r = await self.client.post("/me/analyses", json={"job": OTHER_JID}, headers=h)
                self.assertEqual(r.status, 403)
                r2, pk, _, _ = await self._sign_in()
                hp = self._hdr(r2, "test-only-not-a-real-password")
                r = await self.client.post("/me/analyses", json={"job": OTHER_JID}, headers=hp)
                self.assertEqual(r.status, 200, await r.text())
                r = await self.client.post("/me/wallets", json={"job": "nope", "wallets": [W1]}, headers=hp)
                self.assertEqual(r.status, 404)
                # записи без куки або з чужого сайту — ні
                r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers={"Origin": self.origin})
                self.assertEqual(r.status, 401)
                r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=dict(h, Origin="https://evil.example"))
                self.assertEqual(r.status, 403)
                # видалення, нотатка, стеля
                r = await self.client.post("/me/wallets/note", json={"wallet": W1, "note": "watch"}, headers=h)
                self.assertEqual(r.status, 200)
                self.assertEqual((await (await self.client.get("/me.json", headers=h)).json())["wallets"][W1]["note"], "watch")
                r = await self.client.post("/me/wallets/remove", json={"wallet": W1}, headers=h)
                self.assertTrue((await r.json())["ok"])
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
            finally:
                self.app["password"], self.app["throttle"] = "", Throttle()

        async def test_pages_show_the_account_control(self):
            r = await self.client.get("/")
            html = await r.text()
            self.assertIn(">Connect</button>", html)                                 # герой головної
            self.assertNotIn('class="top"', html)
            r = await self.client.get("/login")
            html = await r.text()
            self.assertIn(">Connect</button>", html)
            self.assertIn("private beta", html)
            self.assertIsNone(CYRILLIC.search(html))
            r, pk, _, _ = await self._sign_in()
            r = await self.client.get("/", headers=self._hdr(r))
            html = await r.text()
            self.assertIn(pk[:4] + "…" + pk[-4:], html)                              # the pill in the hero
            self.assertIn("Sign out", html)
            self.assertNotIn("My analyses (", html)                                  # no recent analyses → no link to count

        async def test_admin_sees_accounts_and_actions(self):
            seed_demo(self.tmp.name, self.app)
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
            self.assertIn(pk_user[:6] + "…" + pk_user[-4:], html)
            self.assertIn("Phantom", html)
            self.assertIn("saved 1 wallet from", html)
            self.assertIn("saved the analysis", html)
            self.assertIn('data-count="2"', html)                                    # two accounts
            self.assertIsNone(CYRILLIC.search(html))
            self.app["admins"] = set()
