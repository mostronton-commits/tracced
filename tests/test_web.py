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
            self.assertIn("That range is not recorded.", await r.text())
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
            self.assertIn("Add to watchlist", page48)
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
            self.assertEqual(page48.count("<b>Coming next</b>"), 2)         # the same wording on both announcements
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
