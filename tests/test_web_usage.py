"""Журнал для дашборда власника на фейковому клієнті: перегляди, прогони, витрати, агент, ліміти. Без мережі."""
import asyncio
import json
import tempfile
import unittest

try:
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # хост без aiohttp: тести сторінок пропускаються
    AioHTTPTestCase = None

from tracced.early import settings

try:
    from tests.test_early_pipeline import TRADES
except ImportError:                       # discover -s tests без -t: модулі без префікса пакета
    from test_early_pipeline import TRADES

if AioHTTPTestCase:
    try:
        from tests.test_web import FakeWebST, MINT, GUEST, TEST_PK, wallet_cookie, seed_demo, DEMO_JID, W1
    except ImportError:
        from test_web import FakeWebST, MINT, GUEST, TEST_PK, wallet_cookie, seed_demo, DEMO_JID, W1
    from tracced.early.assistant import AssistantError
    from tracced.web import accounts as acct_mod
    from tracced.web.app import create_app

    class TestUsageLog(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            self.st = FakeWebST(TRADES)
            s = settings.load()
            s["replay_s"] = 0.6
            s["ranges_per_token"] = 50
            app = create_app(self.st, s, {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            return app

        async def setUpAsync(self):
            await super().setUpAsync()
            self.client.session.headers["Cookie"] = wallet_cookie(TEST_PK)

        async def tearDownAsync(self):
            await asyncio.to_thread(self.app["jobs"].q.join)
            await asyncio.to_thread(self.app["jobs"].rq.join)
            await self.client.close()
            self.tmp.cleanup()

        @property
        def origin(self):
            return {"Origin": f"http://{self.client.host}:{self.client.port}"}

        def lines(self, event=None, **match):
            return [e for e in self.app["events"].read()
                    if (event is None or e["event"] == event) and all(e.get(k) == v for k, v in match.items())]

        def _seed_listed(self):
            """Аналіз одного гаманця (як у тесті картки): 30 днів цього гаманця коштують 1 запит."""
            jid, mint, listed = "EEEEEE_20010909-0146_0206", "E" * 40, acct_mod.b58encode(b"\x05" * 32)
            stored = {"id": jid, "mint": mint, "t_from": 999999960000, "t_to": 1000001160000, "t_exit": None, "status": "done",
                      "error": None, "created_ms": 1, "started_ms": 1, "finished_ms": 2, "symbol_hint": "EEE", "log": [],
                      "progress": {"phase": "done", "done": 1, "total": 1},
                      "result": {"info": {"mint": mint, "symbol": "EEE", "supply": 1000000, "created_time": 999996400000},
                                 "window": {"from": 999999960000, "to": 1000001160000, "end": 1000003560000}, "mode": "wallet-trades",
                                 "counts": {"n_wallets": 1, "n_trades": 3, "n_early": 1}, "wallet_trades": {},
                                 "coverage": {"exits_known": 0, "total": 1, "mode": "wallet-trades"},
                                 "rows": [{"wallet": listed}], "scope": "all", "requests": 0}}
            with open(f"{self.tmp.name}/web/{jid}.json", "w") as f:
                json.dump(stored, f)
            self.app["jobs"]._load()
            return jid, listed

        async def test_views_are_written_for_wallets_only_and_a_reload_is_one_view(self):
            seed_demo(self.tmp.name, self.app)
            await self.client.get("/", headers=GUEST)
            self.assertEqual(self.lines("view"), [])                     # гостей рахує Umami
            for path in ("/", "/", f"/token?mint={MINT}", f"/job/{DEMO_JID}", "/me", "/docs/limits"):
                r = await self.client.get(path)
                self.assertEqual(r.status, 200, path)
            views = self.lines("view")
            self.assertEqual([(v["page"], v.get("ref")) for v in views],
                             [("home", None), ("token", MINT), ("job", DEMO_JID), ("me", None), ("docs", "limits")])
            self.assertEqual((views[1].get("demo"), views[2].get("state"), views[2].get("demo"), views[0]["dev"]), (1, "done", 1, "d"))
            self.assertEqual({v["pubkey"] for v in views}, {TEST_PK})
            self.assertEqual(self.app["events"].tail(), [])               # «Recent actions» — лише дії
            r = await self.client.get("/docs/account", headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Mobile"})
            self.assertEqual(r.status, 200)
            self.assertEqual((self.lines("view")[-1]["ref"], self.lines("view")[-1]["dev"]), ("account", "m"))   # з телефона

        async def test_the_daily_cap_stops_view_lines(self):
            self.app["s"]["usage_events_per_day"] = 2
            for path in ("/", "/me", "/docs/limits"):
                await self.client.get(path)
            self.assertEqual(len(self.lines("view")), 2)

        async def test_a_run_line_says_what_the_run_spent_even_when_it_failed(self):
            rng = lambda h: {"mint": MINT, "from": f"2001-09-09T{h}", "to": "2001-09-09T02:06"}  # noqa: E731
            self.st.fail_trades = True                                  # стрічка лежить: прогін падає, але вже щось витратив
            r = await self.client.post("/analyze", data=rng("01:50"), allow_redirects=False)
            self.assertEqual(r.status, 302, await r.text())
            await asyncio.to_thread(self.app["jobs"].q.join)
            self.st.fail_trades = False
            bad = self.app["jobs"].get(r.headers["Location"].split("/")[-1])
            r = await self.client.post("/analyze", data=rng("01:46"), allow_redirects=False)
            await asyncio.to_thread(self.app["jobs"].q.join)
            good = self.app["jobs"].get(r.headers["Location"].split("/")[-1])
            runs = {e["job"]: e for e in self.lines("run")}
            self.assertEqual((runs[good.id]["ok"], runs[good.id]["st"], runs[good.id]["pubkey"]), (1, good.spent, TEST_PK))
            self.assertGreater(good.spent, 0)
            self.assertEqual((runs[good.id]["rows"], runs[good.id]["symbol"]), (len(good.result["rows"]), good.symbol))
            self.assertEqual((runs[bad.id]["ok"], runs[bad.id]["st"]), (0, bad.spent))
            self.assertTrue(runs[bad.id]["err"])
            self.assertEqual([e["event"] for e in self.app["events"].tail()], ["analyze", "analyze"])
            self.assertEqual([(e["pubkey"], e["mint"]) for e in self.lines("spend", what="overview")], [(TEST_PK, MINT)])   # огляд — раз, далі з кешу

        async def test_card_and_chart_credits_go_to_whoever_asked(self):
            jid, listed = self._seed_listed()
            for _ in range(2):
                r = await self.client.get(f"/wallet_profile.json?job={jid}&wallet={listed}")
                self.assertEqual(r.status, 200)
            self.assertEqual([(e["pubkey"], e["st"], e["job"]) for e in self.lines("spend", what="card-profile")],
                             [(TEST_PK, 1, jid)])                         # вдруге з кешу — нічого не коштує
            mint = "F" * 40
            r = await self.client.get(f"/candles.json?mint={mint}&tf=1h&a=1&b=9999999999", headers=GUEST)
            self.assertEqual(r.status, 200, await r.text())
            paid = [e for e in self.lines("spend") if e.get("mint") == mint]
            self.assertEqual({(e["pubkey"], e["what"]) for e in paid}, {("guest", "overview"), ("guest", "chart")})
            self.assertTrue(all(e["st"] > 0 for e in paid))

        async def test_agent_lines_carry_the_cost_the_cache_and_the_suggested_question(self):
            seed_demo(self.tmp.name, self.app)
            self.app["admins"] = set()                                   # стелі агента — як у людей

            class FakeAgent:
                model = "fake"

                def cards(self, result, cfg, lang):
                    return ({"story": ["1 wallet bought."], "risks": [], "watch": [], "method": "m", "model": "fake"}, [],
                            {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.001})

                def ask(self, result, cfg, q, lang):
                    if q == "boom":
                        raise AssistantError("The agent's model is busy right now.", {"prompt_tokens": 90, "completion_tokens": 0, "cost": 0.0005})
                    return ({"on_topic": q != "a poem", "answer": ["1 wallet bought."], "wallets": [], "model": "fake"},
                            [{"why": "x", "text": "y"}], {"prompt_tokens": 80, "completion_tokens": 10, "cost": 0.0002})
            self.app["agent"] = FakeAgent()
            try:
                chip = self.app["agent_store"].config()["chips"][0]
                for _ in range(2):
                    r = await self.client.post(f"/job/{DEMO_JID}/agent/cards", json={"lang": "en"}, headers=self.origin)
                    self.assertEqual(r.status, 200)
                for q, is_chip in ((chip, True), ("who held?", False), ("a poem", False), ("boom", False)):
                    await self.client.post(f"/job/{DEMO_JID}/agent/ask", json={"q": q, "chip": is_chip, "lang": "en"}, headers=self.origin)
                self.app["s"]["agent_questions_per_day"] = 1
                r = await self.client.post(f"/job/{DEMO_JID}/agent/ask", json={"q": "more"}, headers=self.origin)
                self.assertEqual(r.status, 429)
            finally:
                self.app["agent"], self.app["admins"] = None, {TEST_PK}
            cards = self.lines("agent", kind="cards")
            self.assertEqual([(c["cached"], c.get("ai_usd"), c.get("ai_in")) for c in cards], [(0, 0.001, 100), (1, None, None)])
            asks = self.lines("agent", kind="ask")
            self.assertEqual([a.get("chip") for a in asks], [chip, None, None, None])   # своє питання не пишеться
            self.assertEqual([a["ok"] for a in asks], [1, 1, 1, 0])
            self.assertEqual((asks[2].get("off"), asks[0].get("off"), asks[0]["dropped"]), (1, None, 1))
            self.assertEqual((asks[3]["ai_usd"], asks[3]["ai_in"]), (0.0005, 90))   # невдала відповідь теж оплачена
            self.assertNotIn("who held", json.dumps(self.lines()))       # набраний текст — лише в журналі агента
            self.assertEqual([(e["what"], e["kind"]) for e in self.lines("limit")], [("agent-ask", "wallet")])
            log = self.app["agent_store"].recent(10)
            self.assertEqual([(e.get("chip"), e.get("error") is not None) for e in log if e["kind"] == "ask"],
                             [(False, True), (False, False), (False, False), (True, False)])   # новіші першими
            self.assertEqual(log[0]["usage"]["cost"], 0.0005)

        async def test_clicks_arrive_in_batches_from_this_site_only(self):
            page = f"http://{self.client.host}:{self.client.port}/job/{DEMO_JID}"
            batch = {"e": [["sort", {"key": "real", "dir": "desc", "via": "head"}, 1000], ["hacked", {}, 1000],
                           ["copy", {"what": W1}, 1500]]}
            r = await self.client.post("/me/usage", data=json.dumps(batch), headers=dict(GUEST, Origin=self.origin["Origin"]))
            self.assertEqual(r.status, 401)                               # гість нічого не пише
            r = await self.client.post("/me/usage", data=json.dumps(batch), headers={"Origin": "https://evil.example"})
            self.assertEqual(r.status, 403)                               # чужий сайт — теж
            r = await self.client.post("/me/usage", data=json.dumps(batch), headers=dict(self.origin, Referer=page))
            self.assertEqual(r.status, 204)
            ui = self.lines("ui")
            self.assertEqual([(e["name"], e["page"], e["ref"]) for e in ui], [("sort", "job", DEMO_JID), ("copy", "job", DEMO_JID)])
            self.assertEqual((ui[0]["key"], ui[0]["pubkey"]), ("real", TEST_PK))
            self.assertNotIn(W1, json.dumps(ui))                          # адреса в журнал не пролазить
            admin = f"http://{self.client.host}:{self.client.port}/admin"
            await self.client.post("/me/usage", data=json.dumps(batch), headers=dict(self.origin, Referer=admin))
            await self.client.post("/me/usage", data="x" * 9000, headers=dict(self.origin, Referer=page))
            self.assertEqual(len(self.lines("ui")), 2)                    # кліки власника на /admin і завелике тіло — ні
            self.app["s"]["usage_events_per_day"] = 3
            await self.client.post("/me/usage", data=json.dumps({"e": [["tf", {"tf": "1m"}, 1]] * 5}), headers=dict(self.origin, Referer=page))
            self.assertEqual(len(self.lines("ui")), 3)                    # стеля гаманця на добу

        async def test_the_dashboard_shows_the_owner_what_wallets_do(self):
            import re
            seed_demo(self.tmp.name, self.app)
            user = acct_mod.b58encode(b"\x31" * 32)
            hu = {"Cookie": wallet_cookie(user)}
            self.app["accounts"].touch(user, "Phantom")
            await self.client.get(f"/job/{DEMO_JID}", headers=hu)
            page = f"http://{self.client.host}:{self.client.port}/job/{DEMO_JID}"
            r = await self.client.post("/me/usage", data=json.dumps({"e": [["sort", {"key": "real", "dir": "desc"}, 1]]}),
                                       headers=dict(hu, Origin=self.origin["Origin"], Referer=page))
            self.assertEqual(r.status, 204)
            for p in ("today", "7d", "30d", "all", "junk"):
                r = await self.client.get(f"/admin?p={p}")
                self.assertEqual(r.status, 200, p)
            html = await (await self.client.get("/admin")).text()
            for part in ('id="funnel"', "Analyses and their credits", "Sorted the table", f'href="/admin/w/{user}"', "Phantom", 'id="method"'):
                self.assertIn(part, html)
            self.assertIsNone(re.search("[\u0400-\u04ff]", html))
            self.assertEqual((await self.client.get("/admin", headers=hu)).status, 403)     # не власник
            r = await self.client.get(f"/admin/w/{user}")
            text = await r.text()
            self.assertEqual(r.status, 200)
            self.assertIn("Sorted the table", text)
            self.assertIn("opened a result (demo)", text)
            self.assertEqual((await self.client.get("/admin/w/not-a-wallet")).status, 404)
            self.assertEqual((await self.client.get(f"/admin/w/{user}", headers=hu)).status, 403)
            r = await self.client.post("/admin/usage/exclude", json={"wallet": user, "on": True}, headers=dict(hu, Origin=self.origin["Origin"]))
            self.assertEqual(r.status, 403)                                  # позначати тестовим може лише власник
            r = await self.client.post("/admin/usage/exclude", json={"wallet": user, "on": True}, headers=self.origin)
            self.assertEqual((await r.json())["excluded"], True)
            html = await (await self.client.get("/admin")).text()
            self.assertNotIn(f'href="/admin/w/{user}"', html)                # тестовий гаманець — не користувач
            html = await (await self.client.get("/admin?team=1")).text()
            self.assertIn(f'href="/admin/w/{user}"', html)                   # а з командою видно, з позначкою
            self.assertIn("Team included", html)
            r = await self.client.post("/admin/usage/exclude", json={"wallet": user, "on": False}, headers=self.origin)
            self.assertEqual((await r.json())["excluded"], False)

        async def test_on_chain_facts_of_active_wallets_once_a_day(self):
            from tracced.web.app import refresh_onchain
            import time as _time
            now = int(_time.time() * 1000)
            active, idle = acct_mod.b58encode(b"\x41" * 32), acct_mod.b58encode(b"\x42" * 32)
            self.app["accounts"].touch(active, "Phantom")                         # хто щось робив — той і входив
            self.app["events"].add(active, "view", page="home", ts_ms=now - 3_600_000)
            self.app["events"].add(idle, "view", page="home", ts_ms=now - 10 * 86_400_000)      # тиждень тому й раніше — не оновлюємо

            class Ages:
                def __init__(self):
                    self.calls = []

                def balances(self, ws):
                    self.calls.append(("balances", list(ws)))
                    return {w: 1.5 for w in ws}

                def paused(self):
                    return False

                def oldest_tx(self, w, full=True):
                    self.calls.append(("age", w))
                    return {"oldest_ms": now - 400 * 86_400_000, "exact": True}
            ages = Ages()
            self.app["ages"] = ages
            self.st.identities = lambda ws, **kw: {active: {"name": "Cented", "type": "kol"}}
            before = self.st.requests
            try:
                self.assertEqual(await asyncio.to_thread(refresh_onchain, self.app, now), 1)
                self.assertEqual(await asyncio.to_thread(refresh_onchain, self.app, now + 3_600_000), 0)   # 20 годин ще не минуло
            finally:
                self.app["ages"] = None
                del self.st.identities
            data = json.load(open(self.app["usage_dir"] / "onchain.json"))
            rec = data[active]
            self.assertEqual((rec["sol"], rec["idn"]["name"], rec["p30"]["pnl_usd"]), (1.5, "Cented", 50.0))
            self.assertNotIn(idle, data)
            self.assertEqual(ages.calls, [("balances", [active]), ("age", active)])
            spend = self.lines("spend", what="onchain")
            self.assertEqual([(e["pubkey"], e["st"], e["bg"]) for e in spend], [("system", self.st.requests - before, 1)])
            html = await (await self.client.get("/admin?team=1")).text()
            self.assertIn("Cented", html)                                    # на дашборді — у таблиці гаманців

        async def test_new_profiles_stop_at_the_daily_cap(self):
            from tracced.web.app import refresh_onchain
            import time as _time
            now = int(_time.time() * 1000)
            ws = [acct_mod.b58encode(bytes([0x50 + i]) * 32) for i in range(3)]
            for w in ws:
                self.app["events"].add(w, "view", page="home", ts_ms=now - 3_600_000)
            self.app["s"]["usage_profiles_per_day"] = 2
            before = self.st.requests
            self.assertEqual(await asyncio.to_thread(refresh_onchain, self.app, now), 3)
            self.assertEqual(self.st.requests - before, 2)                    # третій профіль — завтра
            data = json.load(open(self.app["usage_dir"] / "onchain.json"))
            self.assertEqual(sum(1 for w in ws if data[w].get("p30")), 2)

        async def test_sign_out_tags_and_list_exports_are_actions(self):
            seed_demo(self.tmp.name, self.app)
            r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=self.origin)
            self.assertEqual(r.status, 200, await r.text())
            r = await self.client.post("/me/wallets/tags", json={"wallet": W1, "tags": ["insider", "early"]}, headers=self.origin)
            self.assertEqual(r.status, 200, await r.text())
            r = await self.client.get("/me/wallets.csv")
            self.assertEqual(r.status, 200)
            await self.client.post("/auth/logout", headers=self.origin)
            ev = self.app["events"].tail()
            self.assertEqual([e["event"] for e in ev], ["signout", "export", "tags", "save_wallets"])
            self.assertEqual((ev[1]["what"], ev[2]["count"]), ("lists", 2))
            self.assertNotIn("insider", json.dumps(self.lines()))         # слова тегів — справа людини


if __name__ == "__main__":
    unittest.main()
