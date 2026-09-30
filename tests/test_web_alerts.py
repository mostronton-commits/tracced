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
    from tracced.web.app import create_app, tg_reply

    class TestAlertsWeb(AioHTTPTestCase):
        async def get_application(self):
            self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
            app = create_app(FakeWebST(TRADES), settings.load(), {}, out_dir=self.tmp.name + "/web", store_dir=self.tmp.name + "/cache")
            app["admins"] = {TEST_PK}
            app["tg"]["token"], app["tg"]["name"] = "test-token", "tracced_bot"
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
            self.app["tg"]["token"] = ""
            self.assertEqual((await self.client.post("/me/telegram/link", json={}, headers=self.origin)).status, 503)


if __name__ == "__main__":
    unittest.main()
