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
            d = await r.json()
            self.assertEqual((d["alerts"], d["changed"]), (True, 0))                      # the whole list at once; empty here
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

        async def test_the_bell_is_per_wallet_and_capped(self):
            # owner, 02.10: the bell on each wallet, at most alerts_max_wallets (20) on; the page counts them and today's alerts
            seed_demo(self.tmp.name, self.app)
            self.assertEqual(settings.load()["alerts_max_wallets"], 20)                     # owner: 50 → 10 (02.10) → 20 (08.10) per account
            from tracced.web import accounts as acct_mod
            w2 = acct_mod.b58encode(b"\x02" * 32)
            r = await self.client.post("/me/wallets", json={"job": DEMO_JID, "wallets": [W1]}, headers=self.origin)
            self.assertEqual(r.status, 200, await r.text())
            self.app["accounts"].add_wallets(TEST_PK, [{"wallet": w2}])
            self.app["accounts"].set_telegram(TEST_PK, 4242, "@owner")
            bell = lambda w, on: self.client.post("/me/wallets/alert", json={"wallet": w, "on": on}, headers=self.origin)
            d = await (await bell(W1, True)).json()
            self.assertEqual((d["on"], d["n"], d["cap"]), (True, 1, 20))
            self.assertEqual(list(app_mod._watch_now(self.app)), [W1])                       # only the wallet with its bell on
            self.app["s"]["alerts_max_wallets"] = 1
            r = await bell(w2, True)
            self.assertEqual(r.status, 400)
            self.assertIn("Turn one off first", (await r.json())["error"])
            html = await (await self.client.get("/me")).text()
            self.assertIn('data-cap="1">1</b> of 1 wallets', html)                          # the counters by the switch
            self.assertIn("<b>0</b> of 200 alerts today", html)
            self.assertIn('class="ghost bell on" data-bell', html)
            self.assertEqual((await (await bell(W1, False)).json())["n"], 0)
            self.assertEqual((await (await bell(w2, True)).json())["n"], 1)
            self.assertEqual(list(app_mod._watch_now(self.app)), [w2])
            self.assertEqual((await bell("Q" * 44, True)).status, 400)                       # not in the lists
            self.client.session.headers["Cookie"] = wallet_cookie(W1)                        # anyone else, in the closed test
            self.assertEqual((await bell(w2, True)).status, 403)

        async def test_a_whole_list_switches_on_and_the_page_gets_every_bell(self):
            # owner, 04.10: «alerts by lists» again. The list's switch rings every wallet in it, the newest first while there
            # is room, and the answer carries every bell so the page shows them all at once
            from tracced.web import accounts as acct_mod
            w2, w3 = acct_mod.b58encode(b"\x02" * 32), acct_mod.b58encode(b"\x03" * 32)
            acc = self.app["accounts"]
            acc.add_wallets(TEST_PK, [{"wallet": W1}, {"wallet": w2}])
            lid, _ = acc.create_list(TEST_PK, "Second")
            acc.add_wallets(TEST_PK, [{"wallet": w3}], lid)
            the_list = lambda i, on: self.client.post("/me/lists/alerts", json={"id": i, "on": on}, headers=self.origin)
            d = await (await the_list("main", True)).json()
            self.assertEqual((d["changed"], sorted(d["bells"]), d["cap"]), (2, sorted([W1, w2]), 20))
            self.app["s"]["alerts_max_wallets"] = 3
            d = await (await the_list(lid, True)).json()
            self.assertEqual((d["changed"], len(d["bells"])), (1, 3))
            d = await (await the_list("main", False)).json()
            self.assertEqual((d["changed"], d["bells"]), (2, [w3]))                          # the other list keeps its bell
            html = await (await self.client.get("/me")).text()
            self.assertIn('id="lalert"', html)
            self.assertIn('id="tgconnect"', html)                                             # the real site: connect, no preview
            self.assertNotIn("Preview on the draft", html)

        async def test_after_the_alerts_counts_from_the_buy_price(self):
            # owner, 04.10: «що було після алерту» — a bell wallet's first buy and what the token did next, from its price
            from tracced.early import profile as profile_mod
            now = int(time.time() * 1000)
            step = 300_000
            t_buy = (now - 3 * 3_600_000) // step * step
            self.app["accounts"].add_wallets(TEST_PK, [{"wallet": W1}])
            self.app["accounts"].set_wallet_alert(TEST_PK, W1, True, 10)
            mint = "M" * 44
            card = {"recent": [{"mint": mint, "symbol": "PUMP", "trades": [[t_buy, "b", 100.0, 1000, 0.1], [t_buy + 3_600_000, "s", 150.0, 500, 0.3]]}]}
            self.app["profile_cache"].put(f"v{profile_mod.VERSION}:{W1}", card)          # its 30 days, from the card's cache
            asked = []

            def chart(m, interval, a, b, **kw):
                asked.append((m, interval, a, b))
                return [{"time": t_buy + i * step, "open": 0.1, "high": h, "low": lo, "close": h}
                        for i, (h, lo) in enumerate([(0.5, 0.1), (0.12, 0.08), (0.25, 0.2), (0.2, 0.15)])]
            self.app["st"].chart = chart
            self.assertEqual((await self.client.get("/me/after.json")).status, 404)            # the public site: not yet (owner, 04.10)
            self.assertNotIn('id="after"', await (await self.client.get("/me")).text())
            self.app["s"]["after_alerts"] = "on"                                              # the draft has it; «on» opens it anywhere
            d = await (await self.client.get("/me/after.json")).json()
            self.assertEqual((d["basis"], d["wallets"], d["partial"]), ("bells", 1, None))
            r = d["rows"][0]
            self.assertEqual((r["symbol"], r["wallet"], r["new"]), ("PUMP", W1, True))
            self.assertEqual((r["peak_x"], r["dip_x"], r["now_x"], r["at_end"]), (2.5, 0.8, 2.0, False))   # the buy's own candle is out
            self.assertEqual((r["exit_x"], r["exit_min"], r["sold_pct"]), (3.0, 60, 50))
            self.assertEqual(asked[0][:2], (mint, "5m"))
            self.assertEqual(d["summary"]["n"], 1)
            await self.client.get("/me/after.json")
            self.assertEqual(len(asked), 1)                                                # counted once, then 15 minutes from memory
            html = await (await self.client.get("/me")).text()
            self.assertIn('id="after"', html)
            self.assertIn("After the alerts", html)

        async def test_old_results_are_labelled_only_when_the_owner_opens_them(self):
            # release check, 04.10: guests and crawlers on the public site must not queue every old result for labels and
            # «dormant»; the owner's view (or the draft) does, once
            try:
                from tests.test_web import OTHER_JID
            except ImportError:
                from test_web import OTHER_JID
            seed_demo(self.tmp.name, self.app)
            job = self.app["jobs"].get(OTHER_JID)
            job.result["enrich"] = {"done": 1, "total": 1, "funders_done": 1}
            job.result["funders"] = {W1: "F" * 44}
            self.app["labels"] = object()                                   # a key is set on this server
            with mock.patch.object(self.app["jobs"], "resume_enrich") as resume:
                r = await self.client.get("/job/" + OTHER_JID, headers={"Cookie": ""})
                self.assertEqual(r.status, 200)
                resume.assert_not_called()                                  # a guest: nothing is queued
                await self.client.get("/job/" + OTHER_JID)                  # the owner (an admin wallet)
                resume.assert_called_once_with(job)

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

        async def test_the_poll_does_not_step_over_a_trade_still_in_work(self):
            self.app["alerts_wm"] = {"WAL": [{"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}]}
            self.app["alerts_seen"]["S:WAL"] = time.time()
            self.app["alerts_inflight"].add("S:WAL")                                   # the stream is still reading it
            self.assertFalse(await app_mod._alert_tx(self.app, None, "WAL", "S", via="poll"))
            self.app["alerts_inflight"].discard("S:WAL")
            self.assertTrue(await app_mod._alert_tx(self.app, None, "WAL", "S", via="poll"))   # done: the poll moves on

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

        def bot_chain(self, sigs, signed=lambda i: True, down=(), unread=False):
            """Фейкова мережа: підписи гаманця сторінками і транзакції, які він підписав чи ні. down — ноди, що не відповідають."""
            now = time.time()
            rows = {w: [{"signature": f"{w}:{i}", "err": {"x": 1} if i % 2 else None, "blockTime": now - age} for i, age in enumerate(ages)]
                    for w, ages in sigs.items()}
            asked = []

            async def rpc(http, url, method, params):
                asked.append((url, method))
                if url in down:
                    raise RuntimeError("no answer")
                if method == "getSignaturesForAddress":
                    q, got = params[1], rows.get(params[0], [])
                    start = next((i + 1 for i, x in enumerate(got) if x["signature"] == q.get("before")), 0)
                    return got[start:start + q["limit"]]
                if unread:
                    return None
                w, i = params[0].split(":")
                return {"transaction": {"message": {"accountKeys": [{"pubkey": w if signed(int(i)) else "SOMEONE", "signer": True}, {"pubkey": w, "signer": False}]}}}
            return rpc, asked

        def fast_bots(self, per_day=10):
            self.app["s"].update(alerts_spam_per_day=per_day, alerts_spam_sample=20, alerts_rps=1000)
            self.app["alerts_pace"], self.app["alerts_history_pace"], self.app["alerts_check_pace"] = app_mod._Pace(1000), app_mod._Pace(1000), app_mod._Pace(1000)
            self.app["accounts"].add_wallets(TEST_PK, [{"wallet": W1}])
            return lambda on=True: self.client.post("/me/wallets/alert", json={"wallet": W1, "on": on}, headers=self.origin)

        async def test_a_bot_that_signs_cannot_get_a_bell(self):
            bell, a = self.fast_bots(), self.app["accounts"]
            rpc, asked = self.bot_chain({W1: [60 + i for i in range(30)]})
            with mock.patch.object(app_mod, "_rpc", rpc):
                r = await bell()
                self.assertEqual(r.status, 400)                                        # 30 in 24 h, half of them failed: failed ones count
                self.assertIn("signs over 10 transactions a day", (await r.json())["error"])
            self.assertFalse(a.load(TEST_PK)["wallets"][W1].get("alert"))
            self.assertEqual(asked[0][0], self.app["s"]["alerts_history_url"])         # the full history first
            row, = self.app["alerts_spam"].rows()
            self.assertEqual((row["day"], row["week"], row["share"]), (30, 30, 1.0))
            with mock.patch.object(app_mod, "_rpc", mock.AsyncMock(side_effect=AssertionError("known: no request"))):
                self.assertEqual((await bell()).status, 400)                           # the block holds without asking the node
            self.assertTrue(app_mod.alerts_mod.SpamWallets(self.app["alerts_spam"].path).until(W1))   # and survives a restart

        async def test_dust_other_people_send_does_not_make_a_bot(self):
            bell, a = self.fast_bots(), self.app["accounts"]
            rpc, _ = self.bot_chain({W1: [60 + i for i in range(30)]}, signed=lambda i: i % 10 == 0)   # it signed 3 of 30
            with mock.patch.object(app_mod, "_rpc", rpc):
                self.assertTrue((await (await bell()).json())["on"])
            self.assertEqual(self.app["alerts_spam"].rows(), [])

        async def test_a_quiet_day_does_not_hide_a_bots_week(self):
            bell = self.fast_bots()
            rpc, asked = self.bot_chain({W1: [86400 * (1.5 + i * 0.05) for i in range(90)]})   # none today, 90 in the week: over 10 a day
            with mock.patch.object(app_mod, "_rpc", rpc):
                self.assertTrue((await (await bell()).json())["on"])                   # 72 a week against 70: too close for the small sample
                self.assertEqual(self.app["alerts_spam"].pending, {W1})                # the background check takes it
                with mock.patch.object(app_mod, "_watch_now", lambda app: {W1: []}):
                    self.assertEqual(await app_mod._spam_sweep(self.app, None, only={W1}), 1)
            row, = self.app["alerts_spam"].rows()
            self.assertEqual((row["day"], row["week"]), (0, 90))
            rpc, _ = self.bot_chain({W1: [86400 * (1.5 + i * 0.05) for i in range(60)]})       # 60 in the week is under
            self.app["alerts_spam"].blocked.clear()
            with mock.patch.object(app_mod, "_rpc", rpc):
                self.assertTrue((await (await bell()).json())["on"])

        async def test_a_node_that_is_down_is_replaced_and_nothing_stays_unchecked(self):
            bell, a = self.fast_bots(), self.app["accounts"]
            hist, free = self.app["s"]["alerts_history_url"], self.app["s"]["alerts_rpc_url"]
            ages = [60 + i for i in range(30)]
            rpc, _ = self.bot_chain({W1: ages}, down=(hist,))
            with mock.patch.object(app_mod, "_rpc", rpc):
                self.assertEqual((await bell()).status, 400)                           # the free node answers instead
            self.app["alerts_spam"].blocked.clear()
            rpc, _ = self.bot_chain({W1: ages}, down=(hist, free))
            with mock.patch.object(app_mod, "_rpc", rpc):
                self.assertTrue((await (await bell()).json())["on"])                   # nobody answers: the person is not held up
            self.assertEqual(self.app["alerts_spam"].pending, {W1})                    # but it is not forgotten
            rpc, _ = self.bot_chain({W1: ages}, unread=True)
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_watch_now", lambda app: {W1: []}):
                self.assertEqual(await app_mod._spam_sweep(self.app, None, only={W1}), 0)
            self.assertEqual(self.app["alerts_spam"].pending, {W1})                    # no transaction read: no verdict either way
            sent = []

            async def tg(app, http, chat, text, pk=None):
                sent.append(text)
                return True
            rpc, _ = self.bot_chain({W1: ages})
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_watch_now", lambda app: {W1: [sub]}), mock.patch.object(app_mod, "_tg_send", tg):
                self.assertEqual(await app_mod._spam_sweep(self.app, None, only={W1}), 1)
                await asyncio.sleep(0.05)
            self.assertEqual(self.app["alerts_spam"].pending, set())
            self.assertFalse(a.load(TEST_PK)["wallets"][W1].get("alert"))
            self.assertEqual(len(sent), 1)

        async def test_the_stream_counts_then_checks_before_it_stops_anyone(self):
            bell, a = self.fast_bots(per_day=3), self.app["accounts"]
            sub, sent = {"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": ["<kol>"]}, []

            async def tg(app, http, chat, text, pk=None):
                sent.append(text)
                return True
            quiet, _ = self.bot_chain({W1: []})
            with mock.patch.object(app_mod, "_rpc", quiet):
                await bell()
            self.app["alerts_wm"] = {W1: [sub], "OTHER": [sub]}
            dust, _ = self.bot_chain({W1: [60 + i for i in range(5)]}, signed=lambda i: False)
            with mock.patch.object(app_mod, "_rpc", dust), mock.patch.object(app_mod, "_tg_send", tg):
                for sig in ("A", "A", "B", "C", "D"):                                  # stream and poll saw A twice: it counts once
                    app_mod._spam_count(self.app, None, W1, sig)
                await asyncio.sleep(0.05)
            self.assertIn(W1, self.app["alerts_wm"])                                   # four, but none his own: he stays
            self.assertEqual(self.app["alerts_spam"].recent.get(W1), None)             # and the count starts over
            self.assertEqual(sent, [])
            self.app["alerts_spam"].spared.clear()                                     # the next general check is due
            bot, _ = self.bot_chain({W1: [60 + i for i in range(40)]})
            with mock.patch.object(app_mod, "_rpc", bot), mock.patch.object(app_mod, "_tg_send", tg):
                for sig in "EFGH":
                    app_mod._spam_count(self.app, None, W1, sig)
                await asyncio.sleep(0.05)
            self.assertEqual(list(self.app["alerts_wm"]), ["OTHER"])
            self.assertFalse(a.load(TEST_PK)["wallets"][W1].get("alert"))
            self.assertEqual(len(sent), 1)
            self.assertIn("&lt;kol&gt;", sent[0])
            self.assertNotIn(W1, app_mod._watch_now(self.app))

        async def test_a_flood_of_others_hides_neither_its_own_trades_nor_a_bot(self):
            al = app_mod.alerts_mod
            bell = self.fast_bots(per_day=500)
            self.app["s"]["alerts_spam_pages"] = 1
            now = time.time()
            rows = [{"signature": f"N{i}", "err": {"x": 1} if i % 10 else None, "blockTime": now - i * 7.2} for i in range(1000)]   # 1000 in 2 h, cut by the page

            async def rpc(http, url, method, params):
                if method == "getSignaturesForAddress":
                    return rows[:params[1]["limit"]]
                mine = int(params[0][1:]) % 30 == 0
                return {"transaction": {"message": {"accountKeys": [{"pubkey": W1 if mine else "BOT", "signer": True}]}}}
            with mock.patch.object(app_mod, "_rpc", rpc):
                v = await app_mod._spam_verdict(self.app, None, W1)
            self.assertEqual(v["day"], 4000)                                           # counted from the 6 hours at least, not 1000 a day
            self.assertEqual(v["share"], 0.034)                                        # 34 of 100 successful, none of 50 failed, weighed by 100 and 900
            self.assertFalse(v["bot"])                                                 # about 136 a day
            self.assertEqual(al.spam_rates(rows, now, False)[0], 1000)                 # nothing cut: as it is
            self.assertEqual(al.spam_rates(rows[:500], now, True)[0], 2000)
            self.assertEqual(al.spam_rates(rows, now, True)[1], 1000)                  # the week is never stretched
            mine = {"transaction": {"message": {"accountKeys": [{"pubkey": W1, "signer": True}]}}}
            share, low, high = al.spam_share(100, 900, [mine, {}], [{}, {}], W1)
            self.assertEqual(share, 0.05)
            self.assertTrue(low < 0.05 < high)
            self.assertEqual(al.spam_share(0, 900, [], [mine], W1)[0], 1.0)            # no successful ones: that group does not count
            self.assertLess(al.spam_share(10, 0, [mine] * 95 + [{}] * 5, [], W1)[1], 0.95)   # 95 % of a sample: the least is under 95 %

        async def test_a_doubtful_wallet_is_not_stopped_and_a_clear_one_is_at_once(self):
            bell = self.fast_bots(per_day=100)
            ages = [60 + i for i in range(400)]
            near, asked = self.bot_chain({W1: ages}, signed=lambda i: i % 3 == 0)      # about 133 of its own: over 100, but how sure?
            with mock.patch.object(app_mod, "_rpc", near):
                self.assertIsNone(await app_mod._spam_verdict(self.app, None, W1, quick=True))   # 20 read: too few to say
                reads = sum(1 for _, m in asked if m == "getTransaction")
                self.assertEqual(reads, 20)
                v = await app_mod._spam_verdict(self.app, None, W1)
            self.assertLessEqual(sum(1 for _, m in asked if m == "getTransaction") - reads, 220)   # the full one adds up to 200 to its small one
            self.assertTrue(v["bot"] or v["share"] > 0)
            border, _ = self.bot_chain({W1: ages}, signed=lambda i: i % 4 == 0)        # about 100: right on the line
            with mock.patch.object(app_mod, "_rpc", border):
                self.assertFalse((await app_mod._spam_verdict(self.app, None, W1))["bot"])
            clear, asked = self.bot_chain({W1: ages})
            with mock.patch.object(app_mod, "_rpc", clear):
                self.assertTrue((await app_mod._spam_verdict(self.app, None, W1, quick=True))["bot"])
            self.assertEqual(sum(1 for _, m in asked if m == "getTransaction"), 20)    # the small sample is enough

        async def test_the_stream_does_not_read_or_count_known_noise(self):
            bell = self.fast_bots(per_day=2)
            self.app["s"].update(alerts_noise_programs=["NOISE"], alerts_check_s=0.05)
            sent, inbox, reads = [], asyncio.Queue(), []
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}
            note = lambda sig, prog, err=None: {"method": "logsNotification", "params": {"subscription": 101, "result": {"value": {
                "signature": sig, "err": err, "logs": ["Program ComputeBudget111 invoke [1]", f"Program {prog} invoke [1]", "Program other invoke [2]"]}}}}

            class WS:
                async def send_json(self, m):
                    sent.append(m)
                    inbox.put_nowait({"id": m["id"], "result": 100 + m["id"]})
                    if m["id"] == 1:
                        for i in range(40):
                            inbox.put_nowait(note(f"B{i}", "NOISE"))
                        inbox.put_nowait(note("F1", "NOISE", {"x": 1}))
                        inbox.put_nowait(note("REAL", "pump"))

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

            async def fake_tx(app, http, w, sig, via="stream", bt=None):
                reads.append(sig)
                return True
            maps = [{"W": [sub]}, {}]
            with mock.patch.object(app_mod, "_watch_now", lambda app: maps.pop(0) if maps else {}), mock.patch.object(app_mod, "_alert_tx_safe", fake_tx):
                await asyncio.wait_for(app_mod._alerts_watch_once(self.app, HTTP(), "wss://x", {"W": [sub]}), 5)
            await asyncio.sleep(0)
            self.assertEqual(reads, ["REAL"])                                          # the 30-a-minute rule never saw the 40: the real trade passes
            self.assertIn("B7:W", self.app["alerts_seen"])                             # the poll will not read it either
            self.assertNotIn("F1:W", self.app["alerts_seen"])
            self.assertEqual(len(self.app["alerts_spam"].recent.get("W") or []), 1)    # only the real one counts toward a bot
            self.assertEqual(self.app["alerts_spam"].checking, set())

        async def test_a_spared_wallet_does_not_wake_the_check_again(self):
            bell = self.fast_bots(per_day=2)
            dust, asked = self.bot_chain({W1: [60 + i for i in range(5)]}, signed=lambda i: False)
            with mock.patch.object(app_mod, "_rpc", dust):
                for sig in "ABC":
                    app_mod._spam_count(self.app, None, W1, sig)
                await asyncio.sleep(0.05)
                n = len(asked)
                self.assertGreater(n, 0)
                for sig in "DEFGH":
                    app_mod._spam_count(self.app, None, W1, sig)
                await asyncio.sleep(0.05)
            self.assertEqual(len(asked), n)

        async def test_the_owner_sees_the_stopped_and_can_say_not_a_bot(self):
            bell = self.fast_bots()
            rpc, _ = self.bot_chain({W1: [60 + i for i in range(30)]})
            with mock.patch.object(app_mod, "_rpc", rpc):
                self.assertEqual((await bell()).status, 400)
            html = await (await self.client.get("/admin?tab=tg")).text()
            self.assertIn("Stopped as bots", html)
            self.assertIn("Not a bot", html)
            post = lambda allow: self.client.post("/admin/alerts/bot", json={"wallet": W1, "allow": allow}, headers=self.origin)
            self.assertTrue((await (await post(True)).json())["allow"])
            with mock.patch.object(app_mod, "_rpc", mock.AsyncMock(side_effect=AssertionError("an exception asks nothing"))):
                self.assertTrue((await (await bell()).json())["on"])
                self.assertFalse(self.app["alerts_spam"].hit(W1, "X", 0))              # and never counts
            html = await (await self.client.get("/admin?tab=tg")).text()
            self.assertIn("Never stopped", html)
            self.assertNotIn("Not a bot</button>", html)
            self.assertIn(W1, app_mod.alerts_mod.SpamWallets(self.app["alerts_spam"].path).allowed)
            await bell(False)
            self.assertFalse((await (await post(False)).json())["allow"])
            self.client.session.headers["Cookie"] = wallet_cookie(W1)                  # not the owner
            self.assertEqual((await post(True)).status, 403)

        async def test_the_sweep_stops_a_bell_that_became_a_bot(self):
            self.fast_bots()
            now_map = {W1: [{"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}], "QUIET": [], "DOWN": []}
            self.app["accounts"].set_wallet_alert(TEST_PK, W1, True, 20)
            self.app["alerts_wm"] = dict(now_map)
            rpc0, _ = self.bot_chain({W1: [60 + i for i in range(30)], "QUIET": [60]})
            sent = []

            async def rpc(http, url, method, params):
                if params[0] == "DOWN":
                    raise RuntimeError("no answer")
                return await rpc0(http, url, method, params)

            async def tg(app, http, chat, text, pk=None):
                sent.append(text)
                return True
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_tg_send", tg), mock.patch.object(app_mod, "_watch_now", lambda app: now_map):
                self.assertEqual(await app_mod._spam_sweep(self.app, None), 1)         # a node that does not answer stops nobody
                await asyncio.sleep(0.05)
            self.assertEqual(sorted(self.app["alerts_wm"]), ["DOWN", "QUIET"])
            self.assertEqual(self.app["alerts_spam"].pending, {"DOWN"})                # it gets another try in a minute
            self.assertFalse(self.app["accounts"].load(TEST_PK)["wallets"][W1].get("alert"))
            self.assertEqual(len(sent), 1)

        async def test_a_whole_list_leaves_its_bots_without_a_bell(self):
            self.fast_bots()
            a = self.app["accounts"]
            lid, _ = a.create_list(TEST_PK, "Bots")
            a.add_wallets(TEST_PK, [{"wallet": W1}], lid)
            rpc, _ = self.bot_chain({W1: [60 + i for i in range(30)]})
            with mock.patch.object(app_mod, "_rpc", rpc):
                r = await self.client.post("/me/lists/alerts", json={"id": lid, "on": True}, headers=self.origin)
            d = await r.json()
            self.assertEqual((d["spam"], d["changed"], d["bells"], d["spam_per_day"]), (1, 0, [], 10))

        async def test_the_paid_node_reads_trades_and_the_free_one_catches_it(self):
            paid, free = "https://paid.example/?api-key=SECRETKEY", self.app["s"]["alerts_rpc_url"]
            self.app["alerts_paid_url"], self.app["s"]["alerts_rps"] = paid, 1000
            asked, broken = [], False

            async def rpc(http, url, method, params):
                asked.append(url)
                if url == paid and broken:
                    raise RuntimeError(f"500, message='Bad', url='{paid}'")
                return {"ok": url}
            with mock.patch.object(app_mod, "_rpc", rpc):
                self.assertEqual(await app_mod._alert_rpc(self.app, None, "getTransaction", [], paid=True), {"ok": paid})
                self.assertEqual(await app_mod._alert_rpc(self.app, None, "getSignaturesForAddress", []), {"ok": free})   # the poll never spends the month
                broken = True
                with self.assertLogs("early.web", "WARNING") as logs:
                    self.assertEqual(await app_mod._alert_rpc(self.app, None, "getTransaction", [], paid=True), {"ok": free})
                self.assertNotIn("SECRETKEY", "".join(logs.output))
                broken = False
                self.app["s"]["alerts_paid_per_day"] = self.app["alerts_paid_daily"].count("global")   # the day's share is spent
                asked.clear()
                await app_mod._alert_rpc(self.app, None, "getTransaction", [], paid=True)
                self.assertEqual(asked, [free])
                self.app["s"]["alerts_paid_per_day"] = 1000
                self.app["alerts_paid_month"].limit = self.app["alerts_paid_month"].spent      # or the month's
                asked.clear()
                await app_mod._alert_rpc(self.app, None, "getTransaction", [], paid=True)
                self.assertEqual(asked, [free])
            self.assertEqual(self.app["alerts_paid_month"].spent, 2)                   # free-node requests are not counted

        async def test_the_owner_sees_the_paid_nodes_month(self):
            self.app["alerts_paid_url"] = "https://paid.example/?api-key=SECRETKEY"
            self.app["usage_cache"].clear()
            for _ in range(150):
                app_mod._paid_spent(self.app)
            self.app["usage_cache"].clear()
            rows = [e for e in self.app["events"].read(0) if e.get("event") == "node"]
            self.assertEqual([e["de"] for e in rows], [1, 100])                        # the first at once, then in packs
            self.assertEqual({e["pubkey"] for e in rows}, {"system"})
            html = await (await self.client.get("/admin?tab=costs")).text()
            self.assertIn("Digital Energy a day", html)
            self.assertIn("150", html)
            self.assertIn("7,500,000", html)
            self.assertNotIn("SECRETKEY", html)

        async def test_the_paid_node_leads_the_stream_and_its_key_stays_hidden(self):
            self.app["alerts_paid_url"] = "https://paid.example/?api-key=SECRETKEY"
            self.app["s"].update(alerts_ws_urls=["wss://free.example"], alerts_sub_gap_s=0.05)
            tried, stop = [], asyncio.Event()
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {}, "tags": []}

            async def watch(app, http, url, wm, primary=True):
                tried.append((url, primary))
                if len(tried) == 2:
                    stop.set()
                    await asyncio.sleep(60)
                raise RuntimeError(f"403, message='Invalid', url='{url}'")
            with mock.patch.object(app_mod, "_alerts_watch_once", watch), mock.patch.object(app_mod, "_watch_now", lambda app: {"W": [sub]}), \
                    self.assertLogs("early.web", "WARNING") as logs:
                loop = asyncio.ensure_future(app_mod._alerts_loop(self.app))
                await asyncio.wait_for(stop.wait(), 8)
                loop.cancel()
            self.assertEqual(tried, [("wss://paid.example/?api-key=SECRETKEY", True), ("wss://free.example", False)])
            self.assertNotIn("SECRETKEY", "".join(logs.output))
            self.assertIn("paid.example", "".join(logs.output))

            sent, inbox = [], asyncio.Queue()

            class WS:
                async def send_json(self, m):
                    sent.append(time.monotonic())
                    inbox.put_nowait({"id": m["id"], "result": 100 + m["id"]})

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
            maps = [{}]
            self.app["s"]["alerts_check_s"] = 0.05
            with mock.patch.object(app_mod, "_watch_now", lambda app: maps.pop(0) if maps else {}):
                await asyncio.wait_for(app_mod._alerts_watch_once(self.app, HTTP(), "wss://paid.example/?api-key=SECRETKEY",
                                                                  {"A": [sub], "B": [sub], "C": [sub]}), 5)
            self.assertGreaterEqual(sent[2] - sent[0], 0.09)                           # subscriptions keep their pace
            self.assertEqual(self.app["alerts_state"]["url"], "paid.example")          # what the owner's page shows

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

        async def test_alerts_have_a_daily_share_of_the_data_provider(self):
            # plan 0.8, item 17: past the day's share an alert still goes, without paid lookups (cached name only)
            self.app["s"].update(alerts_per_hour=100, alerts_st_per_day=3)
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {"buys": True, "sells": True, "min_usd": 0}, "tags": [], "src": ""}
            self.app["alerts_wm"] = {"WAL": [sub]}
            self.app["activity"].watch({"WAL"})
            ev = {"side": "buy", "mint": "M" * 32, "usd": 500.0, "amount": 10.0, "before": 0.0, "sig": "", "ts": int(time.time()), "mcap": 1e6}
            calls, texts = {"facts": 0}, []

            async def fetch(app, mint):                       # what a real lookup costs: two requests, counted the real way
                calls["facts"] += 1
                app_mod._alerts_spent(app, 2, mint)
                app["alerts_tok"][mint] = (time.time(), {"symbol": "PAID"})                # and kept for 10 minutes, as the real one
                return {"symbol": "PAID"}

            async def send(app, http, chat, text, pk=None):
                texts.append(text)
                return True

            async def rpc(*a, **k):
                return {"tx": 1}

            async def price(app, http):
                return 150.0
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_sol_price", price), \
                    mock.patch.object(app_mod, "_token_facts_fetch", fetch), mock.patch.object(app_mod, "_tg_send", send), \
                    mock.patch.object(app_mod.alerts_mod, "classify", lambda tx, w, px: [dict(ev)]):
                await app_mod._alert_tx_safe(self.app, None, "WAL", "sig1")                # pays: 2 of 3
                self.app["alerts_tok"].clear()                                             # a token not seen for 10 minutes
                await app_mod._alert_tx_safe(self.app, None, "WAL", "sig2")                # pays again: 4 of 3, the day is used up
                await app_mod._alert_tx_safe(self.app, None, "WAL", "sig3")                # no lookup, the name from memory
                self.app["alerts_tok"].clear()
                await app_mod._alert_tx_safe(self.app, None, "WAL", "sig4")                # no lookup, no name: the short address
            self.assertEqual(calls["facts"], 2)
            self.assertEqual(len(texts), 4)                                                # every trade still alerted
            self.assertIn("$PAID", texts[2])
            self.assertNotIn("$PAID", texts[3])
            self.assertIn("MMMMMM", texts[3])
            self.assertEqual(app_mod._alerts_st_left(self.app), -1)
            st = await (await self.client.get("/me/telegram.json")).json()
            self.assertEqual((st["state"]["st_today"], st["state"]["st_per_day"]), (4, 3))   # the owner sees the day's spend

        async def test_an_account_gets_at_most_its_day_of_alerts(self):
            # owner, 02.10: 200 a day per account; past it one line, then silence until 00:00 UTC. What the hour's cap
            # skipped does not use up the day
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {"buys": True, "sells": True, "min_usd": 0}, "tags": [], "src": ""}
            self.app["alerts_wm"] = {"WAL": [sub]}
            self.app["activity"].watch({"WAL"})
            ev = {"side": "buy", "mint": "M" * 32, "usd": 500.0, "amount": 10.0, "before": 0.0, "sig": "", "ts": int(time.time()), "mcap": 1e6}
            texts = []

            async def send(app, http, chat, text, pk=None):
                texts.append(text)
                return True

            async def rpc(*a, **k):
                return {"tx": 1}

            async def price(app, http):
                return 150.0
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_sol_price", price), \
                    mock.patch.object(app_mod, "_token_facts", mock.AsyncMock(return_value={"symbol": "X"})), mock.patch.object(app_mod, "_tg_send", send), \
                    mock.patch.object(app_mod.alerts_mod, "classify", lambda tx, w, px: [dict(ev)]):
                self.app["s"].update(alerts_per_hour=2, alerts_per_day=3)
                for i in range(4):
                    await app_mod._alert_tx_safe(self.app, None, "WAL", f"h{i}")
                self.assertEqual(len(texts), 3)                                            # two alerts, one line about the hour
                self.assertIn("this hour", texts[-1])
                self.assertEqual(self.app["alerts_day"].left("a:" + TEST_PK, 3), 1)      # the skipped two did not use up the day
                self.app["alerts_hour"].clear()                                             # a new hour
                self.app["s"]["alerts_per_hour"] = 100
                for i in range(4):
                    await app_mod._alert_tx_safe(self.app, None, "WAL", f"d{i}")
            self.assertEqual(len(texts), 5)                                                # one more alert, then the day's line, then silence
            self.assertEqual(self.app["alerts_day"].count("s:" + TEST_PK + ":WAL"), 3)      # what the wallet's card says it sent today
            self.assertIn("alerts today", texts[-1])
            self.assertIn("00:00 UTC", texts[-1])

        async def test_one_wallet_gets_at_most_its_day_of_alerts(self):
            # owner, 02.10: 50 a day from any one wallet, so a bot trading every minute does not use up the account's day.
            # Past it one line about that wallet, then it alone stays silent; the others keep coming
            sub = {"pk": TEST_PK, "chat": 7, "prefs": {"buys": True, "sells": True, "min_usd": 0}, "tags": ["botty"], "src": ""}
            self.app["alerts_wm"] = {"WAL": [sub], "OTHER": [dict(sub, tags=[])]}
            self.app["activity"].watch({"WAL", "OTHER"})
            ev = {"side": "buy", "mint": "M" * 32, "usd": 500.0, "amount": 10.0, "before": 0.0, "sig": "", "ts": int(time.time()), "mcap": 1e6}
            texts = []

            async def send(app, http, chat, text, pk=None):
                texts.append(text)
                return True

            async def rpc(*a, **k):
                return {"tx": 1}

            async def price(app, http):
                return 150.0
            with mock.patch.object(app_mod, "_rpc", rpc), mock.patch.object(app_mod, "_sol_price", price), \
                    mock.patch.object(app_mod, "_token_facts", mock.AsyncMock(return_value={"symbol": "X"})), mock.patch.object(app_mod, "_tg_send", send), \
                    mock.patch.object(app_mod.alerts_mod, "classify", lambda tx, w, px: [dict(ev)]):
                self.app["s"].update(alerts_per_hour=100, alerts_per_day=10, alerts_per_wallet_day=2)
                for i in range(4):
                    await app_mod._alert_tx_safe(self.app, None, "WAL", f"w{i}")
                self.assertEqual(len(texts), 3)                                            # two alerts, then one line about it
                self.assertIn("2 alerts from botty today", texts[-1])
                self.assertIn("00:00 UTC", texts[-1])
                self.assertEqual(self.app["alerts_day"].count("a:" + TEST_PK), 2)         # its silence took nothing from the day
                await app_mod._alert_tx_safe(self.app, None, "OTHER", "o1")              # another wallet still comes through
                self.assertEqual(len(texts), 4)
                self.assertNotIn("⏸", texts[-1])
                self.app["s"]["alerts_per_day"] = 3                                         # the account's day ends first:
                await app_mod._alert_tx_safe(self.app, None, "OTHER", "o2")              # its line, and OTHER keeps its place
                self.assertIn("alerts today", texts[-1])
                self.assertEqual(self.app["alerts_day"].count("c:" + TEST_PK + ":OTHER"), 1)


if __name__ == "__main__":
    unittest.main()
