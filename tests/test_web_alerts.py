"""Сповіщення в Telegram на фейковому клієнті: прив'язка кодом, відповіді бота, налаштування, дзвіночок, закритий тест."""
import asyncio
import json
import re
import tempfile
import time
import unittest

try:
    import aiohttp
    from aiohttp.test_utils import AioHTTPTestCase
except ImportError:  # хост без aiohttp: тести сторінок пропускаються
    AioHTTPTestCase = None

from tracced.early import settings

try:
    from tests.test_early_pipeline import TRADES
except ImportError:
    from test_early_pipeline import TRADES

if AioHTTPTestCase:
    try:
        from tests.test_web import FakeWebST, TEST_PK, W1, wallet_cookie, seed_demo, DEMO_JID
    except ImportError:
        from test_web import FakeWebST, TEST_PK, W1, wallet_cookie, seed_demo, DEMO_JID
    from unittest import mock
    from tracced.web import app as app_mod
    from tracced.web.app import create_app, tg_reply

    class TestAlertsWeb(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            app = create_app(FakeWebST(TRADES), settings.load(), {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            app["tg"]["token"], app["tg"]["name"], app["tg"]["on"] = "test-token", "tracced_bot", True
            app["tg"]["checked"] = True                                                    # getMe has answered
            app["s"]["alerts_chat_gap_s"] = 0                                              # no second between messages in tests
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

        async def test_a_one_time_link_binds_the_chat_and_stop_unbinds_it(self):
            r = await self.client.post("/me/telegram/link", json={}, headers=self.origin)
            url = (await r.json())["url"]
            self.assertTrue(url.startswith("https://t.me/tracced_bot?start="))
            code, chat = url.split("start=")[1], 424242

            def upd(text, kind="private"):
                return {"update_id": 1, "message": {"chat": {"id": chat, "type": kind}, "from": {"username": "owner"}, "text": text}}
            self.assertIsNone(tg_reply(self.app, upd("/start " + code, "group")))          # a group would show everyone
            to, text = tg_reply(self.app, upd("/start " + code))
            self.assertEqual(to, chat)
            self.assertIn("Connected to wallet", text)
            tg = self.app["accounts"].load(TEST_PK)["telegram"]
            self.assertEqual((tg["chat"], tg["user"]), (chat, "@owner"))
            self.assertIn("expired", tg_reply(self.app, upd("/start " + code))[1])        # the code works once
            d = await (await self.client.get("/me/telegram.json")).json()
            self.assertTrue(d["linked"])
            self.assertIn("state", d)                                                     # the owner sees the stream's state
            self.assertIn("Alerts stopped", tg_reply(self.app, upd("/stop"))[1])
            self.assertNotIn("telegram", self.app["accounts"].load(TEST_PK))

        async def test_prefs_the_bell_and_the_closed_test(self):
            r = await self.client.post("/me/alerts", json={"buys": True, "sells": False, "min_usd": 250}, headers=self.origin)
            self.assertEqual((await r.json())["prefs"], {"buys": True, "sells": False, "min_usd": 250.0})
            r = await self.client.post("/me/lists/alerts", json={"id": "main", "on": True}, headers=self.origin)
            self.assertIs((await r.json())["alerts"], True)
            self.assertTrue(self.app["accounts"].load(TEST_PK)["lists"]["main"]["alerts"])
            self.assertIn('id="tgbar"', await (await self.client.get("/me")).text())
            self.client.session.headers["Cookie"] = wallet_cookie(W1)                      # anyone else, in the closed test
            self.assertEqual((await self.client.post("/me/telegram/link", json={}, headers=self.origin)).status, 403)
            self.assertEqual((await self.client.post("/me/lists/alerts", json={"id": "main", "on": True}, headers=self.origin)).status, 403)
            self.assertNotIn('id="tgbar"', await (await self.client.get("/me")).text())
            self.app["s"]["alerts_open"] = True
            self.assertEqual((await self.client.post("/me/telegram/link", json={}, headers=self.origin)).status, 200)
            self.app["tg"]["on"] = False                                                     # a token without ALERTS=1: no bot runs here
            self.assertEqual((await self.client.post("/me/telegram/link", json={}, headers=self.origin)).status, 503)
            self.assertNotIn('id="tgbar"', await (await self.client.get("/me")).text())
            self.app["tg"]["on"] = True
            self.app["tg"]["token"] = ""
            self.assertEqual((await self.client.post("/me/telegram/link", json={}, headers=self.origin)).status, 503)


    class TestAlertsReview(TestAlertsWeb):
        """Рев'ю 01.10: чужий код не забирає чат, заблокований бот не глушить інших, серія угод не платить за кожну."""

        def upd(self, text, chat=424242, user="owner"):
            return {"update_id": 1, "message": {"chat": {"id": chat, "type": "private"}, "from": {"username": user}, "text": text}}

        async def code_for(self, cookie):
            self.client.session.headers["Cookie"] = cookie
            r = await self.client.post("/me/telegram/link", json={}, headers=self.origin)
            return (await r.json())["url"].split("start=")[1]

        async def test_a_linked_chat_is_not_taken_by_someone_elses_link(self):
            self.app["s"]["alerts_open"] = True
            mine = await self.code_for(wallet_cookie(TEST_PK))
            self.assertIn("Connected", tg_reply(self.app, self.upd("/start " + mine))[1])
            theirs = await self.code_for(wallet_cookie(W1))                                # someone sends their link to me
            text = tg_reply(self.app, self.upd("/start " + theirs))[1]
            self.assertIn("already gets alerts", text)
            self.assertEqual(self.app["accounts"].load(TEST_PK)["telegram"]["chat"], 424242)   # still mine
            self.assertNotIn("telegram", self.app["accounts"].load(W1))                         # they learn nothing

        async def test_lists_show_what_the_alerts_saw(self):
            seed_demo(self.tmp.name, self.app)
            r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=self.origin)
            self.assertEqual(r.status, 200, await r.text())
            self.assertNotIn('class="wact', await (await self.client.get("/me")).text())  # nothing seen yet: no counter
            act = self.app["activity"]
            act.watch({W1})
            act.bump(W1, "buy"), act.bump(W1, "buy"), act.bump(W1, "sell")
            self.assertNotIn('class="wact', await (await self.client.get("/me")).text())  # the bell is off: not watched, no counter
            self.app["accounts"].set_telegram(TEST_PK, 4242, "@owner")
            r = await self.client.post("/me/lists/alerts", json={"id": "main", "on": True}, headers=self.origin)
            self.assertEqual(r.status, 200, await r.text())
            html = await (await self.client.get("/me")).text()
            self.assertIn('<span class="wact"', html)
            self.assertIn("↑2", html)
            self.assertIn("↓1", html)
            meta = json.loads(re.search(r'id="mewmeta">(.*?)</script>', html, re.S).group(1))
            self.assertEqual((meta[W1]["act"]["buys"], meta[W1]["act"]["sells"]), (2, 1))   # the card gets the same
            act.data[W1]["h"], act.data[W1]["last"] = {}, int(time.time() * 1000) - 9 * 86_400_000
            self.assertIn("last trade 9d ago", await (await self.client.get("/me")).text())   # quiet for a week
            act.data[W1]["last"] = 0
            self.assertIn("no trades yet", await (await self.client.get("/me")).text())       # watched, nothing traded

        async def test_the_poll_catches_what_the_stream_missed(self):
            now = int(time.time())
            self.app["alerts_wm"] = {"WAL": [{"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}]}
            act = self.app["activity"]
            act.watch({"WAL"})
            got, asked = [], []

            async def fake_tx(app, http, w, sig, via="stream", bt=None):
                got.append((sig, via))
                return sig not in fail
            fail = set()

            async def rpc(http, url, method, params):
                asked.append(params[1])
                if "until" not in params[1]:
                    return [{"signature": "BASE", "blockTime": now - 100}]
                return [{"signature": "FRESH", "blockTime": now - 3},                 # newer than the grace: the stream's
                        {"signature": "MISSED", "blockTime": now - 40},
                        {"signature": "FAILED", "blockTime": now - 50, "err": {"x": 1}},
                        {"signature": "OLD", "blockTime": now - 3600}]                 # older than 10 minutes: too late to say
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_alert_tx_safe", fake_tx):
                await app_mod._alerts_poll(self.app, None, ["WAL"])                    # a new wallet: a bookmark, no alerts
                self.assertEqual((got, act.last_sig("WAL")), ([], "BASE"))
                await app_mod._alerts_poll(self.app, None, ["WAL"])
                await asyncio.sleep(0)
            self.assertEqual(asked[-1].get("until"), "BASE")
            self.assertEqual(got, [("MISSED", "poll")])
            self.assertEqual(act.last_sig("WAL"), "MISSED")                            # not past FRESH: the next poll sees it
            act.seen("WAL", "BASE")
            got.clear(), fail.add("MISSED")                                            # the node did not give MISSED this time
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_alert_tx_safe", fake_tx):
                await app_mod._alerts_poll(self.app, None, ["WAL"])
            self.assertEqual(act.last_sig("WAL"), "FAILED")                            # the bookmark waits before it: retried next time

        async def test_lists_change_without_a_reconnect(self):
            sent, inbox = [], asyncio.Queue()

            class WS:
                async def send_json(self, m):
                    sent.append(m)
                    inbox.put_nowait({"id": m["id"], "result": 100 + m["id"] if m["method"] == "logsSubscribe" else True})

                async def receive(self, timeout=None):
                    try:
                        d = inbox.get_nowait()
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.01)
                        raise asyncio.TimeoutError
                    return type("M", (), {"type": aiohttp.WSMsgType.TEXT, "data": json.dumps(d)})()

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *a):
                    return False

                async def close(self):
                    return True

            class HTTP:
                async def ws_connect(self, *a, **k):
                    return WS()
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}
            maps = [{"W2": [sub], "W3": [sub]}, {}]
            self.app["s"]["alerts_check_s"] = 0
            with mock.patch.object(app_mod, "_watch_now", lambda app: maps.pop(0) if maps else {}), \
                    mock.patch.object(app_mod, "_alerts_poll", mock.AsyncMock()):
                await asyncio.wait_for(app_mod._alerts_watch_once(self.app, HTTP(), "wss://x", {"W1": [sub], "W2": [sub]}), 5)
            calls = [(m["method"], m["params"][0]["mentions"][0] if m["method"] == "logsSubscribe" else m["params"][0]) for m in sent]
            self.assertEqual(calls[:2], [("logsSubscribe", "W1"), ("logsSubscribe", "W2")])
            self.assertIn(("logsUnsubscribe", 101), calls)                             # W1 left: unsubscribed, same connection
            self.assertIn(("logsSubscribe", "W3"), calls)                              # W3 came: subscribed, same connection
            self.assertEqual(set(self.app["activity"].data), set())                    # nobody left: counts forgotten

        async def test_a_bot_wallet_and_the_subscription_cap(self):
            sent, inbox = [], asyncio.Queue()

            class WS:
                async def send_json(self, m):
                    sent.append(m)
                    inbox.put_nowait({"id": m["id"], "result": 100 + m["id"]})
                    if m["method"] == "logsSubscribe" and m["id"] == 1:              # the first wallet starts trading like a bot
                        for i in range(32):
                            inbox.put_nowait({"method": "logsNotification", "params": {"subscription": 101,
                                              "result": {"value": {"signature": f"B{i}", "err": None}}}})

                async def receive(self, timeout=None):
                    try:
                        d = inbox.get_nowait()
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.01)
                        raise asyncio.TimeoutError
                    return type("M", (), {"type": aiohttp.WSMsgType.TEXT, "data": json.dumps(d)})()

                async def close(self):
                    return True

            class HTTP:
                async def ws_connect(self, *a, **k):
                    return WS()
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}
            maps, calls = [{"BOT": [sub], "ZZZ": [sub]}, {}], []

            async def fake_tx(app, http, w, sig, via="stream", bt=None):
                calls.append(sig)
                return True
            self.app["s"].update(alerts_check_s=0.05, alerts_subs_per_conn=1)
            with mock.patch.object(app_mod, "_watch_now", lambda app: maps.pop(0) if maps else {}), \
                    mock.patch.object(app_mod, "_alert_tx_safe", fake_tx):
                await asyncio.wait_for(app_mod._alerts_watch_once(self.app, HTTP(), "wss://x", {"BOT": [sub], "ZZZ": [sub]}), 5)
            subs = [m["params"][0]["mentions"][0] for m in sent if m["method"] == "logsSubscribe"]
            self.assertEqual(subs, ["BOT"])                                            # one per connection here: ZZZ left to the poll
            await asyncio.sleep(0)
            self.assertEqual(len(calls), 30)                                           # a bot's minute stops at 30
            self.assertIn("B31:BOT", self.app["alerts_seen"])                          # the rest is marked: the poll will not resend it

        async def test_an_alert_nobody_got_is_tried_again_and_counted_once(self):
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {"buys": True, "sells": True, "min_usd": 0}, "tags": [], "src": ""}
            self.app["alerts_wm"] = {"WAL": [sub]}
            self.app["activity"].watch({"WAL"})
            ev = {"side": "buy", "mint": "M" * 32, "usd": 500.0, "amount": 10.0, "sig": "S", "ts": int(time.time()), "new": True}
            results = [False, True]

            async def send(app, http, chat, text, pk=None):
                return results.pop(0)
            with mock.patch.object(app_mod, "_alert_rpc", mock.AsyncMock(return_value={"tx": 1})), \
                    mock.patch.object(app_mod, "_sol_price", mock.AsyncMock(return_value=150.0)), \
                    mock.patch.object(app_mod, "_tg_send", send), mock.patch.object(app_mod, "_st_open_now", lambda app: False), \
                    mock.patch.object(app_mod.alerts_mod, "classify", lambda tx, w, px: [dict(ev)]):
                self.assertFalse(await app_mod._alert_tx_safe(self.app, None, "WAL", "S"))   # Telegram failed: not handled
                self.assertNotIn("S:WAL", self.app["alerts_seen"])
                self.assertTrue(await app_mod._alert_tx_safe(self.app, None, "WAL", "S", via="poll"))
            self.assertEqual(self.app["activity"].of(["WAL"])["WAL"]["buys"], 1)      # the retry is not a second trade

        async def test_the_poll_skips_a_bots_minute_too(self):
            now = int(time.time())
            self.app["alerts_wm"] = {"BOT": [{"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}]}
            act = self.app["activity"]
            act.watch({"BOT"}), act.seen("BOT", "BASE")
            self.app["s"]["alerts_wallet_per_min"] = 3
            got = []

            async def fake_tx(app, http, w, sig, via="stream", bt=None):
                got.append(sig)
                return True

            async def rpc(http, url, method, params):
                return [{"signature": f"T{i}", "blockTime": now - 30 - i} for i in range(10)]
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_alert_tx_safe", fake_tx):
                await app_mod._alerts_poll(self.app, None, ["BOT"])
            self.assertEqual(len(got), 3)                                                # three a minute, the rest skipped
            self.assertIn("T0:BOT", self.app["alerts_seen"])                             # and marked, so not sent later
            self.assertEqual(act.last_sig("BOT"), "T0")

        async def test_a_trade_the_node_did_not_give_is_retried_not_lost(self):
            self.app["alerts_wm"] = {"WAL": [{"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}]}
            with mock.patch.object(app_mod, "_alert_rpc", mock.AsyncMock(side_effect=RuntimeError("rpc getTransaction: -32005 rate limit"))), \
                    mock.patch.object(asyncio, "sleep", mock.AsyncMock()):
                self.assertFalse(await app_mod._alert_tx_safe(self.app, None, "WAL", "S1"))
            self.assertNotIn("S1:WAL", self.app["alerts_seen"])                       # not marked handled: the poll can take it

        async def test_what_was_handled_survives_a_restart(self):
            act = self.app["activity"]
            act.watch({"WAL"}), act.done("WAL", "S9")
            act.write(act.snapshot())
            again = create_app(FakeWebST(TRADES), settings.load(), {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            self.assertIn("S9:WAL", again["alerts_seen"])                              # the first poll after a restart skips it

        async def test_the_pace_and_its_pause_hold_for_everyone(self):
            p = app_mod._Pace(20)
            t0 = time.monotonic()
            await asyncio.gather(*(p.wait() for _ in range(5)))
            self.assertGreater(time.monotonic() - t0, 0.15)                            # 5 at 20 a second: about 0.2 s
            p = app_mod._Pace(50)
            waits = [asyncio.ensure_future(p.wait()) for _ in range(3)]
            await asyncio.sleep(0)
            p.slow(0.3)                                                                # a refusal after they took their places
            t0 = time.monotonic()
            await asyncio.gather(*waits)
            self.assertGreater(time.monotonic() - t0, 0.25)
            for text in ("rpc getTransaction: {'code': -32005, 'message': 'Rate limit exceeded'}", "429 Too Many Requests"):
                self.assertTrue(app_mod._limited(RuntimeError(text)))
            self.assertFalse(app_mod._limited(RuntimeError("Server disconnected")))

        async def test_credits_never_hold_an_alert(self):
            self.app["s"].update(credits_month=1_000_000, credits_reserve_pct=5)
            self.app["credits"].update(left=None, at=0)
            slow = asyncio.Event()

            async def credits(app):
                await slow.wait()
                return 10
            with mock.patch.object(app_mod, "_credits_left", credits):
                t0 = time.monotonic()
                self.assertTrue(app_mod._st_open_now(self.app))                        # unknown: allowed, asked in the background
                self.assertLess(time.monotonic() - t0, 0.05)
                slow.set()
                await self.app["credits_task"]
            self.app["credits"].update(left=10, at=time.time())
            self.assertFalse(app_mod._st_open_now(self.app))                           # known and under the reserve: no paid lookups

        async def test_no_link_before_the_bot_is_known(self):
            self.app["tg"]["checked"] = False                                              # a name from .env alone is not trusted
            self.assertEqual((await self.client.post("/me/telegram/link", json={}, headers=self.origin)).status, 503)

        async def test_a_blocked_bot_drops_only_that_subscriber(self):
            a, b = {"pk": "A", "chat": 1}, {"pk": "B", "chat": 2}
            self.app["alerts_wm"] = {"W1": [a, b], "W2": [a]}
            app_mod._unwatch(self.app, "A")
            self.assertEqual(self.app["alerts_wm"], {"W1": [b]})

        async def test_a_burst_pays_only_for_what_it_can_send(self):
            self.app["s"]["alerts_per_hour"] = 2
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {"buys": True, "sells": True, "min_usd": 0}, "tags": [], "src": ""}
            picky = {"pk": W1, "chat": 8, "prefs": {"buys": True, "sells": False, "min_usd": 1e9}, "tags": [], "src": ""}   # wants none of these
            self.app["alerts_wm"] = {"WAL": [sub, picky]}
            self.app["activity"].watch({"WAL"})
            ev = {"side": "sell", "mint": "M" * 32, "usd": 500.0, "amount": 10.0, "before": 100.0, "pct": 10, "sig": "", "ts": int(time.time()), "mcap": 1e6}
            calls = {"facts": 0, "share": 0, "sent": 0}

            async def facts(app, mint):
                calls["facts"] += 1
                return {"symbol": "X"}

            async def share(app, w, e):
                calls["share"] += 1
                return None

            async def send(app, http, chat, text, pk=None):
                calls["sent"] += 1
                return True

            async def rpc(*a, **k):
                return {"tx": 1}

            async def price(app, http):
                return 150.0
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_sol_price", price), \
                    mock.patch.object(app_mod, "_token_facts", facts), mock.patch.object(app_mod, "_sold_share", share), \
                    mock.patch.object(app_mod, "_tg_send", send), mock.patch.object(app_mod, "_st_open", mock.AsyncMock(return_value=True)), \
                    mock.patch.object(app_mod.alerts_mod, "classify", lambda tx, w, px: [dict(ev)]):
                await asyncio.gather(*(app_mod._alert_tx_safe(self.app, None, "WAL", f"sig{i}") for i in range(20)))
            self.assertEqual(calls["sent"], 3)                                             # two alerts and one "skipped" line
            self.assertEqual(self.app["activity"].of(["WAL"])["WAL"]["sells"], 20)        # every trade counts, sent or not, whoever wants it
            self.assertEqual((calls["facts"], calls["share"]), (2, 2))                     # paid lookups only for the two
            self.app["alerts_wm"] = {}
            with mock.patch.object(app_mod, "_rpc", mock.AsyncMock(side_effect=AssertionError("no one watches"))):
                await app_mod._alert_tx_safe(self.app, None, "WAL", "late")               # nobody watches: not even the node is asked


if __name__ == "__main__":
    unittest.main()
