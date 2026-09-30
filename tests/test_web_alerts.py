"""Сповіщення в Telegram на фейковому клієнті: прив'язка кодом, відповіді бота, налаштування, дзвіночок, закритий тест."""
import asyncio
import tempfile
import unittest

try:
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
        from tests.test_web import FakeWebST, TEST_PK, W1, wallet_cookie
    except ImportError:
        from test_web import FakeWebST, TEST_PK, W1, wallet_cookie
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
            self.app["alerts_wm"] = {"WAL": [sub]}
            ev = {"side": "sell", "mint": "M" * 32, "usd": 500.0, "amount": 10.0, "before": 100.0, "pct": 10, "sig": "", "ts": 1, "mcap": 1e6}
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
            self.assertEqual((calls["facts"], calls["share"]), (2, 2))                     # paid lookups only for the two
            self.app["alerts_wm"] = {}
            with mock.patch.object(app_mod, "_rpc", mock.AsyncMock(side_effect=AssertionError("no one watches"))):
                await app_mod._alert_tx_safe(self.app, None, "WAL", "late")               # nobody watches: not even the node is asked


if __name__ == "__main__":
    unittest.main()
