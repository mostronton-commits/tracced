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
                r = await self.client.post("/analyze", allow_redirects=False, data={
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
            for el in ('id="dtags"', 'id="dident"', 'id="dprof"', 'id="dwinfo"', 'id="dstar"', 'id="dcopy"',
                       'id="dfacts"', 'id="dcross"', 'id="dtrades"', 'id="dnote"', 'id="dclose"'):
                self.assertIn(el, html)                                    # картка гаманця: секції, на які спирається скрипт
            self.assertIn('class="button wl" id="watchbtn"', html)
            self.assertIn("data-invsol=", html)                            # рядок таблиці несе суми в SOL
            self.assertIn("data-sol=", html)                               # і плитка «Spent in range» теж
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
            r = await self.client.post("/analyze", allow_redirects=False, headers=GUEST, data={
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
                                 "ages": {w: {"ms": 999000000000, "exact": True}},
                                 "identities": {w: {"name": "Cented", "twitter": "@Cented7", "type": "kol"}}}}
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump(stored, f)
            self.app["jobs"]._load()
            d = await (await self.client.get(f"/job/{jid}.enrich.json")).json()
            self.assertEqual(d["ages"][w]["ms"], 999000000000)
            self.assertEqual(d["identities"][w]["twitter"], "@Cented7")

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
            self.assertEqual(r.status, 429)                             # стеля сайту на добу
            self.assertIn("whole site", await r.text())
            self.app["s"]["runs_global_per_day"] = 10
            self.app["admins"] = {TEST_PK}

        async def test_demo_replay_keeps_the_stored_analysis_in_place(self):
            jid, a, b = self._seed_one_demo()
            r = await self.client.post("/analyze", allow_redirects=False, headers=GUEST,
                                       data={"mint": MINT, "from": chart.to_input(a), "to": chart.to_input(b)})
            rid = r.headers["Location"].split("/")[-1]
            self.assertTrue(rid.startswith(jid + "_r") and rid != jid, rid)
            self.assertEqual(self.app["jobs"].get(jid).status, "done")   # збережений аналіз нікуди не дівся…
            r = await self.client.get(f"/job/{jid}.csv", headers=GUEST)
            self.assertEqual(r.status, 200)                              # …і читається, поки демо програється
            await asyncio.to_thread(self.app["jobs"].q.join)
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
            self.assertEqual(r.status, 429)                              # друга за день — ні
            body = await r.text()
            self.assertIn("today", body)
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
            r = await self.client.post(f"/job/{jid}/assistant", json={"method": "x"}, allow_redirects=False,
                                       headers={"Origin": f"http://{self.client.host}:{self.client.port}", "Cookie": ""})
            self.assertIn(r.status, (404, 503))                          # the demo's agent answers guests too

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
            self.assertIn(f">{self.app['s']['max_wallet_lookups']}<", lim)

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
            self.assertIn("Whole history", html)                         # scope switch
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
            self.assertIn("48 h after range", page48)
            self.assertIn('class="on" href="?scope=48h"', page48)
            self.assertIn("+ Watchlist", page48)                        # the real save, no placeholder
            self.assertIn("Save analysis", page48)
            self.assertNotIn("Add to watchlist", page48)
            self.assertNotIn("soon-badge", page48)
            self.assertIn("Sold out", page48)                           # tiles renamed, with hints
            self.assertIn("← Adjust the range", page48)                 # in the header now
            r = await self.client.get("/wallet_trades.json?job=" + loc.split("/")[-1] + "&wallet=A")
            self.assertEqual(r.status, 400)                              # not a base58 wallet in tests → readable error
            o = {"Origin": f"http://{self.client.host}:{self.client.port}"}
            r = await self.client.post(loc + "/assistant", json={"method": "x"}, headers=o)   # assistant: not configured → 503 with a readable reason
            self.assertEqual(r.status, 503)
            self.assertIn("ASSISTANT_KEY", (await r.json())["error"])

            class FakeAssistant:
                model = "fake"
                def ask(self, rows, method):
                    assert rows and method == "only profitable"
                    return {"picks": [{"wallet": rows[0]["wallet"], "reason": "realized profit"}], "note": "", "model": "fake"}
            self.app["assistant"] = a = FakeAssistant()
            r = await self.client.post(loc + "/assistant", json={"method": "only profitable", "wallets": ["A"]})
            self.assertEqual(r.status, 403)                              # JSON writes need the page's own origin
            r = await self.client.post(loc + "/assistant", json={"method": "only profitable", "wallets": ["A"]}, headers=o)
            self.assertEqual(r.status, 200)
            aj = await r.json()
            self.assertEqual(aj["picks"][0]["wallet"], "A")
            self.assertEqual(aj["left"], 9)                               # a wallet gets 10 a day (guests 3)
            r = await self.client.post(loc + "/assistant", json={"method": "only profitable", "wallets": ["A"]}, headers=o)
            self.assertTrue((await r.json()).get("cached"))
            self.assertIn("AI agent", page48)
            self.assertEqual(page48.count("<b>Coming soon</b>"), 1)          # no key on this server: the button says so
            self.app["assistant"] = None                                 # …and then the home page must not promise it either
            home_off = await (await self.client.get("/")).text()
            self.assertIn("Coming next", home_off)
            self.assertNotIn("Live on every result", home_off)
            self.assertIn("The agent is off on this server", await (await self.client.get("/docs/roadmap")).text())
            self.app["assistant"] = a
            home_on = await (await self.client.get("/")).text()
            self.assertIn("Live on every result", home_on)               # with a key the promise is true
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


if AioHTTPTestCase:
    class FakeAgesWeb:
        """Вік і спонсор без мережі: рахує виклики, як нода рахувала б кредити."""
        def __init__(self):
            self.calls, self.cache = 0, {}

        def cached(self, w):
            return self.cache.get(w)

        def paused(self):
            return False

        def oldest_tx(self, w, refresh=False):
            if w not in self.cache:
                self.calls += 1
                self.cache[w] = {"oldest_ms": 999_990_000_000, "exact": True, "n": 3, "oldest_sig": "sig-" + w[:4]}
            return self.cache[w]

        def funder(self, w, sig):
            self.calls += 1
            return "F" * 44

        def flush(self):
            pass

    class TestLazyWalletAge(AioHTTPTestCase):
        """Вік і спонсор гаманця поза першими за PnL перевіряються, коли відкрили його картку, і лишаються в результаті."""

        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.ages = FakeAgesWeb()
            s = settings.load()
            s["age_lookups_max"] = 0                                      # аналіз сам нікого не перевіряє
            self.st = FakeWebST(TRADES)
            return create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache", ages=self.ages)

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
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

        async def test_assistant_daily_budget(self):
            seed_demo(self.tmp.name, self.app)

            class FakeAssistant:
                model = "fake"
                def ask(self, rows, method):
                    return {"picks": [{"wallet": rows[0]["wallet"], "reason": method}], "note": "", "model": "fake"}
            self.app["assistant"] = FakeAssistant()
            o = {"Origin": self.origin}
            for i in range(3):                                             # three different questions a day for a guest
                r = await self.client.post(f"/job/{DEMO_JID}/assistant", json={"method": f"m{i}"}, headers=o)
                self.assertEqual(r.status, 200, await r.text())
                self.assertEqual((await r.json())["left"], 2 - i)
            r = await self.client.post(f"/job/{DEMO_JID}/assistant", json={"method": "m0"}, headers=o)
            self.assertTrue((await r.json())["cached"])                    # a repeat is free
            r = await self.client.post(f"/job/{DEMO_JID}/assistant", json={"method": "m9"}, headers=o)
            self.assertEqual(r.status, 429)
            self.assertIn("connect a wallet", (await r.json())["error"])
            r_in, pk, _, _ = await self._sign_in()                          # a wallet has its own, bigger budget
            r = await self.client.post(f"/job/{DEMO_JID}/assistant", json={"method": "m9"}, headers=self._hdr(r_in))
            self.assertEqual(r.status, 200)
            self.assertEqual((await r.json())["left"], 9)
            self.app["s"]["assistant_global_per_day"] = 0
            r = await self.client.post(f"/job/{DEMO_JID}/assistant", json={"method": "m10"}, headers=self._hdr(r_in))
            self.assertEqual(r.status, 429)
            self.assertIn("daily budget", (await r.json())["error"])
            self.app["s"]["assistant_global_per_day"] = 45
            self.assertEqual([e["event"] for e in self.app["events"].tail()][:1], ["assistant"])
            self.app["assistant"] = None

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
            self.assertIn(pk_user[:6] + "…" + pk_user[-4:], html)
            self.assertIn("Phantom", html)
            self.assertIn("saved 1 wallet from", html)
            self.assertIn("saved the analysis", html)
            self.assertIn('data-count="2"', html)                                    # two accounts
            self.assertIsNone(CYRILLIC.search(html))
            self.app["admins"] = set()
